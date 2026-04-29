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
    # Phase 4A — daphne goes BEFORE django.contrib.staticfiles when
    # used with `runserver` so the ASGI runserver picks up the
    # WebSocket router. Channels itself is third-party.
    "daphne",
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
    "channels",
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
    "apps.catalog",
    "apps.whatsapp",
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
# Phase 4A — channels reads ASGI_APPLICATION to bootstrap the routing.
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

# CSRF trusted origins — required when the browser submits to a different
# scheme/host than ``ALLOWED_HOSTS`` covers (e.g. https://ai.nirogidhara.com
# proxied to the container). The env var takes precedence; defaults match
# the dev CORS origins so local POSTs keep working.
CSRF_TRUSTED_ORIGINS = _csv(os.environ.get("CSRF_TRUSTED_ORIGINS")) or [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


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


# ----- Vapi (Phase 2D) -----
# Same three-mode dispatch: ``mock`` (default, deterministic fake call id, no
# network), ``test`` (Vapi staging — needs a real test API key + sandbox
# assistant id + caller phone-number id), ``live`` (production). Secrets stay
# server-side; the frontend never receives the API key.
#
# COMPLIANCE HARD STOP (Master Blueprint §26 #4):
#   The Vapi assistant prompt MUST pull only from apps.compliance.Claim.
#   Never inject free-style medical text from this codebase. CAIO never
#   executes business actions.
VAPI_MODE = (os.environ.get("VAPI_MODE") or "mock").lower()
VAPI_API_BASE_URL = os.environ.get("VAPI_API_BASE_URL", "")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
VAPI_WEBHOOK_SECRET = os.environ.get("VAPI_WEBHOOK_SECRET", "")
VAPI_DEFAULT_LANGUAGE = os.environ.get("VAPI_DEFAULT_LANGUAGE", "hi-IN")
VAPI_CALLBACK_URL = os.environ.get("VAPI_CALLBACK_URL", "")


# ----- Meta Lead Ads (Phase 2E) -----
# Same three-mode dispatch: ``mock`` (default, no network — parses the
# inbound webhook payload directly), ``test`` (Meta Graph API expansion of
# ids returned in the webhook), ``live`` (production). Webhook verification
# uses META_VERIFY_TOKEN for the GET handshake and signs POST bodies with
# META_WEBHOOK_SECRET (falls back to META_APP_SECRET when not set). Frontend
# never sees any of these — secrets stay server-side.
META_MODE = (os.environ.get("META_MODE") or "mock").lower()
META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")
META_PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "")
META_GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v20.0")
META_WEBHOOK_SECRET = os.environ.get("META_WEBHOOK_SECRET", "")


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


# ----- Phase 3C — Celery scheduler + AI fallback chain + cost tracking -----
# Local dev / CI runs in eager mode by default so neither Redis nor a worker
# needs to be running. Production cron flips ``CELERY_TASK_ALWAYS_EAGER=false``
# and starts ``celery -A config worker -B`` against the real Redis broker.
CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL", "redis://localhost:6379/0"
)
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"
)
CELERY_TASK_ALWAYS_EAGER = _bool(
    os.environ.get("CELERY_TASK_ALWAYS_EAGER"), default=True
)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = os.environ.get("AI_TIMEZONE", "Asia/Kolkata")
CELERY_TASK_TRACK_STARTED = True
CELERY_RESULT_EXTENDED = True

# Daily briefing slots — 09:00 + 18:00 IST by default per locked Phase 3C
# decisions. Hours and minutes are env-driven so ops can shift them.
AI_DAILY_BRIEFING_MORNING_HOUR = _safe_int(
    os.environ.get("AI_DAILY_BRIEFING_MORNING_HOUR"), default=9
)
AI_DAILY_BRIEFING_MORNING_MINUTE = _safe_int(
    os.environ.get("AI_DAILY_BRIEFING_MORNING_MINUTE"), default=0
)
AI_DAILY_BRIEFING_EVENING_HOUR = _safe_int(
    os.environ.get("AI_DAILY_BRIEFING_EVENING_HOUR"), default=18
)
AI_DAILY_BRIEFING_EVENING_MINUTE = _safe_int(
    os.environ.get("AI_DAILY_BRIEFING_EVENING_MINUTE"), default=0
)
AI_TIMEZONE = os.environ.get("AI_TIMEZONE", "Asia/Kolkata")

