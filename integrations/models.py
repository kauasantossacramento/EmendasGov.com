from django.db import models

from tenants.models import Tenant


class StatusSincronizacao(models.TextChoices):
    EXECUTANDO = "executando", "Executando"
    SUCESSO = "sucesso", "Sucesso"
    ERRO = "erro", "Erro"


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
