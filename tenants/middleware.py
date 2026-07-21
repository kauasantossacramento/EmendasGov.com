from django.http import Http404
from django.urls import resolve

from .models import Tenant


class TenantMiddleware:
    """
    Resolve o tenant a partir do path da URL (dominio.com.br/<municipio_slug>/...).

    O slug capturado pelas rotas (kwarg `municipio_slug`) é validado contra o
    banco e o objeto Tenant é anexado em `request.tenant`. Rotas fora do escopo
    de um município (landing page, /admin/ do Django) seguem com tenant=None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        try:
            match = resolve(request.path_info)
        except Http404:
            match = None
        if match is not None:
            slug = match.kwargs.get("municipio_slug")
            if slug:
                try:
                    request.tenant = Tenant.objects.get(slug=slug, ativo=True)
                except Tenant.DoesNotExist:
                    raise Http404("Município não encontrado ou portal inativo.")
        return self.get_response(request)
