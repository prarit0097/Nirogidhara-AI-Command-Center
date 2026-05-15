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
    "apps.saas",
    "apps.mcp_gateway",
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


# ----- Phase 6M — Razorpay Webhook Handler (test-mode) -----
# Safe defaults: handler off, no business mutation, no customer
# notification, raw payload not stored. Missing webhook secret never
# crashes startup — readiness simply reports the gap.
def _razorpay_webhook_bool(env_key: str, default: str = "false") -> bool:
    return (os.environ.get(env_key) or default).strip().lower() == "true"


RAZORPAY_WEBHOOK_TEST_MODE_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_WEBHOOK_TEST_MODE_ENABLED"
)
RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED"
)
RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED"
)
RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD = _razorpay_webhook_bool(
    "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD"
)
# ----- Phase 6O — Sandbox Payment Status Mapping + Manual Review -----
# Default off. When true (and only when true), the Phase 6O service can
# prepare a ``RazorpaySandboxStatusReview`` from a Phase 6M-verified
# ``RazorpayWebhookEvent``. The flag NEVER unlocks any mutation of
# real ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog``;
# the gating purely controls whether new sandbox review rows can be
# created. Production ``.env.production`` is not edited — this default
# IS the production posture.
RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED"
)
# ----- Phase 6P — Controlled Internal Paid-Status Mutation Test -----
# Default off. When true (and only when true) the Phase 6P CLI may
# execute a sandbox-only mutation attempt against
# ``RazorpaySandboxPaidStatusLedger`` rows derived from an approved
# Phase 6O review. The flag NEVER unlocks any mutation of real
# ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog`` /
# ``Customer`` / ``Lead`` rows; even when enabled, the service refuses
# without explicit CLI confirmation + a non-empty Director sign-off
# text. There is intentionally NO API endpoint that executes Phase 6P
# mutation — execution is exclusively CLI. Production
# ``.env.production`` is not edited — this default IS the production
# posture.
RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_SANDBOX_PAID_STATUS_MUTATION_ENABLED"
)
# ----- Phase 6Q — Payment → Order Workflow Safety Gate -----
# Default off. When true, the Phase 6Q service may prepare and
# transition `RazorpayPaymentOrderWorkflowGate` review records derived
# from approved Phase 6P sandbox attempts. The flag NEVER unlocks any
# mutation of real `Order` / `Payment` / `Shipment` / `DiscountOfferLog`
# / `Customer` / `Lead` rows; even when enabled, the service writes only
# to its own gate model. Production `.env.production` is not edited —
# this default IS the production posture.
RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_PAYMENT_ORDER_WORKFLOW_GATE_ENABLED"
)
# ----- Phase 6R — Payment → WhatsApp/Courier Readiness (no live send) -----
# Default off. When true, the Phase 6R service may prepare and
# transition `RazorpayPaymentDispatchReadinessGate` review records
# derived from approved Phase 6Q gates. The flag NEVER unlocks any
# WhatsApp send, Meta Cloud call, Delhivery call, shipment creation,
# customer notification, or business-row mutation; even when enabled,
# the service writes only to its own readiness gate model. Production
# `.env.production` is not edited — this default IS the production
# posture.
RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_PAYMENT_DISPATCH_READINESS_ENABLED"
)
# ----- Phase 6S — Limited Internal Dispatch Pilot Plan (planning-only) -----
# Default off. When true, the Phase 6S service may prepare and
# transition `RazorpayPaymentDispatchPilotPlan` review records derived
# from approved Phase 6R readiness gates. The flag NEVER unlocks any
# pilot execution, WhatsApp send, Meta Cloud call, Delhivery call,
# shipment / AWB creation, customer notification, or business-row
# mutation; even when enabled, the service writes only to its own
# pilot plan model. Production `.env.production` is not edited — this
# default IS the production posture.
RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_PAYMENT_DISPATCH_PILOT_PLAN_ENABLED"
)
# ----- Phase 6T - Final Phase 6 Audit + Lock / Decision Gate -----
# Default off. When true, the Phase 6T service may prepare and lock
# `RazorpayPhase6FinalAuditLock` rows derived from approved Phase 6S
# pilot plans. The flag NEVER unlocks pilot execution, WhatsApp send,
# Meta Cloud / Delhivery / Razorpay provider calls, shipment / AWB
# creation, customer notification, or real business-row mutation.
# Production `.env.production` is not edited - this default IS the
# production posture.
RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED = _razorpay_webhook_bool(
    "RAZORPAY_PHASE6_FINAL_AUDIT_LOCK_ENABLED"
)
# ----- Phase 7B - Controlled Pilot Execution Gate (gate-only) -----
# Default off. When true, the Phase 7B service may prepare and
# transition `RazorpayControlledPilotExecutionGate` review records,
# `RazorpayControlledPilotGateDryRunRecord` rows, and
# `RazorpayControlledPilotGateRollbackDryRunRecord` rows derived from
# locked Phase 6T final audit lock chains. The flag NEVER unlocks any
# pilot execution, provider call, WhatsApp send / queue, Meta Cloud
# call, Delhivery call, shipment / AWB creation, customer
# notification, or business-row mutation; even when enabled, the
# service writes only to its own three Phase 7B tables. Production
# `.env.production` is not edited - this default IS the production
# posture.
PHASE7_CONTROLLED_PILOT_GATE_ENABLED = _razorpay_webhook_bool(
    "PHASE7_CONTROLLED_PILOT_GATE_ENABLED"
)
# ----- Phase 7D - Razorpay-only One-Shot Internal TEST Execution -----
# All three default OFF. Production `.env.production` is NEVER edited by
# code; the operator runbook is the only path that can flip these to
# True for an explicit one-shot execution window.
#
# `PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED` controls the Phase 7D
# review lifecycle (prepare/approve/preview/rollback/archive). Even
# when True, no provider call is issued; the dedicated
# `execute_razorpay_controlled_pilot_test_order` CLI is the only path
# that may issue one Razorpay TEST `Orders.create()` request, and only
# after every gate (per-attempt env flag, Director sign-off referencing
# the exact gate id, key starts with `rzp_test_`, kill switch enabled,
# amount=100 paise, source-chain green) is satisfied at runtime.
#
# `PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION` and
# `PHASE7D_ALLOW_RAZORPAY_TEST_ORDER` must remain False outside the
# one-shot operator-controlled execution window. The Phase 7D service
# NEVER edits any `.env*` file, NEVER imports `dotenv`, and NEVER
# silently rewrites env state; it records env-flag presence snapshots
# on every attempt row at start and at end and refuses execution if
# the snapshot is wrong.
PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED = _razorpay_webhook_bool(
    "PHASE7D_RAZORPAY_TEST_EXECUTION_ENABLED"
)
PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION = _razorpay_webhook_bool(
    "PHASE7D_DIRECTOR_APPROVED_ONE_SHOT_EXECUTION"
)
PHASE7D_ALLOW_RAZORPAY_TEST_ORDER = _razorpay_webhook_bool(
    "PHASE7D_ALLOW_RAZORPAY_TEST_ORDER"
)
# ----- Phase 7E - Controlled Internal WhatsApp Notification Readiness -----
# Default OFF. The Phase 7E gate is review-only and CLI-only; even
# when this flag is True the service NEVER sends WhatsApp, NEVER
# queues an outbound, NEVER calls Meta Cloud / Delhivery / Vapi,
# NEVER creates a shipment / AWB / payment link, NEVER captures or
# refunds, NEVER sends a customer notification, and NEVER mutates
# real Order / Payment / Shipment / Customer / Lead rows. Approval
# of a Phase 7E gate flips status to
# `approved_for_future_phase7f_or_7e_send_review` only - it does
# NOT enable any send path. Live customer notification still
# requires a separate, dated, written Director directive AND
# Phase 7D-Hotfix-1 must already have shipped before any future
# provider-touching command (re-run of execute_*, future Phase 7F,
# future Phase 7E-Live).
PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED = _razorpay_webhook_bool(
    "PHASE7E_WHATSAPP_INTERNAL_NOTIFICATION_GATE_ENABLED"
)
# ----- Phase 7F - Delhivery / Courier Controlled Readiness Gate -----
# Default OFF. The Phase 7F gate is review-only and CLI-only; even
# when this flag is True the service NEVER calls Delhivery, NEVER
# creates a Shipment / WorkflowStep / RescueAttempt row, NEVER
# creates an AWB, NEVER books a pickup, NEVER generates a courier
# label, NEVER sends WhatsApp, NEVER calls Meta Cloud / Razorpay /
# Vapi, NEVER mutates real Order / Payment / Customer / Lead rows,
# NEVER edits any .env file. Approval flips status to
# `approved_for_future_phase7g_or_courier_execution_review` only.
# Live courier dispatch requires Phase 7G + a future execute-window
# guard reusing apps.saas.utc_window.validate_within_director_window.
PHASE7F_COURIER_READINESS_GATE_ENABLED = _razorpay_webhook_bool(
    "PHASE7F_COURIER_READINESS_GATE_ENABLED"
)
# ----- Phase 7G - One-shot Delhivery TEST/MOCK Courier Execution Gate -----
# All three default OFF. Production .env.production is NEVER edited
# by code. Phase 7G is the one-shot Delhivery TEST/MOCK courier
# execution capability — Phase 7G-Live (real customer courier
# execution) remains NOT approved.
#
# `PHASE7G_COURIER_EXECUTION_ENABLED` controls the Phase 7G review
# lifecycle (prepare/approve/preview/inspect). Even when True, no
# provider call is issued; the dedicated
# `execute_delhivery_courier_one_shot` CLI is the only path that
# may issue one Delhivery `create_awb` request, and only after
# every gate (per-attempt env flag, Director sign-off referencing
# the source Phase 7F gate id, structured UTC window, mode
# acknowledgement, kill switch enabled, source-chain green) is
# satisfied at runtime.
#
# `PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION` and
# `PHASE7G_ALLOW_DELHIVERY_TEST_AWB` must remain False outside the
# explicit one-shot operator-controlled execution window. Phase 7G
# never edits any `.env*` file, never imports `dotenv`, never
# silently rewrites env state; it records env-flag presence
# snapshots on every attempt row at start and at end and refuses
# execution if the snapshot is wrong.
PHASE7G_COURIER_EXECUTION_ENABLED = _razorpay_webhook_bool(
    "PHASE7G_COURIER_EXECUTION_ENABLED"
)
PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION = _razorpay_webhook_bool(
    "PHASE7G_DIRECTOR_APPROVED_ONE_SHOT_COURIER_EXECUTION"
)
PHASE7G_ALLOW_DELHIVERY_TEST_AWB = _razorpay_webhook_bool(
    "PHASE7G_ALLOW_DELHIVERY_TEST_AWB"
)
# `PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED` controls the
# Phase 7E-Live-A internal allowed-list WhatsApp one-shot send
# lifecycle (prepare/approve/execute/rollback). Locked OFF by
# default. The actual send is CLI-only and additionally requires
# a fresh Director sign-off with structured BEGIN_UTC/END_UTC
# markers (reusing `apps.saas.utc_window`) AND
# `WHATSAPP_LIVE_META_LIMITED_TEST_MODE=true` AND a recipient on
# the existing `WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`
# allow-list. Phase 7E-Live-A NEVER sends to a real customer
# phone, NEVER mutates business rows, and NEVER edits any
# .env file.
PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED = _razorpay_webhook_bool(
    "PHASE7E_LIVE_INTERNAL_WHATSAPP_SEND_ENABLED"
)
# `PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED` controls the
# Phase 7E-Live-B one-shot real-customer WhatsApp send gate. Defaults
# LOCKED OFF. Operators must pass it via runtime env prefix only; the
# execute path is CLI-only and additionally requires a structured
# Director BEGIN_UTC/END_UTC window plus explicit confirmation.
PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED = _razorpay_webhook_bool(
    "PHASE7E_LIVE_B_REAL_CUSTOMER_SEND_ENABLED"
)
# `PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED` controls the
# Phase 7G-Live one-shot real-customer Delhivery dispatch gate.
# Defaults LOCKED OFF. Operators must pass it via runtime env prefix
# only; the execute path is CLI-only and additionally requires
# `DELHIVERY_MODE=live` at runtime, a structured Director
# BEGIN_UTC/END_UTC window, and explicit confirmation.
PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED = _razorpay_webhook_bool(
    "PHASE7G_LIVE_REAL_CUSTOMER_DISPATCH_ENABLED"
)
# `PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED` controls the
# Phase 8A Payment -> Order Mutation Sandbox Gate. Defaults LOCKED
# OFF. Phase 8A is sandbox / dry-run ONLY: it never mutates real
# Order / Payment / Customer / Lead / Shipment /
# DiscountOfferLog rows, never calls Razorpay / Meta Cloud /
# Delhivery / Vapi, never sends WhatsApp, never sends a customer
# notification, never edits any .env file. Approval flips status
# to `approved_for_future_phase8b_review` only - it does NOT
# authorize any real mutation.
PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED = _razorpay_webhook_bool(
    "PHASE8A_PAYMENT_ORDER_MUTATION_SANDBOX_ENABLED"
)
# `PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED` controls the
# Phase 8B Payment -> Order Mutation Review Gate. Defaults LOCKED
# OFF. Phase 8B is review / dry-run ONLY: it never mutates real
# Order / Payment / Customer / Lead / Shipment / DiscountOfferLog
# rows, never calls Razorpay / Meta Cloud / Delhivery / Vapi, never
# sends WhatsApp, never sends a customer notification, never edits
# any .env file. Approval flips status to
# `approved_for_future_phase8c_controlled_mutation_review` only -
# it does NOT authorize any real mutation.
PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED = _razorpay_webhook_bool(
    "PHASE8B_PAYMENT_ORDER_MUTATION_REVIEW_GATE_ENABLED"
)
# `PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED` controls
# the Phase 8C Controlled Real Payment -> Order Mutation framework.
# Defaults LOCKED OFF. Phase 8C is a CLI-only one-shot mutation
# path against a single, explicitly selected internal/sandbox/test
# Order + Payment pair. Execute requires three env flags ALL true,
# a structured Director sign-off UTC window (<= 15 min), the kill
# switch enabled, and a runtime safety proof that the target rows
# are NOT real customer data. Phase 8C NEVER calls Razorpay / Meta
# Cloud / Delhivery / Vapi, NEVER sends WhatsApp, NEVER sends a
# customer notification, NEVER creates a Shipment / AWB / payment
# link, NEVER captures / refunds, NEVER edits any .env file.
PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED = (
    _razorpay_webhook_bool(
        "PHASE8C_PAYMENT_ORDER_CONTROLLED_MUTATION_GATE_ENABLED"
    )
)
PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION = _razorpay_webhook_bool(
    "PHASE8C_DIRECTOR_APPROVED_ONE_SHOT_MUTATION"
)
PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION = _razorpay_webhook_bool(
    "PHASE8C_ALLOW_INTERNAL_ORDER_PAYMENT_MUTATION"
)
# `PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED` controls the
# Phase 8E Real Customer Payment -> Order Mutation Pilot Gate.
# Defaults LOCKED OFF. Phase 8E is review / dry-run ONLY against
# ONE real customer Order + Payment candidate: it never mutates
# real `Order` / `Payment` / `Customer` / `Lead` / `Shipment` /
# `DiscountOfferLog` / `WhatsAppMessage` rows, never calls
# Razorpay / Meta Cloud / Delhivery / Vapi, never sends WhatsApp,
# never sends a customer notification, never edits any .env file.
# Approval flips status to
# `approved_for_future_phase8f_real_customer_controlled_mutation`
# only - it does NOT authorize any real mutation.
PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED = (
    _razorpay_webhook_bool(
        "PHASE8E_REAL_CUSTOMER_PAYMENT_ORDER_PILOT_ENABLED"
    )
)
# `PHASE8F_*` flags gate the Phase 8F Controlled Real Customer
# Payment -> Order Mutation execute path. All three must be true
# at runtime AND the Director sign-off must include a structured
# UTC window (<= 15 min) AND the kill switch must be enabled
# before any execute call is allowed to mutate the chosen
# real-customer Order.payment_status + Payment.status fields.
# Approval alone does NOT execute. Defaults LOCKED OFF. Phase 8F
# never calls Razorpay / Meta Cloud / Delhivery / Vapi, never
# sends or queues WhatsApp, never creates a Shipment / AWB /
# payment link, never captures / refunds, never sends a customer
# notification, never mutates Customer / Lead / Shipment /
# DiscountOfferLog / WhatsAppMessage rows, never mutates
# Order.state, never edits any .env file.
PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED = (
    _razorpay_webhook_bool(
        "PHASE8F_REAL_CUSTOMER_CONTROLLED_MUTATION_GATE_ENABLED"
    )
)
PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION = (
    _razorpay_webhook_bool(
        "PHASE8F_DIRECTOR_APPROVED_ONE_SHOT_REAL_MUTATION"
    )
)
PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION = (
    _razorpay_webhook_bool(
        "PHASE8F_ALLOW_REAL_CUSTOMER_ORDER_PAYMENT_MUTATION"
    )
)
RAZORPAY_WEBHOOK_ALLOW_TEST_EVENTS_ONLY = _razorpay_webhook_bool(
    "RAZORPAY_WEBHOOK_ALLOW_TEST_EVENTS_ONLY", default="true"
)
RAZORPAY_WEBHOOK_REPLAY_WINDOW_SECONDS = _safe_int(
    os.environ.get("RAZORPAY_WEBHOOK_REPLAY_WINDOW_SECONDS"),
    default=300,
)
RAZORPAY_WEBHOOK_ALLOWED_EVENTS = [
    name.strip()
    for name in (
        os.environ.get("RAZORPAY_WEBHOOK_ALLOWED_EVENTS")
        or "payment.authorized,payment.captured,payment.failed,"
        "order.paid,refund.created,refund.processed,"
        "payment_link.paid,payment_link.cancelled,payment_link.expired"
    ).split(",")
    if name.strip()
]
RAZORPAY_WEBHOOK_DENIED_EVENTS = [
    name.strip()
    for name in (
        os.environ.get("RAZORPAY_WEBHOOK_DENIED_EVENTS")
        or "payment.dispute.created,payment.dispute.won,payment.dispute.lost,"
        "transfer.processed,payout.processed,subscription.charged,"
        "invoice.paid,virtual_account.credited,qr_code.closed"
    ).split(",")
    if name.strip()
]


