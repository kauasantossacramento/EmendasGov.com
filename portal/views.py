import csv
import json

from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from emendas.models import ContratoPNCP, Emenda, Empenho
from integrations.services import gemini
from tenants.models import Tenant

from .models import ConfiguracaoPlataforma
from .security import captcha_liberado, requer_captcha, validar_token

ITENS_POR_PAGINA = 15

# Destaques exibidos na faixa da landing enquanto o administrador não
# cadastra os seus (foco em recursos da plataforma, não em volume).
DESTAQUES_PADRAO = [
    {"valor": "3", "rotulo": "Bases federais integradas (CGU · Transferegov · PNCP)"},
    {"valor": "100%", "rotulo": "Dados oficiais, direto de Brasília"},
    {"valor": "24/7", "rotulo": "Assistente de IA ao cidadão"},
    {"valor": "30 dias", "rotulo": "Trava de conformidade PNCP"},
]


def _emendas_do_tenant(municipio_slug):
    """Isolamento de rota: TODO queryset público parte deste filtro."""
    return Emenda.objects.do_tenant(municipio_slug)


def _empenhos_do_tenant(municipio_slug):
    return Empenho.objects.do_tenant(municipio_slug)


# ---------------------------------------------------------------------------
# Landing page da plataforma (identidade EmendasGov.com)
# ---------------------------------------------------------------------------

def landing(request):
    municipios = Tenant.objects.filter(ativo=True)
    config = ConfiguracaoPlataforma.carregar()

    estatisticas = destaques = None
    if config.exibir_estatisticas:
        if config.usar_dados_reais:
            base = Emenda.objects.filter(tenant__ativo=True)
            estatisticas = {
                "municipios": municipios.count(),
                "emendas": base.count(),
                "volume": float(base.aggregate(t=Sum("valor_total"))["t"] or 0),
                "contratos": ContratoPNCP.objects.filter(
                    empenho__emenda__tenant__ativo=True
                ).count(),
            }
        else:
            destaques = list(config.destaques.all()) or DESTAQUES_PADRAO

    return render(request, "plataforma/landing.html", {
        "municipios": municipios,
        "exibir_estatisticas": config.exibir_estatisticas,
        "estatisticas": estatisticas,
        "destaques": destaques,
    })


# ---------------------------------------------------------------------------
# Login único da plataforma (gestores municipais e administradores)
# ---------------------------------------------------------------------------

def login_global(request):
    """
    Tela de login única. Após autenticar, direciona pelo perfil:
      - superusuário (desenvolvedor/operação) → /superadmin/
      - gestor municipal → painel do município ao qual está vinculado
      - usuário sem vínculo → sessão encerrada + orientação

    Um `?next=` local tem prioridade; as telas de destino revalidam a
    permissão por conta própria (requer_gestor / admin do Django).
    """
    from django.contrib.auth import login as auth_login
    from django.contrib.auth import logout as auth_logout
    from django.contrib.auth.forms import AuthenticationForm

    config = ConfiguracaoPlataforma.carregar()
    form = AuthenticationForm(request, data=request.POST or None)
    erro_vinculo = None

    if request.method == "POST" and form.is_valid():
        usuario = form.get_user()
        auth_login(request, usuario)

        destino = request.GET.get("next", "")
        if destino.startswith("/") and not destino.startswith("//"):
            return redirect(destino)
        if usuario.is_superuser:
            return redirect("painel_dev")
        gestoria = usuario.gestorias.select_related("tenant").first()
        if gestoria:
            return redirect("gestor:painel", municipio_slug=gestoria.tenant.slug)
        # Autenticou, mas não gerencia nenhum município: não deixa sessão ativa.
        auth_logout(request)
        erro_vinculo = (
            "Seu usuário ainda não está vinculado a nenhum município. "
            "Solicite o vínculo ao administrador da plataforma."
        )

    return render(request, "plataforma/login.html", {
        "form": form,
        "erro_vinculo": erro_vinculo,
        "imagem_fundo": config.imagem_fundo_login,
    })


# ---------------------------------------------------------------------------
# Gateway de segurança (reCAPTCHA)
# ---------------------------------------------------------------------------

def gateway(request, municipio_slug):
    destino = request.GET.get("next") or reverse(
        "portal:pesquisa", args=[municipio_slug]
    )
    if not destino.startswith("/"):
        destino = reverse("portal:pesquisa", args=[municipio_slug])
    if captcha_liberado(request):
        return redirect(destino)
    erro = None
    if request.method == "POST":
        token = request.POST.get("g-recaptcha-response", "")
        if token and validar_token(request, token):
            return redirect(destino)
        erro = "Não foi possível validar o desafio. Por favor, tente novamente."
    return render(
        request,
        "portal/gateway.html",
        {"erro": erro, "next": destino},
    )


