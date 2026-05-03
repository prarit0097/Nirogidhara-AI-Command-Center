"""Phase 6L — Razorpay Test Execution Audit Review + Webhook Readiness Plan.

Strictly read-only / planning-only. NEVER calls Razorpay, NEVER
mutates DB rows, NEVER returns raw secrets, NEVER includes raw
provider response, NEVER includes customer data.

Three concerns:

1. **Audit review** — given a Phase 6K
   :class:`apps.saas.models.RuntimeProviderExecutionAttempt`, replay
   the safety invariants from the row + the AuditEvent ledger and
   return a typed PASS / FAIL report.

2. **Webhook readiness** — read-only env presence + Phase 6K artefact
   sanity check that tells the operator whether a Phase 6L webhook
   readiness plan can be authored.

3. **Webhook readiness plan** — pure policy doc returned as JSON. It
   defines the future Razorpay webhook receiver design (signature
   verification, idempotency, event allow/deny lists, replay window,
   audit logging) WITHOUT registering a webhook receiver. Phase 6L
   ships planning only — Phase 6M will own a real webhook handler.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

from django.db.models import QuerySet

from apps.audit.models import AuditEvent

from .models import RuntimeProviderExecutionAttempt
from .razorpay_test_execution import (
    inspect_razorpay_test_env,
    mask_razorpay_key_id,
)


PHASE_6L_WARNING = (
    "Phase 6L is read-only audit + webhook planning. NEVER calls "
    "Razorpay, NEVER mutates business records, NEVER exposes raw "
    "secrets."
)

# Audit kinds emitted by Phase 6K that the review reads.
PHASE_6K_AUDIT_KINDS: tuple[str, ...] = (
    "runtime.provider_execution.prepared",
    "runtime.provider_execution.blocked",
    "runtime.provider_execution.started",
    "runtime.provider_execution.succeeded",
    "runtime.provider_execution.failed",
    "runtime.provider_execution.rolled_back",
    "runtime.provider_execution.archived",
    "runtime.provider_execution.invariant_violation_blocked",
)

# Allowed Phase 6L event types — nothing else may flow through the
# future webhook receiver.
WEBHOOK_EVENT_ALLOWLIST: tuple[str, ...] = (
    "order.paid",
    "order.notification.delivered",
    "order.notification.failed",
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "refund.created",
    "refund.processed",
    "refund.failed",
)

# Explicit deny — even if Razorpay invents a new event we don't yet
# understand, these are HARD refused.
WEBHOOK_EVENT_DENYLIST: tuple[str, ...] = (
    "subscription.activated",
    "subscription.cancelled",
    "subscription.charged",
    "settlement.processed",
    "virtual_account.credited",
    "qr_code.credited",
    "fund_account.validation.completed",
    "payout.processed",
    "payout.failed",
)

# Sensitive payload key parts — if any of these names show up in a
# webhook event payload we refuse to log the full body and instead
# log only the keys present (for forensic awareness).
SENSITIVE_PAYLOAD_KEYS: tuple[str, ...] = (
    "card",
    "vpa",
    "upi",
    "bank_account",
    "wallet",
    "email",
    "contact",
    "customer_id",
    "customer",
    "phone",
    "mobile",
    "address",
)


# ---------------------------------------------------------------------------
# Audit review
# ---------------------------------------------------------------------------


_REQUIRED_INVARIANT_CHECKS: tuple[tuple[str, str, bool], ...] = (
    # (label, attribute, expected)
    ("providerCallAttempted", "provider_call_attempted", True),
    ("externalCallWasMade", "external_call_was_made", True),
    ("businessMutationWasMade", "business_mutation_was_made", False),
    ("paymentLinkCreated", "payment_link_created", False),
    ("paymentCaptured", "payment_captured", False),
    ("customerNotificationSent", "customer_notification_sent", False),
    ("realMoney", "real_money", False),
    ("realCustomerDataAllowed", "real_customer_data_allowed", False),
)


def _safe_audit_event(event: AuditEvent) -> dict[str, Any]:
    """Reduce an AuditEvent to a non-leaking summary."""
    return {
        "id": event.id,
        "kind": event.kind,
        "tone": event.tone,
        "createdAt": event.occurred_at.isoformat(),
        "text": event.text,
        # Keys only — payload values may carry useful signal but never
        # raw secrets / raw provider response (Phase 6K already
        # asserted this; we double-check by listing keys here).
        "payloadKeys": sorted(list((event.payload or {}).keys())),
    }


def _audit_events_for_execution(
    execution_id: str,
) -> list[AuditEvent]:
    qs: QuerySet[AuditEvent] = AuditEvent.objects.filter(
        kind__in=PHASE_6K_AUDIT_KINDS,
    ).order_by("occurred_at")
    matched: list[AuditEvent] = []
    for event in qs:
        payload = event.payload or {}
        if str(payload.get("execution_id") or "") == execution_id:
            matched.append(event)
    return matched


def _scan_for_raw_secret(blob: str, key_id: str) -> bool:
    """Cheap structural check — refuses any literal raw-key occurrence.

    The Phase 6K models / audit emits only masked references; this
    function exists so the audit review can flag a regression if a
    future code path leaks the raw env value.
    """
    if not blob or not key_id:
        return False
    return key_id in blob


def review_razorpay_test_execution_audit(
    execution_id: str,
) -> dict[str, Any]:
    """Read-only review of one Phase 6K execution attempt + its audit
    trail. Returns a typed PASS / FAIL report. NEVER calls Razorpay.
    """
    attempt = (
        RuntimeProviderExecutionAttempt.objects.filter(
            execution_id=execution_id
        )
        .select_related("plan", "organization")
        .first()
    )
    if attempt is None:
        return {
            "passed": False,
            "executionId": execution_id,
            "errors": [f"Execution attempt not found: {execution_id}"],
            "blockers": [f"execution_attempt_not_found_{execution_id}"],
            "warnings": [PHASE_6L_WARNING],
            "nextAction": "verify_execution_id_or_run_phase_6k_again",
        }

    invariant_results: list[dict[str, Any]] = []
    failed: list[str] = []
    for label, attr, expected in _REQUIRED_INVARIANT_CHECKS:
        actual = getattr(attempt, attr)
        ok = actual == expected
        invariant_results.append(
            {"key": label, "expected": expected, "actual": actual, "passed": ok}
        )
        if not ok:
            failed.append(f"{label}_expected_{expected}_got_{actual}")

    rollback_ok = (
        attempt.rollback_status
        == RuntimeProviderExecutionAttempt.RollbackStatus.COMPLETED
    )
    if not rollback_ok:
        failed.append(
            f"rollback_status_must_be_completed_was_{attempt.rollback_status}"
        )
    invariant_results.append(
        {
            "key": "rollbackStatus",
            "expected": "completed",
            "actual": attempt.rollback_status,
            "passed": rollback_ok,
        }
    )

    provider_object_ok = bool(attempt.provider_object_id)
    if not provider_object_ok:
        failed.append("provider_object_id_missing")
    invariant_results.append(
        {
            "key": "providerObjectIdPresent",
            "expected": True,
            "actual": provider_object_ok,
            "passed": provider_object_ok,
        }
    )

    audit_rows = _audit_events_for_execution(execution_id)
    safe_audit_events = [_safe_audit_event(e) for e in audit_rows]

    # Defence-in-depth: scan every audit row's text + payload for the
    # live RAZORPAY_KEY_ID. If anything matches, the report fails.
    raw_key = os.environ.get("RAZORPAY_KEY_ID") or ""
    raw_secret = os.environ.get("RAZORPAY_KEY_SECRET") or ""
    leak_blob = " ".join(
        [
            *[(e.text or "") for e in audit_rows],
            *[
                str(v)
                for e in audit_rows
                for v in (e.payload or {}).values()
            ],
        ]
    )
    raw_key_leaked = _scan_for_raw_secret(leak_blob, raw_key)
    raw_secret_leaked = _scan_for_raw_secret(leak_blob, raw_secret)
    if raw_key_leaked:
        failed.append("raw_razorpay_key_id_leaked_in_audit")
    if raw_secret_leaked:
        failed.append("raw_razorpay_key_secret_leaked_in_audit")

    # Phase 6K should only have written safe summary fields; the
    # safe_response_summary must never include un-whitelisted keys.
    response_keys = sorted(
        list((attempt.safe_response_summary or {}).keys())
    )
    allowed_response_keys = {"id", "status", "amount", "currency", "receipt"}
    extra_keys = [
        k for k in response_keys if k not in allowed_response_keys
    ]
    if extra_keys:
        # ``error`` / ``errorClass`` are allowed only for the FAILED
        # status; any other extra key is an audit failure.
        if attempt.status == RuntimeProviderExecutionAttempt.Status.FAILED:
            extra_keys = [
                k for k in extra_keys if k not in {"error", "errorClass"}
            ]
        if extra_keys:
            failed.append(
                f"safe_response_summary_has_unexpected_keys_{','.join(extra_keys)}"
            )

    passed = not failed
    next_action = (
        "ready_for_phase_6l_webhook_readiness_planning"
        if passed
        else "fix_phase_6k_audit_review_blockers"
    )

    env = inspect_razorpay_test_env()

    return {
        "passed": passed,
        "executionId": execution_id,
        "planId": attempt.plan.plan_id if attempt.plan_id else "",
        "providerType": attempt.provider_type,
        "operationType": attempt.operation_type,
        "providerEnvironment": attempt.provider_environment,
        "status": attempt.status,
        "providerObjectId": attempt.provider_object_id,
        "providerStatus": attempt.provider_status,
        "amountPaise": attempt.amount_paise,
        "currency": attempt.currency,
        "rollbackStatus": attempt.rollback_status,
        "envSnapshot": {
            "envFlagEnabled": env["envFlagEnabled"],
            "razorpayKeyMode": env["razorpayKeyMode"],
            "razorpayKeyIdMasked": env["razorpayKeyIdMasked"],
            "razorpayWebhookSecretPresent": env[
                "razorpayWebhookSecretPresent"
            ],
        },
        "invariantResults": invariant_results,
        "auditEventCount": len(audit_rows),
        "auditEvents": safe_audit_events,
        "safeResponseSummary": attempt.safe_response_summary or {},
        "rawSecretLeakDetected": (raw_key_leaked or raw_secret_leaked),
        "blockers": failed,
        "warnings": [PHASE_6L_WARNING],
        "nextAction": next_action,
    }


# ---------------------------------------------------------------------------
# Webhook readiness
# ---------------------------------------------------------------------------


def _latest_succeeded_attempt() -> Optional[RuntimeProviderExecutionAttempt]:
    """Latest attempt that DID succeed at some point — including
    rolled-back successes (rollback transitions status away from
    SUCCEEDED but the provider call already happened)."""
    return (
        RuntimeProviderExecutionAttempt.objects.filter(
            provider_type="razorpay",
            operation_type="razorpay.create_order",
            provider_call_attempted=True,
            external_call_was_made=True,
        )
        .exclude(provider_object_id="")
        .order_by("-executed_at", "-created_at")
        .first()
    )


def _latest_phase_6k_artefact() -> Optional[RuntimeProviderExecutionAttempt]:
    """Latest Razorpay artefact (any status) — used to anchor planning."""
    return (
        RuntimeProviderExecutionAttempt.objects.filter(
            provider_type="razorpay",
            operation_type="razorpay.create_order",
        )
        .order_by("-executed_at", "-created_at")
        .first()
    )


def inspect_razorpay_webhook_readiness() -> dict[str, Any]:
    """Read-only env + Phase 6K artefact sanity check.

    Reports presence of ``RAZORPAY_WEBHOOK_SECRET`` (boolean ONLY —
    never the value), Razorpay key mode (test/live/missing), the
    latest Phase 6K succeeded execution + its provider order id, and
    a typed ``nextAction``. NEVER calls Razorpay; NEVER returns the
    raw secret value.
    """
    env = inspect_razorpay_test_env()
    latest_success = _latest_succeeded_attempt()
    latest_attempt = _latest_phase_6k_artefact()

    blockers: list[str] = []
    warnings: list[str] = [PHASE_6L_WARNING]
    if not env["razorpayWebhookSecretPresent"]:
        blockers.append("razorpay_webhook_secret_missing")
    if env["isLiveKey"]:
        blockers.append("razorpay_key_id_is_live_key_phase_6l_blocked")
    if not env["isTestKey"]:
        blockers.append("razorpay_key_id_must_be_test_mode_for_phase_6l")
    if latest_success is None:
        blockers.append("no_phase_6k_succeeded_execution_found")
    if (
        latest_success is not None
        and latest_success.rollback_status
        != RuntimeProviderExecutionAttempt.RollbackStatus.COMPLETED
    ):
        warnings.append(
            "latest_phase_6k_execution_not_yet_rolled_back; consider running "
            "rollback_single_provider_execution_attempt before authoring the "
            "Phase 6L webhook plan."
        )

    safe_to_plan_webhook = not blockers

    return {
        "razorpayKeyMode": env["razorpayKeyMode"],
        "razorpayKeyIdMasked": env["razorpayKeyIdMasked"],
        "razorpayKeyIdPresent": env["razorpayKeyIdPresent"],
        "razorpayKeySecretPresent": env["razorpayKeySecretPresent"],
        "razorpayWebhookSecretPresent": env["razorpayWebhookSecretPresent"],
        "envFlagEnabled": env["envFlagEnabled"],
        "isTestKey": env["isTestKey"],
        "isLiveKey": env["isLiveKey"],
        "latestSucceededExecutionId": (
            latest_success.execution_id if latest_success else None
        ),
        "latestSucceededProviderObjectId": (
            latest_success.provider_object_id if latest_success else None
        ),
        "latestSucceededRollbackStatus": (
            latest_success.rollback_status if latest_success else None
        ),
        "latestPhase6KArtefactExecutionId": (
            latest_attempt.execution_id if latest_attempt else None
        ),
        "phase6KSucceededExecutionCount": (
            RuntimeProviderExecutionAttempt.objects.filter(
                status=RuntimeProviderExecutionAttempt.Status.SUCCEEDED
            ).count()
        ),
        "blockers": blockers,
        "warnings": warnings,
        "safeToPlanWebhookReadiness": safe_to_plan_webhook,
        "nextAction": (
            "ready_to_plan_razorpay_webhook_readiness"
            if safe_to_plan_webhook
            else "fix_razorpay_webhook_readiness_blockers"
        ),
    }


# ---------------------------------------------------------------------------
# Webhook readiness plan (pure policy)
# ---------------------------------------------------------------------------


def plan_razorpay_webhook_readiness() -> dict[str, Any]:
    """Return the canonical Phase 6L Razorpay webhook readiness plan.

    Pure policy data. Composes the env readiness snapshot + the
    locked design constants (allow / deny list, signature design,
    idempotency design, replay window, audit logging plan, test-mode
    constraint). NEVER returns the raw webhook secret value. NEVER
    activates a webhook receiver.
    """
    readiness = inspect_razorpay_webhook_readiness()
    return {
        "phase": "6L",
        "policyVersion": "phase6l.v1",
        "summary": (
            "Phase 6L Razorpay webhook readiness plan. Test-mode only. "
            "No payment / order status mutation in Phase 6L. The actual "
            "webhook handler ships in Phase 6M."
        ),
        "preconditions": {
            "razorpayWebhookSecretMustBePresent": True,
            "razorpayKeyMustBeTestMode": True,
            "phase6KExecutionMustExist": True,
            "phase6KSucceededExecutionMustBeRolledBack": False,
        },
        "envReadiness": readiness,
        "endpointDesign": {
            "path": "/api/webhooks/razorpay/test/",
            "method": "POST",
            "csrfExempt": True,
            "authentication": "none (Razorpay-IP allowlist + signature)",
            "phase6LRegistration": False,
            "phase6MRegistration": True,
        },
        "signatureVerificationDesign": {
            "algorithm": "HMAC-SHA256",
            "secretSource": "env: RAZORPAY_WEBHOOK_SECRET",
            "header": "X-Razorpay-Signature",
            "rawBodyMustBeUsed": True,
            "constantTimeCompare": True,
            "rejectOnMissingHeader": True,
            "rejectOnEmptySecret": True,
            "implementationReference": (
                "apps.payments.integrations.razorpay_client.verify_webhook_signature"
            ),
        },
        "idempotencyDesign": {
            "key": "x_razorpay_event_id",
            "fallbackKey": "sha256(rawBody)",
            "storage": "RuntimeWebhookEvent (Phase 6M model — not yet created)",
            "uniqueConstraint": True,
            "duplicateBehaviour": (
                "ignore_with_audit_log; never re-mutate"
            ),
        },
        "eventAllowlist": list(WEBHOOK_EVENT_ALLOWLIST),
        "eventDenylist": list(WEBHOOK_EVENT_DENYLIST),
        "replayProtection": {
            "windowSeconds": 300,
            "rejectOlderThanWindow": True,
            "useEventCreatedAt": True,
            "audit": "runtime.razorpay_webhook.replay_rejected",
        },
        "auditLoggingPlan": {
            "kindsToAdd": [
                "runtime.razorpay_webhook.received",
                "runtime.razorpay_webhook.signature_failed",
                "runtime.razorpay_webhook.duplicate_ignored",
                "runtime.razorpay_webhook.replay_rejected",
                "runtime.razorpay_webhook.event_allowed",
                "runtime.razorpay_webhook.event_denied",
                "runtime.razorpay_webhook.processed",
                "runtime.razorpay_webhook.failed",
            ],
            "phase6LAuditMutationAllowed": False,
            "phase6MAuditMutationAllowed": True,
            "payloadHandling": {
                "storeRawBody": False,
                "storePayloadHash": True,
                "storePayloadKeysOnly": True,
                "sensitiveKeysToScrub": list(SENSITIVE_PAYLOAD_KEYS),
            },
        },
        "testModeOnlyValidationPlan": {
            "razorpayKeyModeMustBeTest": True,
            "envFlagPattern": "PHASE6M_RAZORPAY_WEBHOOK_TEST_MODE_ENABLED",
            "phase6MWebhookHandlerEnabledByDefault": False,
            "phase6MMaxEventsPerRun": 50,
            "phase6MEventCanMutateBusinessTables": False,
        },
        "businessMutationPolicy": {
            "phase6LAllowOrderUpdate": False,
            "phase6LAllowPaymentUpdate": False,
            "phase6LAllowShipmentUpdate": False,
            "phase6LAllowDiscountOfferUpdate": False,
            "phase6LAllowCustomerNotification": False,
        },
        "blockers": readiness["blockers"],
        "warnings": readiness["warnings"],
        "nextAction": (
            "ready_for_phase_6m_razorpay_webhook_handler_implementation"
            if readiness["safeToPlanWebhookReadiness"]
            else "fix_razorpay_webhook_readiness_blockers"
        ),
        "nextPhase": (
            "phase_6m_razorpay_webhook_handler_implementation_test_mode"
        ),
    }


__all__ = (
    "PHASE_6L_WARNING",
    "PHASE_6K_AUDIT_KINDS",
    "WEBHOOK_EVENT_ALLOWLIST",
    "WEBHOOK_EVENT_DENYLIST",
    "SENSITIVE_PAYLOAD_KEYS",
    "review_razorpay_test_execution_audit",
    "inspect_razorpay_webhook_readiness",
    "plan_razorpay_webhook_readiness",
)