# ----- Phase 6M-0 — MCP Gateway Foundation -----
# Safe defaults: no external client, no write tool, no provider tool.
# Missing token / signing key never crashes the app — readiness simply
# reports the gap.
def _mcp_bool(env_key: str, default: str = "false") -> bool:
    return (os.environ.get(env_key) or default).strip().lower() == "true"


MCP_ENABLED = _mcp_bool("MCP_ENABLED")
MCP_TRANSPORT = (os.environ.get("MCP_TRANSPORT") or "streamable_http").strip()
MCP_PUBLIC_BASE_URL = os.environ.get("MCP_PUBLIC_BASE_URL", "").strip()
MCP_REQUIRE_AUTH = _mcp_bool("MCP_REQUIRE_AUTH", default="true")
MCP_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in (os.environ.get("MCP_ALLOWED_ORIGINS") or "").split(",")
    if origin.strip()
]
MCP_SERVICE_TOKEN = os.environ.get("MCP_SERVICE_TOKEN", "")
MCP_JWT_SIGNING_KEY = os.environ.get("MCP_JWT_SIGNING_KEY", "")
MCP_TOKEN_TTL_SECONDS = _safe_int(
    os.environ.get("MCP_TOKEN_TTL_SECONDS"), default=3600
)
MCP_READ_ONLY_MODE = _mcp_bool("MCP_READ_ONLY_MODE", default="true")
MCP_WRITE_TOOLS_ENABLED = _mcp_bool("MCP_WRITE_TOOLS_ENABLED")
MCP_PROVIDER_TOOLS_ENABLED = _mcp_bool("MCP_PROVIDER_TOOLS_ENABLED")
MCP_AUDIT_ENABLED = _mcp_bool("MCP_AUDIT_ENABLED", default="true")
MCP_MASK_PII = _mcp_bool("MCP_MASK_PII", default="true")
MCP_MAX_TOOL_CALLS_PER_MINUTE = _safe_int(
    os.environ.get("MCP_MAX_TOOL_CALLS_PER_MINUTE"), default=30
)
MCP_MAX_OUTPUT_CHARS = _safe_int(
    os.environ.get("MCP_MAX_OUTPUT_CHARS"), default=12000
)
MCP_EXPOSE_RESOURCES = _mcp_bool("MCP_EXPOSE_RESOURCES")
MCP_EXPOSE_PROMPTS = _mcp_bool("MCP_EXPOSE_PROMPTS")


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


