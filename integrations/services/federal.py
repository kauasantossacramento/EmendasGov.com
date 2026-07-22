"""
Clientes das APIs federais: Transferegov e Portal da Transparência (CGU).

O ciclo de importação:
  1. Transferegov / CGU  → origem do recurso (Emenda)
  2. Contabilidade local → reserva do recurso (Empenho)
  3. PNCP                → execução do recurso (ContratoPNCP)
"""
import logging
import threading
import time
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils import timezone

from emendas.models import Emenda

logger = logging.getLogger(__name__)

TIMEOUT = 30

ZERO = Decimal("0.00")


def _decimal(valor):
    """
    Converte valores da API em Decimal com segurança.

    A CGU devolve valores monetários como texto no formato brasileiro
    ("1.234.567,89") — sem este tratamento, tudo viraria 0,00.
    Aceita também números e strings com ponto decimal ("1234567.89").
    """
    if valor is None:
        return ZERO
    if isinstance(valor, (int, float, Decimal)):
        try:
            return Decimal(str(valor)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return ZERO
    texto = str(valor).replace("R$", "").strip()
    if not texto:
        return ZERO
    if "," in texto:
        # Formato brasileiro: remove separador de milhar e troca a vírgula
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation:
        return ZERO


def _normalizar(texto):
    """Remove acentos e caixa para comparação tolerante de nomes."""
    return (
        unicodedata.normalize("NFKD", str(texto or ""))
        .encode("ascii", "ignore")
        .decode()
        .upper()
        .strip()
    )


class PortalTransparenciaClient:
    """
    Consulta emendas parlamentares na API do Portal da Transparência (CGU).

    Respeita os limites oficiais da API (400 req/min em horário comercial,
    700 req/min de madrugada): intervalo mínimo entre requisições
    (CGU_INTERVALO_REQUISICOES) e teto de páginas por execução
    (CGU_MAX_PAGINAS), evitando a suspensão do token.
    """

    def __init__(self):
        self.base = settings.PORTAL_TRANSPARENCIA_API_BASE.rstrip("/")
        self.headers = {
            "chave-api-dados": settings.PORTAL_TRANSPARENCIA_API_KEY,
            "Accept": "application/json",
        }

    def emendas_do_ano(self, ano):
        """GET /api-de-dados/emendas — pagina com throttle até esgotar o ano."""
        pagina = 1
        while pagina <= settings.CGU_MAX_PAGINAS:
            resp = requests.get(
                f"{self.base}/api-de-dados/emendas",
                params={"ano": ano, "pagina": pagina},
                headers=self.headers,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            lote = resp.json()
            if not lote:
                return
            yield from lote
            pagina += 1
            time.sleep(settings.CGU_INTERVALO_REQUISICOES)
        logger.warning(
            "CGU: teto de %s páginas atingido para o ano %s — sincronização "
            "parcial; rode novamente para continuar.",
            settings.CGU_MAX_PAGINAS, ano,
        )


class TransferegovClient:
    """Consulta planos de ação de emendas especiais no Transferegov."""

    def __init__(self):
        self.base = settings.TRANSFEREGOV_API_BASE.rstrip("/")

    def planos_de_acao(self, codigo_ibge, ano):
        resp = requests.get(
            f"{self.base}/fundoafundo/plano_acao",
            params={
                "codigo_ibge_municipio": f"eq.{codigo_ibge}",
                "ano": f"eq.{ano}",
            },
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


def _area_por_funcao(funcao: str) -> str:
    funcao = (funcao or "").lower()
    mapa = {
        "saúde": "saude", "saude": "saude",
        "educação": "educacao", "educacao": "educacao",
        "urbanismo": "infraestrutura", "transporte": "infraestrutura",
        "saneamento": "infraestrutura", "infraestrutura": "infraestrutura",
        "assistência social": "assistencia_social",
        "assistencia social": "assistencia_social",
        "administração": "custeio", "administracao": "custeio",
    }
    return mapa.get(funcao, "outros")


def anos_pendentes(tenant, ano_fim=None):
    """
    Exercícios que ainda precisam ser sincronizados para o tenant.

    Regra incremental: exercícios históricos já sincronizados com SUCESSO
    são pulados (os dados já estão gravados no banco local); o exercício
    corrente é sempre re-sincronizado, pois novas emendas e atualizações
    continuam chegando ao longo do ano. O `update_or_create` garante que
    nada é duplicado nas repetições.
    """
    from integrations.models import SincronizacaoEmendas, StatusSincronizacao

    ano_fim = ano_fim or timezone.localdate().year
    ja_sincronizados = set(
        SincronizacaoEmendas.objects.filter(
            tenant=tenant,
            status=StatusSincronizacao.SUCESSO,
            ano__lt=ano_fim,
        ).values_list("ano", flat=True)
    )
    return [
        ano
        for ano in range(tenant.ano_inicio_sincronizacao, ano_fim + 1)
        if ano == ano_fim or ano not in ja_sincronizados
    ]


def sincronizar_tenant(tenant, ano_fim=None, apenas_ano=None):
    """
    Sincroniza o tenant de forma incremental, registrando cada execução.

    Primeira execução: carga histórica completa (ano_inicio_sincronizacao
    até hoje). Execuções seguintes: apenas exercícios pendentes + o ano
    corrente. Com `apenas_ano`, sincroniza um único exercício — útil para
    cargas manuais controladas, evitando o loop completo e respeitando os
    limites da API. Retorna os registros SincronizacaoEmendas gerados.
    """
    from integrations.models import SincronizacaoEmendas, StatusSincronizacao

    anos = [int(apenas_ano)] if apenas_ano else anos_pendentes(tenant, ano_fim)
    execucoes = []
    for ano in anos:
        log = SincronizacaoEmendas.objects.create(tenant=tenant, ano=ano)
        try:
            criadas, atualizadas = sincronizar_emendas(tenant, ano)
        except Exception as exc:  # noqa: BLE001 — registra e segue o backfill
            log.status = StatusSincronizacao.ERRO
            log.mensagem_erro = str(exc)[:2000]
            logger.exception("Sync %s/%s falhou", tenant.slug, ano)
        else:
            log.status = StatusSincronizacao.SUCESSO
            log.emendas_criadas = criadas
            log.emendas_atualizadas = atualizadas
        log.concluido_em = timezone.now()
        log.save()
        execucoes.append(log)
    return execucoes


def sincronizacao_em_andamento(tenant):
    """
    Há uma sincronização deste tenant rodando agora?

    Considera apenas execuções 'executando' recentes (últimas 2 horas):
    se o servidor reiniciar no meio de uma carga, o registro órfão não
    bloqueia novas sincronizações para sempre.
    """
    from integrations.models import SincronizacaoEmendas, StatusSincronizacao

    limite = timezone.now() - timedelta(hours=2)
    return SincronizacaoEmendas.objects.filter(
        tenant=tenant,
        status=StatusSincronizacao.EXECUTANDO,
        iniciado_em__gte=limite,
    ).exists()


def sincronizar_tenant_em_segundo_plano(tenant, ano_fim=None, apenas_ano=None):
    """
    Dispara a sincronização em uma thread de segundo plano e retorna de
    imediato — o gestor pode sair da página; o andamento fica visível no
    histórico (registros 'Executando' → 'Sucesso'/'Erro').

    Retorna True se a carga foi iniciada, False se já havia uma em
    andamento para o tenant (trava anti-duplicidade).
    """
    from django.db import connections

    if sincronizacao_em_andamento(tenant):
        return False

    def _executar():
        try:
            sincronizar_tenant(tenant, ano_fim=ano_fim, apenas_ano=apenas_ano)
        except Exception:  # noqa: BLE001 — nunca derruba o worker
            logger.exception(
                "Sincronização em segundo plano falhou para %s", tenant.slug
            )
        finally:
            connections.close_all()

    threading.Thread(
        target=_executar,
        name=f"sync-{tenant.slug}",
        daemon=True,
    ).start()
    return True


# ---------------------------------------------------------------------------
# Base nacional: uma carga por ano abastece todos os municípios
# ---------------------------------------------------------------------------

# Ano corrente: uma nova carga nacional só é feita se a última tiver mais
# que este intervalo (evita re-baixar o Brasil a cada clique de gestor).
CARGA_NACIONAL_VALIDADE_HORAS = 20


def sincronizar_nacional(ano, forcar=False):
    """
    Baixa TODAS as emendas do exercício (Brasil inteiro) para a base
    nacional (EmendaNacional). Executada uma única vez por exercício
    histórico; para o ano corrente, revalidada a cada 20h.

    Retorna o registro CargaNacional da carga usada (nova ou aproveitada).
    """
    from integrations.models import CargaNacional, EmendaNacional, StatusSincronizacao

    ultima = (
        CargaNacional.objects.filter(ano=ano, status=StatusSincronizacao.SUCESSO)
        .order_by("-concluido_em")
        .first()
    )
    if ultima and not forcar:
        if ano < timezone.localdate().year:
            return ultima  # exercício encerrado: carga única basta
        if ultima.concluido_em and (
            timezone.now() - ultima.concluido_em
            < timedelta(hours=CARGA_NACIONAL_VALIDADE_HORAS)
        ):
            return ultima  # ano corrente já atualizado nas últimas horas

    log = CargaNacional.objects.create(ano=ano)
    client = PortalTransparenciaClient()
    novos = atualizados = 0
    try:
        for registro in client.emendas_do_ano(ano):
            numero = registro.get("codigoEmenda") or registro.get("numeroEmenda")
            if not numero:
                continue
            localidade = registro.get("localidadeDoGasto", "") or ""
            _, criado = EmendaNacional.objects.update_or_create(
                numero=str(numero),
                ano=int(registro.get("ano") or ano),
                defaults={
                    "autor": registro.get("autor", "") or "",
                    "funcao": registro.get("funcao", "") or "",
                    "localidade": localidade[:255],
                    "localidade_normalizada": _normalizar(localidade)[:255],
                    "valor_total": _decimal(registro.get("valorEmpenhado")),
                    "dados": registro,
                },
            )
            if criado:
                novos += 1
            else:
                atualizados += 1
    except Exception as exc:  # noqa: BLE001
        log.status = StatusSincronizacao.ERRO
        log.mensagem_erro = str(exc)[:2000]
        log.concluido_em = timezone.now()
        log.save()
        raise
    log.status = StatusSincronizacao.SUCESSO
    log.registros_novos = novos
    log.registros_atualizados = atualizados
    log.concluido_em = timezone.now()
    log.save()
    logger.info("Carga nacional %s: %s novas, %s atualizadas", ano, novos, atualizados)
    return log


def materializar_emendas(tenant, ano):
    """
    Copia da base nacional para o município as emendas cuja localidade do
    gasto referencia o tenant. Sem chamadas à API — é só banco de dados.
    Retorna (criadas, atualizadas).
    """
    from integrations.models import EmendaNacional

    alvo = _normalizar(tenant.nome)
    if not alvo:
        return 0, 0
    criadas = atualizadas = 0
    registros = EmendaNacional.objects.filter(
        ano=ano, localidade_normalizada__contains=alvo
    )
    for registro in registros:
        _, criado = Emenda.objects.update_or_create(
            tenant=tenant,
            numero=registro.numero,
            ano=registro.ano,
            defaults={
                "parlamentar": registro.autor or "Não informado",
                "valor_total": registro.valor_total,
                "area_aplicacao": _area_por_funcao(registro.funcao),
                "objeto": registro.localidade,
                "codigo_transferegov": registro.numero,
                "fonte_importacao": "cgu",
                "importado_em": timezone.now(),
            },
        )
        if criado:
            criadas += 1
        else:
            atualizadas += 1
    return criadas, atualizadas


def sincronizar_emendas(tenant, ano):
    """
    Garante a base nacional do exercício (baixando da CGU apenas se ainda
    não existir ou estiver vencida) e materializa as emendas do município
    a partir dela. Retorna (criadas, atualizadas).
    """
    sincronizar_nacional(ano)
    criadas, atualizadas = materializar_emendas(tenant, ano)
    logger.info(
        "Sync %s/%s: %s criadas, %s atualizadas (via base nacional)",
        tenant.slug, ano, criadas, atualizadas,
    )
    return criadas, atualizadas


def materializar_tenant_completo(tenant):
    """
    Ao criar um município no painel, aproveita tudo o que a base nacional
    já tem: materializa cada exercício carregado e registra o log de
    sincronização correspondente — o portal nasce com dados, sem API.
    """
    from integrations.models import (
        CargaNacional,
        SincronizacaoEmendas,
        StatusSincronizacao,
    )

    anos_carregados = (
        CargaNacional.objects.filter(status=StatusSincronizacao.SUCESSO)
        .values_list("ano", flat=True)
        .distinct()
    )
    execucoes = []
    for ano in sorted(anos_carregados):
        if ano < tenant.ano_inicio_sincronizacao:
            continue
        criadas, atualizadas = materializar_emendas(tenant, ano)
        execucoes.append(
            SincronizacaoEmendas.objects.create(
                tenant=tenant,
                ano=ano,
                status=StatusSincronizacao.SUCESSO,
                emendas_criadas=criadas,
                emendas_atualizadas=atualizadas,
                concluido_em=timezone.now(),
            )
        )
    return execucoes
