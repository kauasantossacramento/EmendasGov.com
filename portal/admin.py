from django.contrib import admin

from .models import ConfiguracaoPlataforma, DestaquePlataforma


class DestaquePlataformaInline(admin.TabularInline):
    model = DestaquePlataforma
    extra = 1


@admin.register(ConfiguracaoPlataforma)
class ConfiguracaoPlataformaAdmin(admin.ModelAdmin):
    list_display = ("__str__", "exibir_estatisticas", "usar_dados_reais", "atualizado_em")
    inlines = [DestaquePlataformaInline]

    def has_add_permission(self, request):
        # Singleton: só permite criar se ainda não existir.
        return not ConfiguracaoPlataforma.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