# ----- Phase 5C — WhatsApp AI Chat Sales Agent -----
# Auto-reply behaviour. Defaults are SAFE (off) so a fresh deploy never
# auto-replies to a customer until ops explicitly opt in. Production is
# expected to flip the env var to true once the WhatsApp team verifies
# the conversation flow on a controlled set of test numbers.
WHATSAPP_AI_AUTO_REPLY_ENABLED = _bool(
    os.environ.get("WHATSAPP_AI_AUTO_REPLY_ENABLED"), default=False
)
WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD = _safe_float(
    os.environ.get("WHATSAPP_AI_AUTO_REPLY_CONFIDENCE_THRESHOLD"),
    default=0.75,
)
# Per-conversation + per-customer rate limits to bound runaway loops.
WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR = _safe_int(
    os.environ.get("WHATSAPP_AI_MAX_TURNS_PER_CONVERSATION_PER_HOUR"),
    default=10,
)
WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY = _safe_int(
    os.environ.get("WHATSAPP_AI_MAX_MESSAGES_PER_CUSTOMER_PER_DAY"),
    default=30,
)


# ----- Phase 5D — Chat-to-Call Handoff + Lifecycle Automation -----
# Direct WhatsApp → Vapi handoff. Defaults OFF so a fresh deploy does
# not auto-dial customers until ops verify the Vapi assistant config
# end-to-end (mock first, OpenAI test second, then limited live Meta).
WHATSAPP_CALL_HANDOFF_ENABLED = _bool(
    os.environ.get("WHATSAPP_CALL_HANDOFF_ENABLED"), default=False
)

