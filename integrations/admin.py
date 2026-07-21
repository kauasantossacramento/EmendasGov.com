from django.contrib import admin

from .models import SincronizacaoEmendas


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
