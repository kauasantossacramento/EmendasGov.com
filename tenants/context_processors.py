from django.conf import settings


def tenant_context(request):
    """
    Disponibiliza o tenant atual, a data da última atualização dos dados
    (selo PNTP, exibido em todas as páginas do município) e chaves
    públicas em todos os templates.
    """
    tenant = getattr(request, "tenant", None)
    return {
        "tenant": tenant,
        "ultima_atualizacao": tenant.ultima_atualizacao_dados() if tenant else None,
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY,
    }
