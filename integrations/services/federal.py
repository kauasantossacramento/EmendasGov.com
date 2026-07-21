"""
Clientes das APIs federais: Transferegov e Portal da Transparência (CGU).

O ciclo de importação:
  1. Transferegov / CGU  → origem do recurso (Emenda)
  2. Contabilidade local → reserva do recurso (Empenho)
  3. PNCP                → execução do recurso (ContratoPNCP)
"""
import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.utils import timezone

from emendas.models import Emenda

logger = logging.getLogger(__name__)

TIMEOUT = 30


def _decimal(valor):
    try:
        return Decimal(str(valor or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


class PortalTransparenciaClient:
    """Consulta emendas parlamentares na API do Portal da Transparência (CGU)."""

    def __init__(self):
        self.base = settings.PORTAL_TRANSPARENCIA_API_BASE.rstrip("/")
        self.headers = {
            "chave-api-dados": settings.PORTAL_TRANSPARENCIA_API_KEY,
            "Accept": "application/json",
        }

    def emendas_por_municipio(self, codigo_ibge, ano):
        """
        GET /api-de-dados/emendas — pagina automaticamente até esgotar
        os resultados do município/ano informados.
        """
        pagina = 1
        while True:
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
                break
            yield from lote
            pagina += 1


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
    criadas = atualizadas = 0
    for registro in client.emendas_por_municipio(tenant.codigo_ibge, ano):
        numero = registro.get("codigoEmenda") or registro.get("numeroEmenda")
        if not numero:
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
        "Sync %s/%s: %s criadas, %s atualizadas",
        tenant.slug, ano, criadas, atualizadas,
    )
    return criadas, atualizadas