# Lifecycle template automation. Defaults OFF — when enabled, business
# events (order moved to confirmation, payment link created, shipment
# out for delivery / NDR / RTO) trigger approved-template sends through
# the existing Phase 5A pipeline. All consent / Claim Vault / approval
# matrix / CAIO gates remain in force.
WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED = _bool(
    os.environ.get("WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"), default=False
)

# Limited live Meta test mode — when WHATSAPP_PROVIDER=meta_cloud and
# this flag is true, the service layer refuses to send to any number
# not in WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS. This is the bridge
# between mock+OpenAI verification and a full production rollout.
WHATSAPP_LIVE_META_LIMITED_TEST_MODE = _bool(
    os.environ.get("WHATSAPP_LIVE_META_LIMITED_TEST_MODE"), default=True
)
WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS = _csv(
    os.environ.get("WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS")
)


# ----- Phase 5E — Rescue Discount Flow + Day-20 Reorder + Default Claims -----
# All defaults stay OFF / SAFE so a fresh deploy never automatically
# offers a customer a discount. Production rollout sequence:
#   1) Mock + OpenAI verification on test customers.
#   2) Limited-live Meta with one test number.
#   3) Flip WHATSAPP_RESCUE_DISCOUNT_ENABLED=true (confirmation +
#      delivery refusals; uses the WhatsApp AI agent).
#   4) Flip WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=true once RTO rescue
#      flow has soaked for 3+ days.
#   5) Flip WHATSAPP_REORDER_DAY20_ENABLED=true and start the daily
#      Celery beat for run_reorder_day20_sweep.
#
# DEFAULT_CLAIMS_SEED_DEMO_ONLY=true keeps the demo Claim Vault visible
# in coverage reports as ``risk=demo_ok`` and forces production ops to
# replace each row with a doctor-approved claim before promoting the
# Claim out of demo mode.
WHATSAPP_RESCUE_DISCOUNT_ENABLED = _bool(
    os.environ.get("WHATSAPP_RESCUE_DISCOUNT_ENABLED"), default=False
)
WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED = _bool(
    os.environ.get("WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED"), default=False
)
WHATSAPP_REORDER_DAY20_ENABLED = _bool(
    os.environ.get("WHATSAPP_REORDER_DAY20_ENABLED"), default=False
)
DEFAULT_CLAIMS_SEED_DEMO_ONLY = _bool(
    os.environ.get("DEFAULT_CLAIMS_SEED_DEMO_ONLY"), default=True
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
