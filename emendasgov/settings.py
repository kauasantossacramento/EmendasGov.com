"""
Configurações do projeto EmendasGov.com
Portal Multi-Tenant de Transparência de Emendas Parlamentares.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _carregar_dotenv(caminho):
    """
    Carrega variáveis de um arquivo .env na raiz do projeto (se existir).

    Aceita linhas no formato CHAVE=valor, com ou sem prefixo "export" e
    com ou sem aspas no valor. Variáveis já definidas no ambiente têm
    prioridade e não são sobrescritas. O .env está no .gitignore — nunca
    commite chaves.
    """
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("export "):
            linha = linha[len("export "):]
        chave, separador, valor = linha.partition("=")
        if not separador:
            continue
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-troque-esta-chave-em-producao",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Confiança de CSRF para ambientes de teste hospedados (GitHub Codespaces)
# e domínios próprios em produção (informe via variável de ambiente).
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "https://*.app.github.dev"
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Apps do projeto
    "tenants",
    "emendas",
    "portal",
    "gestor",
    "integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "emendasgov.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tenants.context_processors.tenant_context",
            ],
        },
    },
]

WSGI_APPLICATION = "emendasgov.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Em produção, configure PostgreSQL via variáveis de ambiente:
if os.environ.get("POSTGRES_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
# Valores monetários usam o filtro |moeda (portal/templatetags/formatos.py);
# não ativar USE_THOUSAND_SEPARATOR global, pois agruparia também os anos.

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/admin/login/"

# ---------------------------------------------------------------------------
# Integrações externas
# ---------------------------------------------------------------------------

# Google reCAPTCHA (gateway de segurança da área pública)
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "")
# Sessão liberada após validação do captcha (em segundos)
RECAPTCHA_SESSION_TTL = 60 * 60 * 4

# Google Gemini (Assistente de Transparência IA)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# APIs federais
TRANSFEREGOV_API_BASE = os.environ.get(
    "TRANSFEREGOV_API_BASE", "https://api.transferegov.gestao.gov.br"
)
PORTAL_TRANSPARENCIA_API_BASE = os.environ.get(
    "PORTAL_TRANSPARENCIA_API_BASE", "https://api.portaldatransparencia.gov.br"
)
PORTAL_TRANSPARENCIA_API_KEY = os.environ.get("PORTAL_TRANSPARENCIA_API_KEY", "")
PNCP_API_BASE = os.environ.get("PNCP_API_BASE", "https://pncp.gov.br/api/consulta")

# Prazo (dias) para alerta de empenho sem vínculo PNCP
PNCP_PRAZO_VINCULO_DIAS = 30
