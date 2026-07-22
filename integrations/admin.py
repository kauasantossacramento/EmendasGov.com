from django.contrib import admin

from .models import CargaNacional, EmendaNacional, SincronizacaoEmendas


@admin.register(CargaNacional)
class CargaNacionalAdmin(admin.ModelAdmin):
    list_display = (
        "ano", "status", "registros_novos", "registros_atualizados",
        "iniciado_em", "concluido_em",
    )
    list_filter = ("status", "ano")

    def has_add_permission(self, request):
        return False


@admin.register(EmendaNacional)
class EmendaNacionalAdmin(admin.ModelAdmin):
    list_display = ("numero", "ano", "autor", "localidade", "valor_total")
    list_filter = ("ano",)
    search_fields = ("numero", "autor", "localidade")

    def has_add_permission(self, request):
        return False


@admin.register(SincronizacaoEmendas)
class SincronizacaoEmendasAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "ano", "status", "emendas_criadas",
        "emendas_atualizadas", "iniciado_em", "concluido_em",
    )
    list_filter = ("status", "tenant", "ano")
    readonly_fields = (
        "tenant", "ano", "status", "emendas_criadas", "emendas_atualizadas",
        "mensagem_erro", "iniciado_em", "concluido_em",
    )

    def has_add_permission(self, request):
        return False
