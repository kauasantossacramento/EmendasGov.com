from django.urls import path

from . import views

app_name = "gestor"

urlpatterns = [
    path("<slug:municipio_slug>/login/", views.login_view, name="login"),
    path("<slug:municipio_slug>/sair/", views.logout_view, name="logout"),
    path("<slug:municipio_slug>/", views.painel, name="painel"),
    path(
        "<slug:municipio_slug>/configuracoes/",
        views.configuracoes,
        name="configuracoes",
    ),
    path("<slug:municipio_slug>/emendas/", views.emendas_lista, name="emendas"),
    path(
        "<slug:municipio_slug>/sincronizacao/",
        views.sincronizacao,
        name="sincronizacao",
    ),
    path(
        "<slug:municipio_slug>/empenhos/<int:empenho_id>/vincular/",
        views.vincular_empenho,
        name="vincular",
    ),
]
