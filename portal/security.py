"""Gateway de segurança: Google reCAPTCHA antes da liberação dos dados."""
import time
from functools import wraps

import requests
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = "recaptcha_ok_em"
VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def captcha_liberado(request) -> bool:
    """Sessão já validada no reCAPTCHA (dentro do TTL)?"""
    tenant = getattr(request, "tenant", None)
    if tenant is not None and not tenant.exigir_recaptcha:
        return True
    if not settings.RECAPTCHA_SECRET_KEY:
        # Sem chave configurada não há como validar — não bloqueia o portal.
        return True
    validado_em = request.session.get(SESSION_KEY)
    return bool(
        validado_em
        and time.time() - validado_em < settings.RECAPTCHA_SESSION_TTL
    )


def validar_token(request, token: str) -> bool:
    try:
        resp = requests.post(
            VERIFY_URL,
            data={
                "secret": settings.RECAPTCHA_SECRET_KEY,
                "response": token,
                "remoteip": request.META.get("REMOTE_ADDR", ""),
            },
            timeout=10,
        )
        resp.raise_for_status()
        ok = bool(resp.json().get("success"))
    except requests.RequestException:
        ok = False
    if ok:
        request.session[SESSION_KEY] = time.time()
    return ok


def requer_captcha(view_func):
    """Redireciona para o gateway caso a sessão ainda não tenha sido validada."""

    @wraps(view_func)
    def wrapper(request, municipio_slug, *args, **kwargs):
        if not captcha_liberado(request):
            gateway = reverse("portal:gateway", args=[municipio_slug])
            return redirect(f"{gateway}?next={request.get_full_path()}")
        return view_func(request, municipio_slug, *args, **kwargs)

    return wrapper
