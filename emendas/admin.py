from django.contrib import admin

from .models import ContratoPNCP, Emenda, Empenho


class EmpenhoInline(admin.TabularInline):
    model = Empenho
    extra = 0
    fields = (
        "numero", "data_empenho", "fornecedor_nome",
        "valor_empenhado", "valor_liquidado", "valor_pago",
        "status_rastreabilidade",
    )
    show_change_link = True


@admin.register(Emenda)
class EmendaAdmin(admin.ModelAdmin):
    list_display = ("numero", "ano", "parlamentar", "tenant", "valor_total", "area_aplicacao")
    list_filter = ("tenant", "ano", "area_aplicacao")
    search_fields = ("numero", "parlamentar", "objeto")
    inlines = [EmpenhoInline]


class ContratoPNCPInline(admin.StackedInline):
    model = ContratoPNCP
    extra = 0


@admin.register(Empenho)
class EmpenhoAdmin(admin.ModelAdmin):
    list_display = (
        "numero", "emenda", "data_empenho", "fornecedor_nome",
        "valor_empenhado", "status_rastreabilidade",
    )
    list_filter = ("status_rastreabilidade", "emenda__tenant", "emenda__ano")
    search_fields = ("numero", "fornecedor_nome", "fornecedor_cnpj", "objeto")
    inlines = [ContratoPNCPInline]


@admin.register(ContratoPNCP)
class ContratoPNCPAdmin(admin.ModelAdmin):
    list_display = ("numero_contrato", "empenho", "modalidade", "id_pncp", "data_assinatura")
    list_filter = ("modalidade",)
    search_fields = ("numero_contrato", "id_pncp")
