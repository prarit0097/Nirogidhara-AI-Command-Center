"""Phase 15C — Audit Timeline read-only view.

Public surface: ``GET /api/audit/timeline/`` returns a sanitised
window into the Master Event Ledger so admins/directors can review
recent state changes without exposing any sensitive body content.

Hard rules (defense in depth — even if a future writer accidentally
stuffs a sensitive field into ``AuditEvent.payload``):

* The endpoint NEVER mutates state. POST / PUT / PATCH / DELETE
  return 405.
* The endpoint NEVER writes a new ``AuditEvent`` row.
* The endpoint NEVER calls a provider (Razorpay, Meta Cloud,
  Delhivery, Vapi, OpenAI, Anthropic, NVIDIA, OpenRouter).
* The endpoint NEVER enqueues a Celery task.
* The endpoint NEVER mutates business tables.
* The endpoint NEVER changes ``RuntimeKillSwitch`` / ``SandboxState``.
* The endpoint NEVER edits any ``.env*`` file.
* The endpoint NEVER returns the raw ``AuditEvent.payload`` —
  only the explicit safe-key allow-list below.
* String values are truncated defensively at ``_MAX_VALUE_CHARS``.
* Phone / email / address / token / secret / raw-body keys are
  dropped outright.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission

from .models import AuditEvent


class _AdminAndUpAuditTimeline(RoleBasedPermission):
    """Phase 15C — audit timeline is admin/director/owner/superuser only.

    Mirrors the Phase 15A ``_AdminAndUpAlways`` pattern: viewer and
    anonymous users are blocked entirely.
    """

    allowed_roles = ADMIN_AND_UP

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request.user, "role", None) in self.allowed_roles


# ---------------------------------------------------------------------------
# Category mapping. Categories are derived by audit-kind prefix only —
# we never inspect the payload to assign a category. New audit kinds
# automatically fall into ``other`` until a category prefix is added,
# which is the safe default.
# ---------------------------------------------------------------------------

CATEGORY_SAFETY = "safety"
CATEGORY_ROLLBACK = "rollback"
CATEGORY_AI_GOVERNANCE = "ai_governance"
CATEGORY_WHATSAPP = "whatsapp"
CATEGORY_PAYMENTS = "payments"
CATEGORY_ORDERS = "orders"
CATEGORY_DELIVERY = "delivery"
CATEGORY_AUTH_SYSTEM = "auth_system"
CATEGORY_OTHER = "other"

ALL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_SAFETY,
    CATEGORY_ROLLBACK,
    CATEGORY_AI_GOVERNANCE,
    CATEGORY_WHATSAPP,
    CATEGORY_PAYMENTS,
    CATEGORY_ORDERS,
    CATEGORY_DELIVERY,
    CATEGORY_AUTH_SYSTEM,
    CATEGORY_OTHER,
)


def categorize_kind(kind: str) -> str:
    """Map an ``AuditEvent.kind`` string to a UI-friendly category slug.

    Prefix dispatch only. Rollback wins over safety where they overlap
    (``ai.prompt_version.rolled_back`` is rollback first). Safety
    covers explicit kill-switch / sandbox / compliance flags.
    """
    if not isinstance(kind, str) or not kind:
        return CATEGORY_OTHER

    k = kind.lower()

    # Rollback first (rolled_back / rollback / rolled-back).
    if "rolled_back" in k or "rollback" in k:
        return CATEGORY_ROLLBACK

    # Explicit safety: kill switch, sandbox, compliance flag, safety
    # downgrades, invariant violations.
    if (
        "kill_switch" in k
        or k.startswith("ai.sandbox")
        or k.startswith("compliance.")
        or "safety_downgraded" in k
        or "invariant_violation" in k
    ):
        return CATEGORY_SAFETY

    # AI governance (prompt versions, agent runs, approvals, budgets,
    # CAIO, CEO briefings, sandbox transitions handled above).
    if (
        k.startswith("ai.")
        or k.startswith("approval.")
        or k.startswith("prompt_version.")
        or k.startswith("learning.")
        or k.startswith("call_outcome.")
        or k.startswith("call_quality.")
        or k.startswith("transcript.")
        or k.startswith("caio.")
        or k.startswith("ceo_orchestration.")
        or k.startswith("rto_prevention.")
        or k.startswith("customer_success.")
        or k.startswith("cfo.")
        or k.startswith("data_analyst.")
        or k.startswith("calling_team_leader.")
        or k.startswith("ai_calling.")
    ):
        return CATEGORY_AI_GOVERNANCE

    # WhatsApp surfaces.
    if k.startswith("whatsapp.") or k.startswith("call_followup."):
        return CATEGORY_WHATSAPP

    # Delivery / shipments / RTO / Delhivery / courier. Checked
    # BEFORE the Razorpay/payments branch so audit kinds like
    # ``razorpay.courier_execution.executed`` land under delivery
    # rather than payments.
    if (
        k.startswith("shipment.")
        or k.startswith("rto.")
        or k.startswith("delhivery.")
        or "courier" in k
        or "phase7g" in k
        or "phase7h" in k
        or "phase7f" in k
    ):
        return CATEGORY_DELIVERY

    # Payments / Razorpay / discounts.
    if (
        k.startswith("payment.")
        or k.startswith("razorpay.")
        or k.startswith("discount.")
        or k.startswith("phase8")
        or k.startswith("phase7d")
        or k.startswith("phase10")
    ):
        return CATEGORY_PAYMENTS

    # Orders / catalog / rewards.
    if (
        k.startswith("order.")
        or k.startswith("catalog.")
        or k.startswith("reward.")
        or k.startswith("rescue.")
        or k.startswith("confirmation.")
    ):
        return CATEGORY_ORDERS

    # Calls go under AI governance — they're consumed by Vapi/CAIO
    # learning loops. Lead/customer events go under orders.
    if k.startswith("call.") or k.startswith("lead.") or k.startswith("customer."):
        if k.startswith("call.") or k.startswith("lead.meta_"):
            return CATEGORY_AI_GOVERNANCE
        return CATEGORY_ORDERS

    # Auth, SaaS scaffold, MCP, runtime, smoke tests, system events.
    if (
        k.startswith("saas.")
        or k.startswith("runtime.")
        or k.startswith("mcp.")
        or k.startswith("system.")
        or k.startswith("auth.")
    ):
        return CATEGORY_AUTH_SYSTEM

    return CATEGORY_OTHER


class AuditTimelineView(APIView):
    """Phase 15C — read-only audit timeline.

    Returns sanitised audit rows filtered by kind, tone, category,
    text query, and date range. Pagination via ``limit``/``offset``.
    """

    permission_classes = [_AdminAndUpAuditTimeline]

    _MAX_LIMIT = 200
    _DEFAULT_LIMIT = 50
    _MAX_VALUE_CHARS = 200  # defensive truncation for surfaced strings

    # Keys we are willing to surface from ``AuditEvent.payload``. These
    # are stable identifiers / labels / counts used across the codebase
    # for audit context. Any other key is dropped to prevent leaking
    # sensitive body content even if a future writer accidentally
    # includes it.
    _ALLOWED_PAYLOAD_KEYS: frozenset[str] = frozenset(
        {
            # Phase / source / actor breadcrumbs.
            "phase",
            "source",
            "action",
            "actor",
            "agent",
            "operator_name",
            "by",
            "reason",
            # ID handles — always integers or short slug strings.
            "lead_id",
            "order_id",
            "payment_id",
            "shipment_id",
            "customer_id",
            "call_id",
            "campaign_gate_id",
            "outcome_record_id",
            "follow_up_id",
            "gate_id",
            "attempt_id",
            "rollback_id",
            "snapshot_id",
            "proposal_id",
            "lock_id",
            "execution_id",
            "version_id",
            "previous_version_id",
            "previous_active_version_id",
            "target_version_id",
            "membership_id",
            "organization_id",
            "integration_setting_id",
            "lifecycle_event_id",
            "conversation_id",
            "message_id",
            "inbound_message_id",
            "outbound_message_id",
            # Stage / status / mode labels.
            "stage",
            "status",
            "kind",
            "mode",
            "tier",
            "decision",
            "matrix_action",
            "matrix_status",
            "severity",
            "tone",
            "review_status",
            "validation_status",
            "is_active",
            "created",
            # Version labels (short strings only — never the prompt body).
            "previous_version",
            "previous_version_label",
            "target_version",
            "target_version_label",
            # Safe stats / counts.
            "duration_ms",
            "claim_row_count",
            "approved_claim_count",
            "disallowed_phrase_count",
            "score",
            "composite_score",
            "confidence",
            "amount",
            "currency",
            # Last-4 / suffix-only identifiers (never full E.164/email).
            "phone_suffix",
            "phone_last4",
            "vapi_call_id_last4",
            "provider_object_id_last4",
            "ai_assistant_id_last4",
            "agent_label_suffix",
            # Short labels.
            "organization_code",
            "provider_type",
            "display_name",
            "category",
            "normalized_claim_product",
            "language",
            "channel",
            "template_id",
            "template_name",
            "template_status",
            "template_category",
            "fallback_reason",
            "final_reply_source",
            "trigger_path",
            "next_action",
            # Booleans.
            "consent_verified",
            "real_money",
            "live_execution_allowed",
            "external_call_will_be_made",
            "external_call_was_made",
            "provider_call_attempted",
            "dry_run",
            "sandbox",
            "consent_required",
            "deterministic_fallback_used",
            "claim_vault_used",
            "history_safety_ignored_for_current_safe_query",
            # Smoke-test / activity counters (small numeric maps are OK).
            "auto_reply_flag_path_used_count",
            "reply_auto_sent_count",
            "deterministic_builder_used_count",
            "unexpected_non_allowed_sends_count",
            # Short flag list arrays — content is bounded.
            "history_safety_flags",
            "latest_inbound_safety_flags",
            "flags",
            "used_approved_phrases",
            "blockers",
            "warnings",
            "force_auto_reply",
            "triggered_by",
            # Hashes (no secrets — these are SHA-256 hex digests).
            "signoff_hash",
            "payload_hash",
            "evidence_hash",
        }
    )

    # Keys we explicitly REJECT even if accidentally added to the
    # allow-list above. Defence in depth — keep this list in sync with
    # known sensitive payload patterns across the codebase.
    _FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
        {
            "token",
            "access_token",
            "refresh_token",
            "verify_token",
            "app_secret",
            "secret",
            "api_key",
            "razorpay_key_secret",
            "razorpay_key_id",
            "META_WA_TOKEN",
            "VAPI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DELHIVERY_API_TOKEN",
            "phone",
            "customer_phone",
            "phone_number",
            "to_phone",
            "from_phone",
            "email",
            "customer_email",
            "address",
            "shipping_address",
            "card",
            "card_last4",
            "vpa",
            "upi",
            "raw_response",
            "raw_payload",
            "raw_request",
            "raw_signature",
            "raw_body",
            "gateway_reference_id",
            "payment_url",
            "system_policy",
            "role_prompt",
            "instruction_payload",
            "messages",
            "provider_payload",
            "transcript",
            "transcript_text",
            "reply_text",
            "inbound_text",
            "customer_name",
            "name",
            "director_signoff",
            "signoff_text",
            "metadata",
            "evidence_json",
            "request_summary",
            "response_summary",
            "briefing_text",
        }
    )

    @classmethod
    def _truncate(cls, value: Any) -> Any:
        """Cap surfaced string length at ``_MAX_VALUE_CHARS``.

        Lists/dicts pass through but their string members are also
        truncated recursively (one level deep). Non-string, non-list,
        non-dict values pass through unchanged.
        """
        if isinstance(value, str):
            if len(value) > cls._MAX_VALUE_CHARS:
                return value[: cls._MAX_VALUE_CHARS - 3] + "..."
            return value
        if isinstance(value, list):
            return [cls._truncate(v) for v in value[:20]]
        if isinstance(value, dict):
            # Single-level dict truncation — strip forbidden keys + cap
            # remaining string values.
            return {
                k: cls._truncate(v)
                for k, v in value.items()
                if isinstance(k, str)
                and k not in cls._FORBIDDEN_PAYLOAD_KEYS
            }
        return value

    @classmethod
    def _safe_payload_slice(cls, payload: Any) -> dict:
        """Allow-listed slice of an ``AuditEvent.payload`` row.

        Returns ``{}`` for non-dict payloads. Drops every forbidden
        key. Truncates string values defensively.
        """
        if not isinstance(payload, dict):
            return {}
        out: dict = {}
        for key in cls._ALLOWED_PAYLOAD_KEYS:
            if key in payload and key not in cls._FORBIDDEN_PAYLOAD_KEYS:
                out[key] = cls._truncate(payload[key])
        return out

    @classmethod
    def _serialize_event(cls, event: AuditEvent) -> dict:
        return {
            "id": event.id,
            "occurredAt": event.occurred_at.isoformat(),
            "kind": event.kind,
            "tone": event.tone,
            "icon": event.icon,
            "text": cls._truncate(event.text or ""),
            "category": categorize_kind(event.kind),
            "payload": cls._safe_payload_slice(event.payload),
        }

    def _parse_date(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        # Accept full ISO datetime or YYYY-MM-DD (treat as midnight UTC).
        parsed = parse_datetime(raw)
        if parsed is not None:
            return parsed
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

    def get(self, request):
        qs = AuditEvent.objects.all()

        # Filter — exact kind.
        kind = (request.query_params.get("kind") or "").strip()
        if kind:
            qs = qs.filter(kind=kind)

        # Filter — tone (success/info/warning/danger).
        tone = (request.query_params.get("tone") or "").strip().lower()
        if tone:
            valid_tones = {t for t, _ in AuditEvent.Tone.choices}
            if tone not in valid_tones:
                return Response(
                    {
                        "detail": (
                            "tone must be one of "
                            + ", ".join(sorted(valid_tones))
                            + "."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(tone=tone)

        # Filter — category (prefix-derived; applied in Python since
        # the AuditEvent table has no category column).
        category = (request.query_params.get("category") or "").strip().lower()
        if category:
            if category not in ALL_CATEGORIES:
                return Response(
                    {
                        "detail": (
                            "category must be one of "
                            + ", ".join(ALL_CATEGORIES)
                            + "."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Filter — text query (case-insensitive against the ``text``
        # column only — payload bodies are never substring-searched
        # because the payload is sanitised at serialise time).
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(text__icontains=q[:120])

        # Filter — date range. We never extrapolate; missing values
        # leave the side of the range open.
        date_from = self._parse_date(request.query_params.get("date_from"))
        if date_from is not None:
            qs = qs.filter(occurred_at__gte=date_from)
        date_to = self._parse_date(request.query_params.get("date_to"))
        if date_to is not None:
            qs = qs.filter(occurred_at__lte=date_to)

        # Pagination (hard cap so a malformed ``limit`` cannot drain
        # the audit table).
        try:
            limit = min(
                int(request.query_params.get("limit") or self._DEFAULT_LIMIT),
                self._MAX_LIMIT,
            )
        except (TypeError, ValueError):
            limit = self._DEFAULT_LIMIT
        if limit <= 0:
            limit = self._DEFAULT_LIMIT
        try:
            offset = max(int(request.query_params.get("offset") or 0), 0)
        except (TypeError, ValueError):
            offset = 0

        # Secondary order-by -id so SQLite millisecond ties resolve
        # deterministically (Phase 15A precedent).
        qs = qs.order_by("-occurred_at", "-id")

        if category:
            # Category filter is prefix-derived — drain the queryset
            # under a hard cap so we never iterate the whole table.
            # We over-fetch (limit + offset) * 4 then page in Python.
            window = (limit + offset) * 4
            if window > self._MAX_LIMIT * 8:
                window = self._MAX_LIMIT * 8
            window = max(window, limit + offset)
            candidates = list(qs[:window])
            filtered = [e for e in candidates if categorize_kind(e.kind) == category]
            total = len(filtered)
            page = filtered[offset : offset + limit]
            items = [self._serialize_event(event) for event in page]
            return Response(
                {
                    "items": items,
                    "count": total,
                    "limit": limit,
                    "offset": offset,
                    "categoriesAvailable": list(ALL_CATEGORIES),
                    "categoryFiltered": category,
                }
            )

        total = qs.count()
        page = qs[offset : offset + limit]
        items = [self._serialize_event(event) for event in page]
        return Response(
            {
                "items": items,
                "count": total,
                "limit": limit,
                "offset": offset,
                "categoriesAvailable": list(ALL_CATEGORIES),
                "categoryFiltered": None,
            }
        )

    # Explicit 405 on writes — DRF default would return 405 anyway
    # because we only define ``get``, but we want the contract clear
    # in tests and code review.
    def post(self, request):  # noqa: ARG002
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def put(self, request):  # noqa: ARG002
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def patch(self, request):  # noqa: ARG002
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def delete(self, request):  # noqa: ARG002
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
