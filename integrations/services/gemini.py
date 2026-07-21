"""
Assistente de Transparência IA — RAG sobre a API do Google Gemini.

Fluxo:
  1. Injeção de contexto: busca no banco os dados do tenant relevantes à pergunta.
  2. Prompt de sistema estrito: o modelo só responde com base nos dados fornecidos.
  3. Resposta em linguagem natural, pedagógica e restrita ao município.
"""
import json
import logging

import requests
from django.conf import settings
from django.db.models import Q, Sum

from emendas.models import Emenda, Empenho

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

SYSTEM_PROMPT = """Você é o Assistente de Transparência do portal EmendasGov.com \
do município de {municipio}. Sua missão é aproximar o cidadão dos dados públicos.

REGRAS ESTRITAS:
1. Responda APENAS com base nos dados financeiros fornecidos no contexto JSON abaixo. \
Se a informação não estiver no contexto, diga que não tem essa informação e oriente o \
cidadão a usar os filtros de pesquisa do portal.
2. Responda somente sobre emendas parlamentares, empenhos e contratos DESTE município. \
Não responda sobre política geral, opiniões, outros municípios ou qualquer outro assunto.
3. Use linguagem pedagógica, não burocrática: traduza termos técnicos \
(ex.: explique o que significa "empenho", "liquidação", "elemento de despesa").
4. Formate valores em reais no padrão brasileiro (R$ 1.234.567,89).
5. Seja acolhedor e cordial, com foco no impacto local do recurso federal.

DADOS FINANCEIROS DO MUNICÍPIO (contexto):
{contexto}
"""


def _montar_contexto(tenant, pergunta: str) -> str:
    """Injeção de contexto (RAG): seleciona os dados do tenant para o prompt."""
    emendas = Emenda.objects.filter(tenant=tenant)

    # Recorte simples por termos da pergunta (parlamentar, número, ano)
    termos = [t for t in pergunta.split() if len(t) >= 4]
    filtro = Q()
    for termo in termos:
        filtro |= (
            Q(parlamentar__icontains=termo)
            | Q(numero__icontains=termo)
            | Q(objeto__icontains=termo)
        )
    relevantes = emendas.filter(filtro) if termos else emendas.none()
    selecao = (relevantes if relevantes.exists() else emendas)[:50]

    resumo_areas = (
        emendas.values("area_aplicacao")
        .annotate(total=Sum("valor_total"))
        .order_by("-total")
    )
    resumo_parlamentares = (
        emendas.values("parlamentar")
        .annotate(total=Sum("valor_total"))
        .order_by("-total")[:10]
    )

    dados = {
        "municipio": str(tenant),
        "totais_por_area": [
            {"area": r["area_aplicacao"], "valor_total": float(r["total"] or 0)}
            for r in resumo_areas
        ],
        "ranking_parlamentares": [
            {"parlamentar": r["parlamentar"], "valor_total": float(r["total"] or 0)}
            for r in resumo_parlamentares
        ],
        "emendas": [
            {
                "numero": e.numero,
                "ano": e.ano,
                "parlamentar": e.parlamentar,
                "area": e.get_area_aplicacao_display(),
                "valor_total": float(e.valor_total),
                "valor_empenhado": float(e.total_empenhado),
                "valor_liquidado": float(e.total_liquidado),
                "valor_pago": float(e.total_pago),
                "objeto": e.objeto[:300],
                "empenhos": [
                    {
                        "numero": emp.numero,
                        "data": emp.data_empenho.isoformat(),
                        "fornecedor": emp.fornecedor_nome,
                        "valor_empenhado": float(emp.valor_empenhado),
                        "valor_pago": float(emp.valor_pago),
                        "status": emp.get_status_rastreabilidade_display(),
                        "contratos_pncp": [
                            {
                                "numero_contrato": c.numero_contrato,
                                "modalidade": c.get_modalidade_display(),
                                "id_pncp": c.id_pncp,
                                "url_pncp": c.url_pncp,
                            }
                            for c in emp.contratos_pncp.all()
                        ],
                    }
                    for emp in e.empenhos.all()[:20]
                ],
            }
            for e in selecao
        ],
    }
    return json.dumps(dados, ensure_ascii=False)


def perguntar(tenant, pergunta: str) -> str:
    """Envia a pergunta do cidadão ao Gemini com o contexto do tenant."""
    if not settings.GEMINI_API_KEY:
        return (
            "O assistente de IA ainda não está configurado neste portal. "
            "Você pode consultar todas as emendas usando os filtros de pesquisa."
        )

    prompt_sistema = SYSTEM_PROMPT.format(
        municipio=str(tenant),
        contexto=_montar_contexto(tenant, pergunta),
    )
    payload = {
        "system_instruction": {"parts": [{"text": prompt_sistema}]},
        "contents": [{"role": "user", "parts": [{"text": pergunta[:1000]}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    try:
        resp = requests.post(
            GEMINI_URL.format(model=settings.GEMINI_MODEL, key=settings.GEMINI_API_KEY),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        corpo = resp.json()
        return corpo["candidates"][0]["content"]["parts"][0]["text"]
    except (requests.RequestException, KeyError, IndexError):
        logger.exception("Falha ao consultar o Gemini para o tenant %s", tenant.slug)
        return (
            "Não consegui processar sua pergunta agora. Nossos sistemas podem "
            "estar atualizando as informações — tente novamente em instantes."
        )
