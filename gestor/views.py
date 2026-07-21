from functools import wraps

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from emendas.models import Emenda, Empenho, StatusRastreabilidade
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
                f"{reverse('gestor:login', args=[municipio_slug])}"
                f"?next={request.get_full_path()}"
            )
        request.tenant = tenant
        return view_func(request, municipio_slug, *args, **kwargs)

    return wrapper


def login_view(request, municipio_slug):
    tenant = get_object_or_404(Tenant, slug=municipio_slug)
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.get_user()
        if not _pode_gerir(usuario, tenant):
            form.add_error(None, "Este usuário não é gestor deste município.")
        else:
            auth_login(request, usuario)
            destino = request.GET.get("next", "")
            if not destino.startswith("/"):
                destino = reverse("gestor:painel", args=[municipio_slug])
            return redirect(destino)
    return render(request, "gestor/login.html", {"form": form, "tenant_login": tenant})


def logout_view(request, municipio_slug):
    auth_logout(request)
    return redirect("gestor:login", municipio_slug=municipio_slug)


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
