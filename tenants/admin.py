from django.contrib import admin

from .models import GestorMunicipal, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("nome", "uf", "slug", "ativo", "atualizado_em")
    list_filter = ("ativo", "uf")
    search_fields = ("nome", "slug", "codigo_ibge", "cnpj")
    prepopulated_fields = {"slug": ("nome",)}
    fieldsets = (
        ("Identificação", {
            "fields": ("nome", "slug", "uf", "codigo_ibge", "cnpj", "ativo"),
        }),
        ("White-label (identidade visual)", {
            "fields": ("brasao", "cor_primaria", "cor_secundaria", "cor_destaque"),
        }),
        ("Conteúdo", {
            "fields": ("texto_introdutorio", "avisos"),
        }),
        ("Segurança", {
            "fields": ("exigir_recaptcha",),
        }),
    )


@admin.register(GestorMunicipal)
class GestorMunicipalAdmin(admin.ModelAdmin):
    list_display = ("usuario", "tenant", "cargo", "criado_em")
    list_filter = ("tenant",)
    search_fields = ("usuario__username", "usuario__email", "tenant__nome")
