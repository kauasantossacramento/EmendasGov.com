"""
Rotas do EmendasGov.com.

Arquitetura multi-tenant por URL path:
  /                       → landing page da plataforma
  /superadmin/            → Django admin (operação da plataforma)
  /admin/<slug>/          → módulo do gestor municipal
  /<slug>/                → portal público do município (dashboard)
  /<slug>/emendas/...     → pesquisa e drill-downs (emenda → empenho)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from gestor import views as gestor_views
from portal import views as portal_views

urlpatterns = [
    path("", portal_views.landing, name="landing"),
    path("login/", portal_views.login_global, name="login_global"),
    path("dev/", gestor_views.painel_desenvolvedor, name="painel_dev"),
    path("superadmin/", admin.site.urls),
    path("admin/", include("gestor.urls")),
    path("", include("portal.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
