from functools import wraps

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from emendas.models import Emenda, Empenho, StatusRastreabilidade
from integrations.services.federal import anos_pendentes, sincronizar_tenant
from tenants.models import Tenant

from .forms import ConfiguracaoTenantForm, VinculoContratualForm


def _pode_gerir(usuario, tenant) -> bool:
    if not usuario.is_authenticated:
        return False
    if usuario.is_superuser:
        return True
    return tenant.gestores.filter(usuario=usuario).exists()


def requer_gestor(view_func):
    """Garante autenticação e vínculo do usuário com o tenant da rota."""

    @wraps(view_func)
    def wrapper(request, municipio_slug, *args, **kwargs):
        tenant = get_object_or_404(Tenant, slug=municipio_slug)
        if not _pode_gerir(request.user, tenant):
            if request.user.is_authenticated:
                raise Http404("Você não tem acesso ao painel deste município.")
            return redirect(
                f"{reverse('login_global')}?next={request.get_full_path()}"
            )
        request.tenant = tenant
        return view_func(request, municipio_slug, *args, **kwargs)

    return wrapper


def login_view(request, municipio_slug):
    """Compatibilidade: o login agora é único, na tela global da plataforma."""
    get_object_or_404(Tenant, slug=municipio_slug)
    destino = request.GET.get("next", "")
    if not destino.startswith("/") or destino.startswith("//"):
        destino = reverse("gestor:painel", args=[municipio_slug])
    return redirect(f"{reverse('login_global')}?next={destino}")


def logout_view(request, municipio_slug):
    auth_logout(request)
    return redirect("login_global")


@requer_gestor
def painel(request, municipio_slug):
    """Visão geral: pendências de conformidade PNCP e atalhos."""
    empenhos = Empenho.objects.do_tenant(municipio_slug)
    pendentes = empenhos.pendentes_de_vinculo()
    estourados = empenhos.com_prazo_estourado().select_related("emenda")
    return render(request, "gestor/painel.html", {
        "total_emendas": Emenda.objects.do_tenant(municipio_slug).count(),
        "total_empenhos": empenhos.count(),
        "total_pendentes": pendentes.count(),
        "estourados": estourados[:20],
        "total_estourados": estourados.count(),
    })


@requer_gestor
def configuracoes(request, municipio_slug):
    """White-label do tenant: brasão, cores e textos."""
    form = ConfiguracaoTenantForm(
        request.POST or None, request.FILES or None, instance=request.tenant
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Configurações do portal salvas com sucesso.")
        return redirect("gestor:configuracoes", municipio_slug=municipio_slug)
    return render(request, "gestor/configuracoes.html", {"form": form})


@requer_gestor
def emendas_lista(request, municipio_slug):
    """Emendas e empenhos importados das APIs federais, com status visual."""
    emendas = (
        Emenda.objects.do_tenant(municipio_slug)
        .prefetch_related("empenhos")
        .order_by("-ano", "numero")
    )
    return render(request, "gestor/emendas.html", {"emendas": emendas})


@requer_gestor
def sincronizacao(request, municipio_slug):
    """
    Histórico e disparo da sincronização com as APIs federais.

    Os dados importados ficam gravados no banco local — o portal público
    nunca depende da API em tempo real. Aqui o gestor acompanha o que já
    foi carregado e dispara a atualização incremental quando quiser.
    """
    if request.method == "POST":
        apenas_ano = request.POST.get("ano", "").strip()
        try:
            execucoes = sincronizar_tenant(
                request.tenant,
                apenas_ano=int(apenas_ano) if apenas_ano.isdigit() else None,
            )
        except ValueError as exc:  # ex.: código IBGE não configurado
            messages.error(request, str(exc))
        else:
            if not execucoes:
                messages.success(request, "Nada pendente — os dados locais já estão completos.")
            else:
                sucesso = sum(1 for e in execucoes if e.status == "sucesso")
                criadas = sum(e.emendas_criadas for e in execucoes)
                atualizadas = sum(e.emendas_atualizadas for e in execucoes)
                messages.success(
                    request,
                    f"Sincronização concluída: {sucesso} exercício(s) processado(s), "
                    f"{criadas} emendas novas, {atualizadas} atualizadas.",
                )
                erros = [e for e in execucoes if e.status == "erro"]
                for e in erros:
                    messages.error(
                        request, f"Exercício {e.ano}: {e.mensagem_erro or 'falha na API'}"
                    )
        return redirect("gestor:sincronizacao", municipio_slug=municipio_slug)

    from django.utils import timezone

    ano_atual = timezone.localdate().year
    return render(request, "gestor/sincronizacao.html", {
        "historico": request.tenant.sincronizacoes.select_related("tenant")[:50],
        "pendentes": anos_pendentes(request.tenant),
        "total_emendas": Emenda.objects.do_tenant(municipio_slug).count(),
        "anos_disponiveis": range(
            ano_atual, request.tenant.ano_inicio_sincronizacao - 1, -1
        ),
    })


@requer_gestor
def vincular_empenho(request, municipio_slug, empenho_id):
    """Formulário de rastreabilidade: processo, contrato e link PNCP."""
    empenho = get_object_or_404(
        Empenho.objects.do_tenant(municipio_slug).select_related("emenda"),
        pk=empenho_id,
    )
    contrato = empenho.contratos_pncp.first()
    form = VinculoContratualForm(
        request.POST or None,
        request.FILES or None,
        instance=contrato,
        initial={"processo_administrativo": empenho.processo_administrativo},
    )
    if request.method == "POST" and form.is_valid():
        contrato = form.save(commit=False)
        contrato.empenho = empenho
        contrato.save()
        empenho.processo_administrativo = form.cleaned_data["processo_administrativo"]
        empenho.status_rastreabilidade = StatusRastreabilidade.VINCULADO
        empenho.save(update_fields=[
            "processo_administrativo", "status_rastreabilidade", "atualizado_em",
        ])
        messages.success(
            request,
            f"Empenho {empenho.numero} vinculado ao contrato "
            f"{contrato.numero_contrato} — agora Em Conformidade.",
        )
        return redirect("gestor:emendas", municipio_slug=municipio_slug)
    return render(request, "gestor/vincular.html", {
        "form": form,
        "empenho": empenho,
    })