# ---------------------------------------------------------------------------
# Dashboard inicial do município (KPIs + gráficos)
# ---------------------------------------------------------------------------

def dashboard(request, municipio_slug):
    emendas = _emendas_do_tenant(municipio_slug)
    anos = list(
        emendas.values_list("ano", flat=True).distinct().order_by("-ano")
    )
    ano_atual = timezone.localdate().year
    try:
        ano = int(request.GET.get("ano", ""))
    except ValueError:
        ano = 0
    if ano not in anos:
        ano = ano_atual if ano_atual in anos else (anos[0] if anos else ano_atual)

    do_ano = emendas.filter(ano=ano)
    empenhos_ano = _empenhos_do_tenant(municipio_slug).filter(emenda__ano=ano)

    # --- Faixa de KPIs -----------------------------------------------------
    total_emendas = do_ano.count()
    volume_total = do_ano.aggregate(t=Sum("valor_total"))["t"] or 0
    vinculados = (
        empenhos_ano.filter(status_rastreabilidade="vinculado")
        .aggregate(t=Sum("valor_empenhado"))["t"] or 0
    )
    taxa_execucao = round(float(vinculados) / float(volume_total) * 100) if volume_total else 0

    por_area = list(
        do_ano.values("area_aplicacao")
        .annotate(total=Sum("valor_total"))
        .order_by("-total")
    )
    area_top = None
    if por_area and volume_total:
        rotulos = dict(Emenda._meta.get_field("area_aplicacao").choices)
        area_top = {
            "nome": rotulos.get(por_area[0]["area_aplicacao"], "Outros"),
            "percentual": round(float(por_area[0]["total"]) / float(volume_total) * 100),
        }

    # --- Gráficos ----------------------------------------------------------
    rotulos_area = dict(Emenda._meta.get_field("area_aplicacao").choices)

    mensal = [0.0] * 12
    for e in do_ano.exclude(data_recebimento=None):
        mensal[e.data_recebimento.month - 1] += float(e.valor_total)

    ranking = list(
        do_ano.values("parlamentar")
        .annotate(total=Sum("valor_total"), qtd=Count("id"))
        .order_by("-total")
    )

    # Sankey: Parlamentar -> Município -> Fornecedores (contratos PNCP)
    municipio_nome = request.tenant.nome if request.tenant else "Município"
    sankey = []
    for r in ranking[:8]:
        sankey.append({
            "from": r["parlamentar"], "to": municipio_nome, "flow": float(r["total"]),
        })
    destinos = (
        empenhos_ano.exclude(fornecedor_nome="")
        .values("fornecedor_nome")
        .annotate(total=Sum("valor_empenhado"))
        .order_by("-total")[:8]
    )
    for d in destinos:
        sankey.append({
            "from": municipio_nome, "to": d["fornecedor_nome"], "flow": float(d["total"]),
        })

    graficos = {
        "mensal": mensal,
        "ranking": {
            "labels": [r["parlamentar"] for r in ranking[:5]],
            "valores": [float(r["total"]) for r in ranking[:5]],
        },
        "areas": {
            "labels": [rotulos_area.get(a["area_aplicacao"], "Outros") for a in por_area],
            "valores": [float(a["total"]) for a in por_area],
        },
        "sankey": sankey,
    }

    return render(request, "portal/dashboard.html", {
        "ano": ano,
        "anos": anos,
        "kpi_total_emendas": total_emendas,
        "kpi_volume_total": volume_total,
        "kpi_taxa_execucao": taxa_execucao,
        "kpi_area_top": area_top,
        # Dict puro: o filtro json_script do template faz a serialização.
        # (json.dumps aqui causaria dupla codificação — o JS receberia uma
        # string em vez de objeto e os gráficos ficariam vazios.)
        "graficos": graficos,
        "ranking_completo": ranking,
    })


# ---------------------------------------------------------------------------
# Nível 1 — Painel de pesquisa e listagem
# ---------------------------------------------------------------------------

def _filtrar_emendas(request, municipio_slug):
    qs = _emendas_do_tenant(municipio_slug)
    ano = request.GET.get("ano", "").strip()
    parlamentar = request.GET.get("parlamentar", "").strip()
    razao_social = request.GET.get("razao_social", "").strip()
    fornecedor = request.GET.get("fornecedor", "").strip()

    if ano.isdigit():
        qs = qs.filter(ano=int(ano))
    if parlamentar:
        qs = qs.filter(parlamentar__icontains=parlamentar)
    if razao_social:
        qs = qs.filter(
            Q(empenhos__fornecedor_nome__icontains=razao_social)
            | Q(empenhos__fornecedor_cnpj__icontains=razao_social)
        )
    if fornecedor:
        qs = qs.filter(empenhos__fornecedor_nome__icontains=fornecedor)
    return qs.distinct()


