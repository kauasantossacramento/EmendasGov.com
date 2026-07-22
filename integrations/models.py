from django.db import models

from tenants.models import Tenant


class StatusSincronizacao(models.TextChoices):
    EXECUTANDO = "executando", "Executando"
    SUCESSO = "sucesso", "Sucesso"
    ERRO = "erro", "Erro"


class CargaNacional(models.Model):
    """
    Registro de cada carga da base nacional (Brasil inteiro, por exercício)
    a partir da API da CGU. É a fonte que abastece todos os municípios.
    """

    ano = models.PositiveIntegerField("Exercício")
    status = models.CharField(
        "Status", max_length=15,
        choices=StatusSincronizacao.choices,
        default=StatusSincronizacao.EXECUTANDO,
    )
    registros_novos = models.PositiveIntegerField("Registros novos", default=0)
    registros_atualizados = models.PositiveIntegerField(
        "Registros atualizados", default=0
    )
    mensagem_erro = models.TextField("Mensagem de erro", blank=True)
    iniciado_em = models.DateTimeField("Iniciado em", auto_now_add=True)
    concluido_em = models.DateTimeField("Concluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Carga nacional de emendas"
        verbose_name_plural = "Cargas nacionais de emendas"
        ordering = ["-iniciado_em"]
        indexes = [models.Index(fields=["ano", "status"])]

    def __str__(self):
        return f"Carga nacional {self.ano} · {self.get_status_display()}"


class EmendaNacional(models.Model):
    """
    Base nacional: todas as emendas devolvidas pela CGU, de qualquer
    município. Ao criar um município no painel, seus dados são
    materializados daqui — sem novas consultas à API.
    """

    numero = models.CharField("Nº da emenda", max_length=40)
    ano = models.PositiveIntegerField("Exercício")
    autor = models.CharField("Parlamentar (autor)", max_length=150, blank=True)
    funcao = models.CharField("Função orçamentária", max_length=120, blank=True)
    localidade = models.CharField("Localidade do gasto", max_length=255, blank=True)
    localidade_normalizada = models.CharField(
        "Localidade normalizada", max_length=255, blank=True, db_index=True,
        help_text="Sem acentos, em maiúsculas — usada no vínculo com municípios.",
    )
    valor_total = models.DecimalField(
        "Valor empenhado (R$)", max_digits=16, decimal_places=2, default=0
    )
    dados = models.JSONField("Registro completo da API", default=dict, blank=True)
    importado_em = models.DateTimeField("Importado em", auto_now=True)

    class Meta:
        verbose_name = "Emenda (base nacional)"
        verbose_name_plural = "Emendas (base nacional)"
        unique_together = [("numero", "ano")]
        indexes = [models.Index(fields=["ano", "localidade_normalizada"])]

    def __str__(self):
        return f"{self.numero}/{self.ano} — {self.localidade or 'sem localidade'}"


class SincronizacaoEmendas(models.Model):
    """
    Registro de cada execução de sincronização com as APIs federais,
    por município e exercício.

    É a memória do sistema: exercícios históricos já sincronizados com
    sucesso não são consultados de novo na API — o portal serve tudo a
    partir do banco local, ficando disponível mesmo com a API fora do ar.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="sincronizacoes",
        verbose_name="Município",
    )
    ano = models.PositiveIntegerField("Exercício")
    status = models.CharField(
        "Status", max_length=15,
        choices=StatusSincronizacao.choices,
        default=StatusSincronizacao.EXECUTANDO,
    )
    emendas_criadas = models.PositiveIntegerField("Emendas criadas", default=0)
    emendas_atualizadas = models.PositiveIntegerField("Emendas atualizadas", default=0)
    mensagem_erro = models.TextField("Mensagem de erro", blank=True)
    iniciado_em = models.DateTimeField("Iniciado em", auto_now_add=True)
    concluido_em = models.DateTimeField("Concluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Sincronização de emendas"
        verbose_name_plural = "Sincronizações de emendas"
        ordering = ["-iniciado_em"]
        indexes = [models.Index(fields=["tenant", "ano", "status"])]

    def __str__(self):
        return f"{self.tenant.slug} · {self.ano} · {self.get_status_display()}"
