from django.db import models


class ConfiguracaoPlataforma(models.Model):
    """
    Configurações globais da plataforma (singleton), editadas pelo
    administrador do sistema no /superadmin/.
    """

    exibir_estatisticas = models.BooleanField(
        "Exibir faixa de números na página inicial",
        default=True,
        help_text="Desative para ocultar completamente a faixa de estatísticas.",
    )
    usar_dados_reais = models.BooleanField(
        "Usar dados reais do banco",
        default=False,
        help_text=(
            "Ativado: mostra municípios, emendas, volume e contratos reais "
            "da plataforma. Desativado: mostra os destaques personalizados "
            "cadastrados abaixo (recomendado no lançamento, enquanto os "
            "números reais ainda são pequenos)."
        ),
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração da plataforma"
        verbose_name_plural = "Configuração da plataforma"

    def __str__(self):
        return "Configuração da plataforma"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def carregar(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DestaquePlataforma(models.Model):
    """
    Destaque personalizado exibido na faixa de números da página inicial
    quando 'usar dados reais' está desativado. Ex.: valor "24/7",
    rótulo "Assistente de IA ao cidadão".
    """

    configuracao = models.ForeignKey(
        ConfiguracaoPlataforma, on_delete=models.CASCADE, related_name="destaques"
    )
    valor = models.CharField(
        "Valor em destaque", max_length=40,
        help_text='O número/texto grande. Ex.: "100%", "3", "24/7", "30 dias".',
    )
    rotulo = models.CharField(
        "Rótulo", max_length=80,
        help_text='A descrição abaixo do valor. Ex.: "Dados oficiais de Brasília".',
    )
    ordem = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Destaque da página inicial"
        verbose_name_plural = "Destaques da página inicial"
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.valor} — {self.rotulo}"