@requer_captcha
def pesquisa(request, municipio_slug):
    qs = _filtrar_emendas(request, municipio_slug)
    anos = (
        _emendas_do_tenant(municipio_slug)
        .values_list("ano", flat=True).distinct().order_by("-ano")
    )
    parlamentares = (
        _emendas_do_tenant(municipio_slug)
        .values_list("parlamentar", flat=True).distinct().order_by("parlamentar")
    )
    try:
        por_pagina = min(max(int(request.GET.get("por_pagina", ITENS_POR_PAGINA)), 10), 20)
    except ValueError:
        por_pagina = ITENS_POR_PAGINA
    paginator = Paginator(qs, por_pagina)
    pagina = paginator.get_page(request.GET.get("pagina"))

    parametros = request.GET.copy()
    parametros.pop("pagina", None)

    return render(request, "portal/pesquisa.html", {
        "pagina": pagina,
        "anos": anos,
        "parlamentares": parlamentares,
        "por_pagina": por_pagina,
        "querystring": parametros.urlencode(),
    })


@requer_captcha
def exportar_emendas(request, municipio_slug):
    qs = _filtrar_emendas(request, municipio_slug)
    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = (
        f'attachment; filename="emendas-{municipio_slug}.csv"'
    )
    resposta.write("\ufeff")  # BOM para o Excel abrir com acentuação correta
    escritor = csv.writer(resposta, delimiter=";")
    escritor.writerow([
        "Nº da Emenda", "Parlamentar", "Exercício", "Área",
        "Orçamento (R$)", "Empenhado (R$)", "Liquidado (R$)", "Pago (R$)",
    ])
    for e in qs:
        escritor.writerow([
            e.numero, e.parlamentar, e.ano, e.get_area_aplicacao_display(),
            e.valor_total, e.total_empenhado, e.total_liquidado, e.total_pago,
        ])
    return resposta


# ---------------------------------------------------------------------------
# Nível 2 — Resumo da emenda (drill-down 1)
# ---------------------------------------------------------------------------

@requer_captcha
def emenda_detalhe(request, municipio_slug, emenda_id):
    emenda = get_object_or_404(
        _emendas_do_tenant(municipio_slug).prefetch_related(
            "empenhos__contratos_pncp"
        ),
        pk=emenda_id,
    )
    return render(request, "portal/emenda_detalhe.html", {"emenda": emenda})


@requer_captcha
def exportar_empenhos(request, municipio_slug, emenda_id):
    emenda = get_object_or_404(_emendas_do_tenant(municipio_slug), pk=emenda_id)
    resposta = HttpResponse(content_type="text/csv; charset=utf-8")
    resposta["Content-Disposition"] = (
        f'attachment; filename="empenhos-emenda-{emenda.numero}-{emenda.ano}.csv"'
    )
    resposta.write("\ufeff")
    escritor = csv.writer(resposta, delimiter=";")
    escritor.writerow([
        "Nº do Empenho", "Data", "Fornecedor (CNPJ)", "Fornecedor (Razão Social)",
        "Empenhado (R$)", "Liquidado (R$)", "Pago (R$)", "A Liquidar (R$)", "A Pagar (R$)",
    ])
    for emp in emenda.empenhos.all():
        escritor.writerow([
            emp.numero, emp.data_empenho.strftime("%d/%m/%Y"),
            emp.fornecedor_cnpj, emp.fornecedor_nome,
            emp.valor_empenhado, emp.valor_liquidado, emp.valor_pago,
            emp.valor_a_liquidar, emp.valor_a_pagar,
        ])
    return resposta


# ---------------------------------------------------------------------------
# Nível 3 — Detalhamento do empenho + vínculo contratual PNCP (drill-down 2)
# ---------------------------------------------------------------------------

@requer_captcha
def empenho_detalhe(request, municipio_slug, emenda_id, empenho_id):
    empenho = get_object_or_404(
        _empenhos_do_tenant(municipio_slug)
        .select_related("emenda")
        .prefetch_related("contratos_pncp"),
        pk=empenho_id,
        emenda_id=emenda_id,
    )
    return render(request, "portal/empenho_detalhe.html", {
        "empenho": empenho,
        "emenda": empenho.emenda,
        "contratos": empenho.contratos_pncp.all(),
    })


# ---------------------------------------------------------------------------
# Assistente de Transparência IA (Gemini RAG)
# ---------------------------------------------------------------------------

@require_POST
def chat_assistente(request, municipio_slug):
    tenant = get_object_or_404(Tenant, slug=municipio_slug, ativo=True)
    try:
        corpo = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"erro": "Requisição inválida."}, status=400)
    pergunta = (corpo.get("pergunta") or "").strip()
    if not pergunta:
        return JsonResponse({"erro": "Faça uma pergunta."}, status=400)
    resposta = gemini.perguntar(tenant, pergunta)
    return JsonResponse({"resposta": resposta})