# Provider fallback chain — `dispatch_messages` walks this list in order.
# Empty / missing → falls back to ``[AI_PROVIDER]`` (single-provider behaviour
# preserved for Phase 3A/3B test fixtures).
AI_PROVIDER_FALLBACKS = _csv(os.environ.get("AI_PROVIDER_FALLBACKS"))

# Per-provider model overrides used by the fallback chain. The first
# OpenAI attempt uses ``OPENAI_FALLBACK_MODEL`` (or ``AI_MODEL``); the
# Anthropic fallback uses ``ANTHROPIC_MODEL``.
OPENAI_FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "")


# ----- Phase 3D — Sandbox toggle default -----
# The DB-backed SandboxState singleton holds the live toggle; this env
# var is the boot-time default the singleton picks up the FIRST time it
# is queried. Flipping the toggle later goes through PATCH
# /api/ai/sandbox/status/ (admin/director only).
AI_SANDBOX_MODE = _bool(os.environ.get("AI_SANDBOX_MODE"), default=False)


# ----- Phase 5A — WhatsApp (Meta Cloud API) -----
# Three-mode dispatch matching every other gateway adapter:
#   mock        — deterministic, no network. Default for tests / dev.
#   meta_cloud  — Meta WhatsApp Business Cloud API (production target).
#                 Calls https://graph.facebook.com/{version}/{phone_number_id}/messages.
#                 HMAC-SHA256 webhook verification via META_WA_APP_SECRET.
#   baileys_dev — explicit dev-only stub. Refuses to load when
#                 DJANGO_DEBUG=False AND WHATSAPP_DEV_PROVIDER_ENABLED!=true.
#                 Never use in production.
#
# COMPLIANCE HARD STOP (Master Blueprint §26):
#   Every WhatsApp send must be consent + approved-template + Claim-Vault
#   gated server-side. Failed sends never mutate Order / Payment / Shipment.
#   CAIO never sends customer messages — refused at engine + bridge +
#   execute layer + an explicit guard at the WhatsApp service entry.
WHATSAPP_PROVIDER = (os.environ.get("WHATSAPP_PROVIDER") or "mock").lower()
META_WA_PHONE_NUMBER_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", "")
META_WA_BUSINESS_ACCOUNT_ID = os.environ.get("META_WA_BUSINESS_ACCOUNT_ID", "")
META_WA_ACCESS_TOKEN = os.environ.get("META_WA_ACCESS_TOKEN", "")
META_WA_VERIFY_TOKEN = os.environ.get("META_WA_VERIFY_TOKEN", "")
META_WA_APP_SECRET = os.environ.get("META_WA_APP_SECRET", "")
META_WA_API_VERSION = os.environ.get("META_WA_API_VERSION", "v20.0")
WHATSAPP_WEBHOOK_SECRET = os.environ.get("WHATSAPP_WEBHOOK_SECRET", "")
WHATSAPP_DEV_PROVIDER_ENABLED = _bool(
    os.environ.get("WHATSAPP_DEV_PROVIDER_ENABLED"), default=False
)
# Webhook replay window (seconds). Meta does not strictly require this for the
# Cloud API but it's defense in depth — when the request arrives with a
# timestamp header older than this window it's rejected.
WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS = _safe_int(
    os.environ.get("WHATSAPP_WEBHOOK_REPLAY_WINDOW_SECONDS"), default=300
)


# ----- Phase 4A — Real-time WebSockets via Django Channels -----
# Local dev / pytest default to the in-memory channel layer so neither
# Redis nor the daphne ASGI runner is required for the test suite. To
# use Redis-backed channels (production target) set:
#   CHANNEL_LAYER_BACKEND=redis
#   CHANNEL_REDIS_URL=redis://localhost:6379/2
# The frontend can override the WebSocket origin via VITE_WS_BASE_URL;
# otherwise it derives the URL from VITE_API_BASE_URL.
CHANNEL_LAYER_BACKEND = (
    os.environ.get("CHANNEL_LAYER_BACKEND") or "memory"
).strip().lower()
CHANNEL_REDIS_URL = os.environ.get(
    "CHANNEL_REDIS_URL", "redis://localhost:6379/2"
)

if CHANNEL_LAYER_BACKEND == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [CHANNEL_REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "apps": {"handlers": ["console"], "level": "INFO"},
    },
}
