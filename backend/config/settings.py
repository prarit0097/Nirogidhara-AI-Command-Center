"""Django settings for the Nirogidhara AI Command Center backend.

Driven entirely by environment variables. Sensible dev defaults (SQLite, debug
on, generous CORS) so the stack runs locally with zero configuration. Override
via ``backend/.env`` for non-dev work; see ``.env.example`` for the full list.
"""
from __future__ import annotations

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = _bool(os.environ.get("DJANGO_DEBUG"), default=True)
ALLOWED_HOSTS = _csv(os.environ.get("DJANGO_ALLOWED_HOSTS")) or [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    # Local apps (order respects FK dependencies)
    "apps.accounts",
    "apps.audit",
    "apps.crm",
    "apps.calls",
    "apps.orders",
    "apps.payments",
    "apps.shipments",
    "apps.agents",
    "apps.ai_governance",
    "apps.compliance",
    "apps.rewards",
    "apps.learning_engine",
    "apps.analytics",
    "apps.dashboards",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
    ),
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    # Reads stay public; writes require auth (Phase 2A onwards).
    # Per-view permission classes can override this where stricter role checks apply.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": None,
}

SIMPLE_JWT = {
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY", SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ACCESS_TOKEN_LIFETIME_HOURS": 12,
    "REFRESH_TOKEN_LIFETIME_DAYS": 7,
}

# CORS — Vite dev server runs on :8080 per vite.config.ts
CORS_ALLOWED_ORIGINS = _csv(os.environ.get("CORS_ALLOWED_ORIGINS")) or [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
CORS_ALLOW_CREDENTIALS = True


def _safe_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


# ----- Razorpay (Phase 2B) -----
# Three modes: ``mock`` (default, deterministic fake link, no network),
# ``test`` (Razorpay sandbox), ``live`` (real production). Frontend never sees
# any of these — secrets stay server-side.
RAZORPAY_MODE = (os.environ.get("RAZORPAY_MODE") or "mock").lower()
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
RAZORPAY_CALLBACK_URL = os.environ.get("RAZORPAY_CALLBACK_URL", "")


# ----- Delhivery (Phase 2C) -----
# Same three-mode dispatch as Razorpay: ``mock`` (default, network-free,
# deterministic AWB), ``test`` (Delhivery staging — needs real test token +
# pickup location), ``live`` (production). Secrets stay server-side; the
# frontend only ever sees the AWB string and the customer-facing tracking URL.
DELHIVERY_MODE = (os.environ.get("DELHIVERY_MODE") or "mock").lower()
DELHIVERY_API_BASE_URL = os.environ.get("DELHIVERY_API_BASE_URL", "")
DELHIVERY_API_TOKEN = os.environ.get("DELHIVERY_API_TOKEN", "")
DELHIVERY_PICKUP_LOCATION = os.environ.get("DELHIVERY_PICKUP_LOCATION", "")
DELHIVERY_RETURN_ADDRESS = os.environ.get("DELHIVERY_RETURN_ADDRESS", "")
DELHIVERY_DEFAULT_PACKAGE_WEIGHT_GRAMS = _safe_int(
    os.environ.get("DELHIVERY_DEFAULT_PACKAGE_WEIGHT_GRAMS"), default=500
)
DELHIVERY_WEBHOOK_SECRET = os.environ.get("DELHIVERY_WEBHOOK_SECRET", "")


# ----- AI provider (Phase 3+ scaffolding) -----
# Today no LLM call is dispatched. ``apps/_ai_config.py`` reads these and
# Phase 3 adapters in ``apps/integrations/ai/`` will consume them.
# COMPLIANCE HARD STOP: AI must speak only from ``apps.compliance.Claim``.
AI_PROVIDER = (os.environ.get("AI_PROVIDER") or "disabled").lower()
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_TEMPERATURE = _safe_float(os.environ.get("AI_TEMPERATURE"), default=0.2)
AI_MAX_TOKENS = _safe_int(os.environ.get("AI_MAX_TOKENS"), default=2000)
AI_REQUEST_TIMEOUT_SECONDS = _safe_int(
    os.environ.get("AI_REQUEST_TIMEOUT_SECONDS"), default=30
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "apps": {"handlers": ["console"], "level": "INFO"},
    },
}
