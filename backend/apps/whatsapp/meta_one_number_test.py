"""Phase 5E-Smoke-Fix-3 → Phase 5F-Gate — Limited Live Meta One-Number Test.

This module owns the **single safe entry point** for verifying real Meta
WhatsApp Cloud API sends against exactly one approved test number,
without enabling AI auto-reply, broadcasts, lifecycle automation,
rescue / RTO / reorder automation, or freeform text.

LOCKED safety rules (every rule below is enforced at the function level
AND at the management-command level — defence in depth):

1. Provider must be ``meta_cloud``.
2. ``WHATSAPP_LIVE_META_LIMITED_TEST_MODE`` must be ``True``.
3. ``WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS`` must be **non-empty** and
   the destination number must be in it (after E.164 normalisation).
4. The send must use an **APPROVED + active** ``WhatsAppTemplate`` row.
   Freeform text is refused outright.
5. AI auto-reply must remain ``False``.
6. CAIO actor token is refused.
7. Real send only when ``--send`` is explicitly passed AND nothing above
   has failed; default mode is dry-run.
8. ``OPENAI_API_KEY`` / ``META_WA_ACCESS_TOKEN`` are NEVER copied into
   audit payloads.

Every block writes a ``whatsapp.meta_test.*`` ledger row so an operator
can replay the run from `/api/dashboard/activity/`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from django.conf import settings

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import WhatsAppConnection, WhatsAppTemplate


_DIGITS_RE = re.compile(r"\D+")


def _normalize_phone(phone: str | None) -> str:
    """Reduce a phone string to a leading-`+` E.164 form.

    The allow-list comparison is digits-only, so this canonicaliser is
    permissive about formatting (`+91 90000 99991`, `91-9000099991`,
    `9000099991` all collapse to the same digit string).
    """
    if not phone:
        return ""
    cleaned = _DIGITS_RE.sub("", str(phone))
    return f"+{cleaned}" if cleaned else ""


def _digits_only(phone: str | None) -> str:
    return _DIGITS_RE.sub("", str(phone or ""))


def get_allowed_test_numbers() -> list[str]:
    """Return the configured allow-list as a list of digit strings."""
    raw = getattr(settings, "WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS", "") or ""
    if isinstance(raw, (list, tuple)):
        items: Iterable[Any] = raw
    else:
        items = [chunk for chunk in str(raw).split(",")]
    out: list[str] = []
    for item in items:
        digits = _digits_only(item)
        if digits:
            out.append(digits)
    return out


def is_number_allowed_for_live_meta_test(phone: str | None) -> bool:
    """Return True iff the number is on the configured allow-list.

    The allow-list is read fresh from settings on every call so test
    overrides via ``override_settings`` take effect immediately.
    """
    digits = _digits_only(phone)
    if not digits:
        return False
    allow = get_allowed_test_numbers()
    if not allow:
        return False
    return digits in allow


# ---------------------------------------------------------------------------
# Result dataclass shared with the management command + tests.
# ---------------------------------------------------------------------------


@dataclass
class MetaOneNumberTestResult:
    """In-memory result. The management command serialises this to JSON."""

    passed: bool = False
    dry_run: bool = True
    send_attempted: bool = False
    provider: str = ""
    limited_test_mode: bool = False
    to_normalized: str = ""
    to_allowed: bool = False
    template: str = ""
    template_language: str = ""
    template_approved: bool = False
    message_id: str = ""
    provider_message_id: str = ""
    audit_events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_action: str = ""
    duplicate_idempotency_key: bool = False
    already_queued: bool = False
    already_sent: bool = False
    existing_message_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "dryRun": self.dry_run,
            "sendAttempted": self.send_attempted,
            "provider": self.provider,
            "limitedTestMode": self.limited_test_mode,
            "to": self.to_normalized,
            "toAllowed": self.to_allowed,
            "template": self.template,
            "templateLanguage": self.template_language,
            "templateApproved": self.template_approved,
            "messageId": self.message_id,
            "providerMessageId": self.provider_message_id,
            "duplicateIdempotencyKey": self.duplicate_idempotency_key,
            "alreadyQueued": self.already_queued,
            "alreadySent": self.already_sent,
            "existingMessageId": self.existing_message_id,
            "auditEvents": list(self.audit_events),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "nextAction": self.next_action,
        }


# ---------------------------------------------------------------------------
# Audit helpers (no secrets in payloads, ever).
# ---------------------------------------------------------------------------


def _emit(
    *,
    kind: str,
    text: str,
    tone: str,
    payload: dict[str, Any] | None = None,
    result: MetaOneNumberTestResult | None = None,
) -> None:
    safe_payload = {k: v for k, v in (payload or {}).items() if "token" not in k.lower()}
    write_event(kind=kind, text=text, tone=tone, payload=safe_payload)
    if result is not None:
        result.audit_events.append(kind)


def emit_started(*, to_normalized: str, template_name: str, dry_run: bool, send: bool) -> None:
    _emit(
        kind="whatsapp.meta_test.started",
        text=(
            f"Meta one-number test started · template={template_name or '(unspecified)'} "
            f"· dryRun={dry_run} · send={send}"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "to_digits_suffix": to_normalized[-4:] if to_normalized else "",
            "template": template_name,
            "dry_run": dry_run,
            "send_requested": send,
        },
    )


def emit_blocked_number(*, to_digits: str, allow_list_size: int) -> None:
    _emit(
        kind="whatsapp.meta_test.blocked_number",
        text=(
            f"Meta one-number test refused · destination not in "
            f"WHATSAPP_LIVE_META_ALLOWED_TEST_NUMBERS (allow_list_size={allow_list_size})"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "to_digits_suffix": to_digits[-4:] if to_digits else "",
            "allow_list_size": allow_list_size,
        },
    )


def emit_template_missing(*, template_name: str, action_key: str, language: str, reason: str) -> None:
    _emit(
        kind="whatsapp.meta_test.template_missing",
        text=f"Meta one-number test refused · template not approved/active: {reason}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "template": template_name,
            "action_key": action_key,
            "language": language,
            "reason": reason,
        },
    )


def emit_config_failed(*, missing_keys: list[str]) -> None:
    _emit(
        kind="whatsapp.meta_test.config_failed",
        text=(
            f"Meta one-number test refused · provider/credential "
            f"check failed: missing={','.join(missing_keys) or 'none'}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload={"missing_keys": list(missing_keys)},
    )


def emit_config_ok(*, provider: str, api_version: str, app_secret_set: bool, verify_token_set: bool) -> None:
    _emit(
        kind="whatsapp.meta_test.config_ok",
        text=f"Meta one-number test config ok · provider={provider}",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "provider": provider,
            "api_version": api_version,
            "app_secret_set": app_secret_set,
            "verify_token_set": verify_token_set,
        },
    )


def emit_sent(*, message_id: str, provider_message_id: str, template_name: str) -> None:
    _emit(
        kind="whatsapp.meta_test.sent",
        text=(
            f"Meta one-number test send dispatched · message_id={message_id} "
            f"· template={template_name}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "message_id": message_id,
            "provider_message_id": provider_message_id,
            "template": template_name,
        },
    )


def emit_duplicate_idempotency(
    *,
    idempotency_key: str,
    existing_message_id: str,
    existing_status: str,
    template_name: str,
) -> None:
    """Phase 5F-Gate Hardening Hotfix — duplicate idempotency_key path.

    The CLI used to crash with an IntegrityError traceback when the
    same allowed number was sent the same template within the daily
    idempotency window. We now report the duplicate cleanly and point
    the operator at the existing row.
    """
    _emit(
        kind="whatsapp.meta_test.duplicate_idempotency",
        text=(
            f"Meta one-number test refused · duplicate idempotency_key "
            f"matches existing message {existing_message_id} ({existing_status})"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "idempotency_key_suffix": (idempotency_key or "")[-12:],
            "existing_message_id": existing_message_id,
            "existing_status": existing_status,
            "template": template_name,
        },
    )


def emit_failed(*, error_code: str, error_message: str, template_name: str) -> None:
    _emit(
        kind="whatsapp.meta_test.failed",
        text=f"Meta one-number test send failed · {error_code}: {error_message[:160]}",
        tone=AuditEvent.Tone.DANGER,
        payload={
            "error_code": error_code,
            "error_message": (error_message or "")[:480],
            "template": template_name,
        },
    )


def emit_webhook_subscription_checked(*, status) -> None:
    """Phase 5F-Gate Hardening Hotfix — emit a single audit row per check.

    The emitter never crashes if the GraphAPI lookup itself failed; it
    just records what the diagnostics layer found.
    """
    _emit(
        kind="whatsapp.meta_test.webhook_subscription_checked",
        text=(
            f"WABA subscription checked · checked={status.checked} "
            f"· active={status.active} · count={status.subscribed_app_count}"
        ),
        tone=(
            AuditEvent.Tone.SUCCESS
            if status.active
            else AuditEvent.Tone.WARNING
        ),
        payload={
            "checked": status.checked,
            "active": status.active,
            "subscribed_app_count": status.subscribed_app_count,
            "warning": status.warning,
            "error": status.error,
        },
    )


def emit_completed(*, passed: bool, dry_run: bool, send_attempted: bool) -> None:
    _emit(
        kind="whatsapp.meta_test.completed",
        text=(
            f"Meta one-number test completed · passed={passed} "
            f"· dryRun={dry_run} · sendAttempted={send_attempted}"
        ),
        tone=AuditEvent.Tone.SUCCESS if passed else AuditEvent.Tone.WARNING,
        payload={
            "passed": passed,
            "dry_run": dry_run,
            "send_attempted": send_attempted,
        },
    )


# ---------------------------------------------------------------------------
# Verification logic — used by `--verify-only` and the precondition stack.
# ---------------------------------------------------------------------------


@dataclass
class VerificationOutcome:
    ok: bool
    provider: str
    limited_test_mode: bool
    missing_keys: list[str]
    automation_off: bool
    automation_warnings: list[str]
    api_version: str
    app_secret_set: bool
    verify_token_set: bool


REQUIRED_META_ENV_KEYS: tuple[str, ...] = (
    "META_WA_ACCESS_TOKEN",
    "META_WA_PHONE_NUMBER_ID",
    "META_WA_BUSINESS_ACCOUNT_ID",
    "META_WA_VERIFY_TOKEN",
)

# App secret may live in either META_WA_APP_SECRET or
# WHATSAPP_WEBHOOK_SECRET — both are checked.
_AUTOMATION_FLAGS_THAT_MUST_STAY_OFF: tuple[str, ...] = (
    "WHATSAPP_AI_AUTO_REPLY_ENABLED",
    "WHATSAPP_CALL_HANDOFF_ENABLED",
    "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED",
    "WHATSAPP_RESCUE_DISCOUNT_ENABLED",
    "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED",
    "WHATSAPP_REORDER_DAY20_ENABLED",
)


def verify_provider_and_credentials() -> VerificationOutcome:
    """Run the precondition stack and return a structured outcome.

    Does NOT raise — callers translate ``ok=False`` into a refusal.
    """
    provider = (getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock").lower()
    limited = bool(getattr(settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False))
    missing: list[str] = []

    if provider != "meta_cloud":
        missing.append("WHATSAPP_PROVIDER")

    for key in REQUIRED_META_ENV_KEYS:
        if not getattr(settings, key, ""):
            missing.append(key)

    app_secret_set = bool(
        getattr(settings, "META_WA_APP_SECRET", "")
        or getattr(settings, "WHATSAPP_WEBHOOK_SECRET", "")
    )
    if not app_secret_set:
        missing.append("META_WA_APP_SECRET_OR_WHATSAPP_WEBHOOK_SECRET")

    automation_warnings: list[str] = []
    automation_off = True
    for flag in _AUTOMATION_FLAGS_THAT_MUST_STAY_OFF:
        if bool(getattr(settings, flag, False)):
            automation_warnings.append(flag)
            automation_off = False

    return VerificationOutcome(
        ok=(provider == "meta_cloud" and limited and not missing and automation_off),
        provider=provider,
        limited_test_mode=limited,
        missing_keys=missing,
        automation_off=automation_off,
        automation_warnings=automation_warnings,
        api_version=str(getattr(settings, "META_WA_API_VERSION", "v20.0") or "v20.0"),
        app_secret_set=app_secret_set,
        verify_token_set=bool(getattr(settings, "META_WA_VERIFY_TOKEN", "")),
    )


# ---------------------------------------------------------------------------
# Template resolver — only APPROVED + active templates can send.
# ---------------------------------------------------------------------------


def resolve_test_template(
    *,
    template_name: str = "",
    action_key: str = "",
    language: str = "hi",
    connection: WhatsAppConnection | None = None,
) -> tuple[WhatsAppTemplate | None, str]:
    """Return (template, reason). ``reason`` is empty on success.

    Selection precedence:
      1. Explicit ``template_name`` lookup.
      2. ``action_key`` (e.g. ``whatsapp.greeting``) via the registry.
      3. Default fallback: ``whatsapp.greeting`` action.

    Templates must be ``APPROVED`` AND ``is_active`` AND
    ``status='APPROVED'``. Anything else is refused.
    """
    qs = WhatsAppTemplate.objects.all()
    if connection is not None:
        qs = qs.filter(connection=connection)

    template: WhatsAppTemplate | None = None
    if template_name:
        template = (
            qs.filter(
                name=template_name,
                language=language,
            ).first()
            or qs.filter(name=template_name).first()
        )
    elif action_key:
        template = (
            qs.filter(
                action_key=action_key,
                language=language,
            ).first()
            or qs.filter(action_key=action_key).first()
        )
    else:
        # Default: approved greeting template — universally safe (UTILITY,
        # no Claim Vault dependency).
        template = (
            qs.filter(action_key="whatsapp.greeting", language=language).first()
            or qs.filter(action_key="whatsapp.greeting").first()
        )

    if template is None:
        return None, "template_not_found"
    if template.status != WhatsAppTemplate.Status.APPROVED:
        return None, f"template_not_approved (status={template.status})"
    if not template.is_active:
        return None, "template_inactive"
    if template.category == WhatsAppTemplate.Category.MARKETING:
        # Marketing tier is for Phase 5F. The one-number test only runs
        # UTILITY / AUTHENTICATION templates.
        return None, "template_is_marketing_tier"
    return template, ""


def find_existing_message_by_idempotency_key(
    idempotency_key: str,
):
    """Return the live ``WhatsAppMessage`` row for an idempotency key.

    Imported lazily to keep this module import-safe at Django settings
    load time (the management command imports the helper before
    settings are fully built in some contexts).
    """
    if not idempotency_key:
        return None
    from .models import WhatsAppMessage

    return (
        WhatsAppMessage.objects.filter(idempotency_key=idempotency_key)
        .order_by("-created_at")
        .first()
    )


# ---------------------------------------------------------------------------
# WABA subscribed_apps diagnostics
# ---------------------------------------------------------------------------


@dataclass
class WabaSubscriptionStatus:
    """Result of inspecting ``GET /{WABA_ID}/subscribed_apps``."""

    checked: bool = False
    active: bool | None = None
    subscribed_app_count: int = 0
    warning: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wabaSubscriptionChecked": self.checked,
            "wabaSubscriptionActive": self.active,
            "wabaSubscribedAppCount": self.subscribed_app_count,
            "wabaSubscriptionWarning": self.warning,
            "wabaSubscriptionError": self.error,
        }


def check_waba_subscription() -> WabaSubscriptionStatus:
    """Best-effort check of the WhatsApp Business Account's webhook subscription.

    Calls ``GET https://graph.facebook.com/{api}/{WABA_ID}/subscribed_apps``
    with the configured ``META_WA_ACCESS_TOKEN``. The call is read-only
    and never mutates anything. Returns a :class:`WabaSubscriptionStatus`
    so callers can decide whether to surface the warning. Never raises.

    Hard rules:
    - Never log / return the access token.
    - Never raise — return ``error`` instead so the CLI keeps producing
      JSON.
    - Skip outright when ``META_WA_BUSINESS_ACCOUNT_ID`` /
      ``META_WA_ACCESS_TOKEN`` are missing.
    """
    waba_id = (getattr(settings, "META_WA_BUSINESS_ACCOUNT_ID", "") or "").strip()
    token = (getattr(settings, "META_WA_ACCESS_TOKEN", "") or "").strip()
    api_version = (getattr(settings, "META_WA_API_VERSION", "v20.0") or "v20.0").strip()

    status = WabaSubscriptionStatus()
    if not waba_id or not token:
        status.warning = "META_WA_BUSINESS_ACCOUNT_ID or META_WA_ACCESS_TOKEN missing — skipping Graph check."
        return status

    try:
        import requests  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - requests is in requirements
        status.error = "requests package not available; cannot check WABA subscription."
        return status

    url = f"https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - any transport failure
        status.error = f"Graph subscribed_apps GET failed: {type(exc).__name__}"
        return status

    status.checked = True
    if not response.ok:
        status.error = (
            f"Graph subscribed_apps GET returned HTTP {response.status_code}"
        )
        return status

    try:
        body = response.json() or {}
    except Exception:  # noqa: BLE001 - non-JSON path
        status.error = "Graph subscribed_apps GET returned non-JSON body."
        return status

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        status.error = "Graph subscribed_apps GET returned unexpected shape."
        return status

    status.subscribed_app_count = len(data)
    status.active = len(data) > 0
    if not status.active:
        status.warning = (
            "subscribed_apps is empty — Meta will NOT deliver inbound webhooks. "
            "Run: POST /{WABA_ID}/subscribed_apps with override_callback_uri="
            "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/ + verify_token."
        )
    return status


def webhook_url_summary() -> dict[str, Any]:
    """Return a doc-friendly summary of webhook endpoints + verify-token presence."""
    return {
        "callbackUrl": "https://ai.nirogidhara.com/api/webhooks/whatsapp/meta/",
        "verifyTokenSet": bool(getattr(settings, "META_WA_VERIFY_TOKEN", "")),
        "appSecretSet": bool(
            getattr(settings, "META_WA_APP_SECRET", "")
            or getattr(settings, "WHATSAPP_WEBHOOK_SECRET", "")
        ),
        "subscribedFields": ["messages"],
        "apiVersion": str(getattr(settings, "META_WA_API_VERSION", "v20.0")),
        "notes": [
            "Meta Developer Console → WhatsApp → Configuration → Webhook.",
            "Set callback URL exactly as above; paste META_WA_VERIFY_TOKEN as the Verify Token.",
            "Subscribe at minimum to the 'messages' field; production also subscribes 'message_template_status_update'.",
            "X-Hub-Signature-256 is verified server-side — never disable signature checks.",
        ],
    }


__all__ = (
    "MetaOneNumberTestResult",
    "REQUIRED_META_ENV_KEYS",
    "VerificationOutcome",
    "WabaSubscriptionStatus",
    "check_waba_subscription",
    "emit_blocked_number",
    "emit_completed",
    "emit_config_failed",
    "emit_config_ok",
    "emit_duplicate_idempotency",
    "emit_failed",
    "emit_sent",
    "emit_started",
    "emit_template_missing",
    "emit_webhook_subscription_checked",
    "find_existing_message_by_idempotency_key",
    "get_allowed_test_numbers",
    "is_number_allowed_for_live_meta_test",
    "resolve_test_template",
    "verify_provider_and_credentials",
    "webhook_url_summary",
)
