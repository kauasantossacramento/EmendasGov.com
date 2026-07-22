"""
Clientes das APIs federais: Transferegov e Portal da Transparência (CGU).

O ciclo de importação:
  1. Transferegov / CGU  → origem do recurso (Emenda)
  2. Contabilidade local → reserva do recurso (Empenho)
  3. PNCP                → execução do recurso (ContratoPNCP)
"""
import logging
import time
import unicodedata
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


def _refere_ao_municipio(registro, tenant):
    """
    O endpoint /api-de-dados/emendas da CGU não filtra por município de
    forma confiável — pode devolver emendas do país inteiro. Validamos
    cada registro pela localidade do gasto (e campos afins) antes de
    gravar, para não poluir o portal com emendas de outras cidades.
    """
    campos = " ".join(
        str(registro.get(campo, ""))
        for campo in ("localidadeDoGasto", "municipio", "nomeMunicipio")
    )
    codigo = str(registro.get("codigoIbgeMunicipio", "") or registro.get("codigoMunicipio", ""))
    if tenant.codigo_ibge and codigo and codigo.strip() == tenant.codigo_ibge.strip():
        return True
    alvo = _normalizar(tenant.nome)
    return bool(alvo) and alvo in _normalizar(campos)


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

    def emendas_por_municipio(self, codigo_ibge, ano):
        """GET /api-de-dados/emendas — pagina com throttle até esgotar o ano."""
        pagina = 1
        while pagina <= settings.CGU_MAX_PAGINAS:
            resp = requests.get(
                f"{self.base}/api-de-dados/emendas",
                params={
                    "codigoIbgeMunicipio": codigo_ibge,
                    "ano": ano,
                    "pagina": pagina,
                },
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


def sincronizar_emendas(tenant, ano):
    """
    Importa/atualiza as emendas do município a partir do Portal da
    Transparência (CGU). Retorna (criadas, atualizadas).
    """
    if not tenant.codigo_ibge:
        raise ValueError(
            f"Tenant '{tenant.slug}' sem código IBGE configurado — "
            "impossível consultar as APIs federais."
        )

    client = PortalTransparenciaClient()
    criadas = atualizadas = ignoradas = 0
    for registro in client.emendas_por_municipio(tenant.codigo_ibge, ano):
        numero = registro.get("codigoEmenda") or registro.get("numeroEmenda")
        if not numero:
            continue
        if not _refere_ao_municipio(registro, tenant):
            ignoradas += 1
            continue
        _, criado = Emenda.objects.update_or_create(
            tenant=tenant,
            numero=str(numero),
            ano=int(registro.get("ano") or ano),
            defaults={
                "parlamentar": registro.get("autor", "") or "Não informado",
                "valor_total": _decimal(registro.get("valorEmpenhado")),
                "area_aplicacao": _area_por_funcao(registro.get("funcao", "")),
                "objeto": registro.get("localidadeDoGasto", "") or "",
                "codigo_transferegov": str(registro.get("codigoEmenda") or ""),
                "fonte_importacao": "cgu",
                "importado_em": timezone.now(),
            },
        )
        if criado:
            criadas += 1
        else:
            atualizadas += 1
    logger.info(
        "Sync %s/%s: %s criadas, %s atualizadas, %s de outros municípios ignoradas",
        tenant.slug, ano, criadas, atualizadas, ignoradas,
    )
    return criadas, atualizadas
