from django.db import models


class Tenant(models.Model):
    """
    Município (tenant) do portal. O isolamento de dados é feito por URL path:
    dominio.com.br/<slug>/ — todas as consultas devem filtrar por este tenant.
    """

    slug = models.SlugField(
        "Slug do município",
        unique=True,
        max_length=80,
        help_text="Identificador usado na URL, ex.: 'salvador' → emendas.gov.com/salvador/",
    )
    nome = models.CharField("Nome do município", max_length=150)
    uf = models.CharField("UF", max_length=2, blank=True)
    codigo_ibge = models.CharField("Código IBGE", max_length=7, blank=True)
    cnpj = models.CharField("CNPJ da Prefeitura", max_length=18, blank=True)

    # White-label -----------------------------------------------------------
    brasao = models.ImageField(
        "Brasão / Logo", upload_to="brasoes/", blank=True, null=True
    )
    cor_primaria = models.CharField(
        "Cor primária (hex)", max_length=7, default="#1351B4"
    )
    cor_secundaria = models.CharField(
        "Cor secundária (hex)", max_length=7, default="#00884A"
    )
    cor_destaque = models.CharField(
        "Cor de destaque (hex)", max_length=7, default="#FFCD07"
    )
    texto_introdutorio = models.TextField(
        "Texto introdutório (HTML)",
        blank=True,
        help_text=(
            "Exibido na página inicial do portal do município. Aceita HTML "
            "(rich text) — use para citar leis e resoluções locais, "
            "ex.: 'Conforme Resolução nº XXX/Ano - TCM'."
        ),
    )
    avisos = models.TextField(
        "Avisos (HTML)",
        blank=True,
        help_text="Avisos exibidos em destaque no portal público.",
    )

    # Sincronização ---------------------------------------------------------
    ano_inicio_sincronizacao = models.PositiveIntegerField(
        "Ano inicial da sincronização",
        default=2020,
        help_text=(
            "Primeiro exercício a importar das APIs federais. Na primeira "
            "sincronização o sistema faz a carga histórica deste ano até a "
            "data atual; depois, apenas o que ainda falta é consultado."
        ),
    )

    # Controle --------------------------------------------------------------
    ativo = models.BooleanField("Portal ativo", default=True)
    exigir_recaptcha = models.BooleanField(
        "Exigir reCAPTCHA antes da consulta", default=True
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Município (Tenant)"
        verbose_name_plural = "Municípios (Tenants)"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome}/{self.uf}" if self.uf else self.nome

    def ultima_atualizacao_dados(self):
        """
        Momento da última atualização dos dados exibidos ao cidadão
        (transparência ativa — critério do PNTP).

        Preferência: conclusão da última sincronização bem-sucedida com
        as APIs federais; sem sincronização, cai para a importação ou
        alteração mais recente das emendas no banco local.
        """
        sync = (
            self.sincronizacoes.filter(status="sucesso")
            .exclude(concluido_em=None)
            .order_by("-concluido_em")
            .first()
        )
        if sync:
            return sync.concluido_em
        return (
            self.emendas.exclude(importado_em=None)
            .order_by("-importado_em")
            .values_list("importado_em", flat=True)
            .first()
            or self.emendas.order_by("-atualizado_em")
            .values_list("atualizado_em", flat=True)
            .first()
        )


class GestorMunicipal(models.Model):
    """Vincula um usuário do Django a um tenant, dando acesso ao módulo gestor."""

    usuario = models.ForeignKey(
        "auth.User", on_delete=models.CASCADE, related_name="gestorias"
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="gestores"
    )
    cargo = models.CharField("Cargo", max_length=120, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gestor municipal"
        verbose_name_plural = "Gestores municipais"
        unique_together = [("usuario", "tenant")]

    def __str__(self):
        return f"{self.usuario} @ {self.tenant.slug}"
