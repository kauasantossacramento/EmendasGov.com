from django import forms

from emendas.models import ContratoPNCP
from tenants.models import Tenant


class ConfiguracaoTenantForm(forms.ModelForm):
    """White-label: brasão, paleta de cores e textos da página inicial."""

    class Meta:
        model = Tenant
        fields = [
            "brasao", "cor_primaria", "cor_secundaria", "cor_destaque",
            "texto_introdutorio", "avisos", "exigir_recaptcha",
        ]
        widgets = {
            "cor_primaria": forms.TextInput(attrs={"type": "color"}),
            "cor_secundaria": forms.TextInput(attrs={"type": "color"}),
            "cor_destaque": forms.TextInput(attrs={"type": "color"}),
            "texto_introdutorio": forms.Textarea(
                attrs={"rows": 8, "class": "richtext"}
            ),
            "avisos": forms.Textarea(attrs={"rows": 4, "class": "richtext"}),
        }


class VinculoContratualForm(forms.ModelForm):
    """
    Formulário de rastreabilidade PNCP: fecha a lacuna entre o empenho
    (contabilidade local) e o contrato (PNCP).
    """

    processo_administrativo = forms.CharField(
        label="Nº/Ano do processo administrativo",
        max_length=60,
        help_text="Ex.: PA-0042/2026",
    )

    class Meta:
        model = ContratoPNCP
        fields = [
            "numero_contrato", "modalidade", "id_pncp", "url_pncp",
            "url_edital", "data_assinatura", "documento_anexo",
        ]
        widgets = {
            "data_assinatura": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_url_pncp(self):
        url = self.cleaned_data.get("url_pncp", "")
        if url and "pncp.gov.br" not in url:
            raise forms.ValidationError(
                "Informe a URL direta da contratação em pncp.gov.br."
            )
        return url
