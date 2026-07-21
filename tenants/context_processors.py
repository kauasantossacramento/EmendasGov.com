from django.conf import settings


def tenant_context(request):
    """Disponibiliza o tenant atual e chaves públicas em todos os templates."""
    return {
        "tenant": getattr(request, "tenant", None),
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY,
    }
