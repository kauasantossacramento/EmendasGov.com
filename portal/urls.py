from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("<slug:municipio_slug>/", views.dashboard, name="dashboard"),
    path("<slug:municipio_slug>/acesso/", views.gateway, name="gateway"),
    path("<slug:municipio_slug>/emendas/", views.pesquisa, name="pesquisa"),
    path(
        "<slug:municipio_slug>/emendas/exportar/",
        views.exportar_emendas,
        name="exportar_emendas",
    ),
    path(
        "<slug:municipio_slug>/emendas/<int:emenda_id>/",
        views.emenda_detalhe,
        name="emenda_detalhe",
    ),
    path(
        "<slug:municipio_slug>/emendas/<int:emenda_id>/exportar/",
        views.exportar_empenhos,
        name="exportar_empenhos",
    ),
    path(
        "<slug:municipio_slug>/emendas/<int:emenda_id>/empenhos/<int:empenho_id>/",
        views.empenho_detalhe,
        name="empenho_detalhe",
    ),
    path(
        "<slug:municipio_slug>/assistente/",
        views.chat_assistente,
        name="chat_assistente",
    ),
]
