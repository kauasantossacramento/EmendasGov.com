from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from tenants.models import Tenant

ZERO = Decimal("0.00")


class AreaAplicacao(models.TextChoices):
    SAUDE = "saude", "Saúde"
    EDUCACAO = "educacao", "Educação"
    INFRAESTRUTURA = "infraestrutura", "Infraestrutura"
    ASSISTENCIA_SOCIAL = "assistencia_social", "Assistência Social"
    CUSTEIO = "custeio", "Custeio"
    OUTROS = "outros", "Outros"


class EmendaQuerySet(models.QuerySet):
    def do_tenant(self, municipio_slug):
        """Isolamento de rota: toda listagem pública DEVE passar por aqui."""
        return self.filter(tenant__slug=municipio_slug)


class Emenda(models.Model):
    """
    Emenda parlamentar destinada ao município (origem do recurso —
    Transferegov / Portal da Transparência CGU).
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="emendas",
        verbose_name="Município",
    )
    numero = models.CharField("Nº da emenda", max_length=40)
    parlamentar = models.CharField("Parlamentar (autor)", max_length=150)
    ano = models.PositiveIntegerField("Exercício (ano)")
    valor_total = models.DecimalField(
        "Valor do orçamento (R$)", max_digits=16, decimal_places=2, default=ZERO
    )
    area_aplicacao = models.CharField(
        "Área de aplicação", max_length=30,
        choices=AreaAplicacao.choices, default=AreaAplicacao.OUTROS,
    )
    objeto = models.TextField("Objeto / finalidade", blank=True)
    data_recebimento = models.DateField(
        "Data de recebimento do recurso", null=True, blank=True
    )

    # Rastreabilidade da origem federal
    codigo_transferegov = models.CharField(
        "Código no Transferegov", max_length=60, blank=True
    )
    fonte_importacao = models.CharField(
        "Fonte da importação", max_length=30, blank=True,
        help_text="transferegov, cgu ou manual",
    )
    importado_em = models.DateTimeField("Importado em", null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = EmendaQuerySet.as_manager()

    class Meta:
        verbose_name = "Emenda"
        verbose_name_plural = "Emendas"
        ordering = ["-ano", "numero"]
        unique_together = [("tenant", "numero", "ano")]
        indexes = [
            models.Index(fields=["tenant", "ano"]),
            models.Index(fields=["tenant", "parlamentar"]),
        ]

    def __str__(self):
        return f"Emenda {self.numero}/{self.ano} — {self.parlamentar}"

    # Totalizações financeiras (cards do Nível 2) ---------------------------
    def _soma(self, campo):
        return self.empenhos.aggregate(t=models.Sum(campo))["t"] or ZERO

    @property
    def total_empenhado(self):
        return self._soma("valor_empenhado")

    @property
    def total_liquidado(self):
        return self._soma("valor_liquidado")

    @property
    def total_pago(self):
        return self._soma("valor_pago")


class StatusRastreabilidade(models.TextChoices):
    PENDENTE = "pendente", "Pendente de Vínculo Contratual"
    VINCULADO = "vinculado", "Em Conformidade"
    CANCELADO = "cancelado", "Cancelado"


class EmpenhoQuerySet(models.QuerySet):
    def do_tenant(self, municipio_slug):
        return self.filter(emenda__tenant__slug=municipio_slug)

    def pendentes_de_vinculo(self):
        return self.filter(status_rastreabilidade=StatusRastreabilidade.PENDENTE)

    def com_prazo_estourado(self):
        """Empenhos emitidos há mais de N dias sem vínculo PNCP (trava/alerta)."""
        limite = timezone.localdate() - timedelta(
            days=settings.PNCP_PRAZO_VINCULO_DIAS
        )
        return self.pendentes_de_vinculo().filter(data_empenho__lt=limite)


class Empenho(models.Model):
    """Reserva do recurso na contabilidade local, vinculada a uma emenda."""

    emenda = models.ForeignKey(
        Emenda, on_delete=models.CASCADE, related_name="empenhos",
        verbose_name="Emenda",
    )
    numero = models.CharField("Nº do empenho", max_length=40)
    data_empenho = models.DateField("Data do empenho")
    unidade_executora = models.CharField("Unidade executora", max_length=200, blank=True)
    projeto_atividade = models.CharField("Projeto/Atividade", max_length=200, blank=True)
    elemento_despesa = models.CharField("Elemento de despesa", max_length=60, blank=True)
    fonte = models.CharField("Fonte", max_length=60, blank=True)
    subfonte = models.CharField("Subfonte", max_length=60, blank=True)

    fornecedor_cnpj = models.CharField("CNPJ do fornecedor", max_length=18, blank=True)
    fornecedor_nome = models.CharField(
        "Razão social do fornecedor", max_length=200, blank=True
    )
    objeto = models.TextField(
        "Objeto",
        blank=True,
        help_text="Descrição textual completa do que está sendo adquirido/contratado.",
    )

    # Matriz de valores -----------------------------------------------------
    valor_empenhado = models.DecimalField(
        "Valor empenhado (R$)", max_digits=16, decimal_places=2, default=ZERO
    )
    valor_liquidado = models.DecimalField(
        "Valor liquidado (R$)", max_digits=16, decimal_places=2, default=ZERO
    )
    valor_pago = models.DecimalField(
        "Valor pago (R$)", max_digits=16, decimal_places=2, default=ZERO
    )

    # Conformidade PNCP -----------------------------------------------------
    processo_administrativo = models.CharField(
        "Nº/Ano do processo administrativo", max_length=60, blank=True
    )
    status_rastreabilidade = models.CharField(
        "Status de rastreabilidade",
        max_length=20,
        choices=StatusRastreabilidade.choices,
        default=StatusRastreabilidade.PENDENTE,
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = EmpenhoQuerySet.as_manager()

    class Meta:
        verbose_name = "Empenho"
        verbose_name_plural = "Empenhos"
        ordering = ["-data_empenho", "numero"]
        unique_together = [("emenda", "numero")]

    def __str__(self):
        return f"Empenho {self.numero} ({self.emenda})"

    # Valores derivados exibidos no Nível 3 ---------------------------------
    @property
    def valor_a_liquidar(self):
        return self.valor_empenhado - self.valor_liquidado

    @property
    def valor_a_pagar(self):
        return self.valor_liquidado - self.valor_pago

    @property
    def dias_desde_emissao(self):
        return (timezone.localdate() - self.data_empenho).days

    @property
    def prazo_pncp_estourado(self):
        """Trava de conformidade: mais de 30 dias sem vínculo PNCP."""
        return (
            self.status_rastreabilidade == StatusRastreabilidade.PENDENTE
            and self.dias_desde_emissao > settings.PNCP_PRAZO_VINCULO_DIAS
        )


class ModalidadeContratacao(models.TextChoices):
    PREGAO_ELETRONICO = "pregao_eletronico", "Pregão Eletrônico"
    PREGAO_PRESENCIAL = "pregao_presencial", "Pregão Presencial"
    CONCORRENCIA = "concorrencia", "Concorrência"
    DISPENSA = "dispensa", "Dispensa de Licitação"
    INEXIGIBILIDADE = "inexigibilidade", "Inexigibilidade"
    LEILAO = "leilao", "Leilão"
    DIALOGO_COMPETITIVO = "dialogo_competitivo", "Diálogo Competitivo"
    CONCURSO = "concurso", "Concurso"


class ContratoPNCP(models.Model):
    """
    Execução do recurso: contrato registrado no Portal Nacional de
    Contratações Públicas (PNCP), vinculado a um empenho.
    """

    empenho = models.ForeignKey(
        Empenho, on_delete=models.CASCADE, related_name="contratos_pncp",
        verbose_name="Empenho",
    )
    numero_contrato = models.CharField("Nº/Ano do contrato", max_length=60)
    modalidade = models.CharField(
        "Modalidade", max_length=30,
        choices=ModalidadeContratacao.choices, blank=True,
    )
    id_pncp = models.CharField(
        "ID PNCP", max_length=80, blank=True,
        help_text="Código sequencial único da contratação no portal nacional.",
    )
    url_pncp = models.URLField(
        "Link do contrato no PNCP", blank=True,
        help_text="URL direta para a página do contrato em pncp.gov.br.",
    )
    url_edital = models.URLField("Link do edital", blank=True)
    data_assinatura = models.DateField("Data de assinatura", null=True, blank=True)
    documento_anexo = models.FileField(
        "Documento anexo (Termo de Referência / Edital)",
        upload_to="contratos/", blank=True, null=True,
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato PNCP"
        verbose_name_plural = "Contratos PNCP"
        ordering = ["-data_assinatura"]

    def __str__(self):
        return f"Contrato {self.numero_contrato} (PNCP {self.id_pncp or 's/ id'})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Ao registrar o contrato, o empenho passa a "Em Conformidade".
        if self.empenho.status_rastreabilidade == StatusRastreabilidade.PENDENTE:
            self.empenho.status_rastreabilidade = StatusRastreabilidade.VINCULADO
            self.empenho.save(update_fields=["status_rastreabilidade", "atualizado_em"])
