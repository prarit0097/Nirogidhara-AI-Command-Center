"""Phase 6N — Razorpay Webhook Business-Mutation Sandbox Plan.

Strictly planning / readiness only. Phase 6N never:

- calls Razorpay,
- mutates ``Order`` / ``Payment`` / ``Shipment`` / ``DiscountOfferLog``,
- sends customer notifications,
- creates payment links, captures, or refunds,
- changes ``.env`` or any feature flag,
- enables MCP.

It defines the policy, eligibility, manual-review checklist, rollback
plan, safety invariants, audit plan, and read-only readiness signal
that a future Phase 6O implementation must respect.

Public service surface (all read-only, JSON-shaped):

- :func:`get_razorpay_business_mutation_sandbox_plan`
- :func:`inspect_razorpay_business_mutation_sandbox_readiness`
- :func:`build_razorpay_event_status_mapping_plan`
- :func:`build_synthetic_order_eligibility_policy`
- :func:`build_phase6n_manual_review_checklist`
- :func:`build_phase6n_rollback_plan`
- :func:`validate_phase6n_no_mutation_invariants`
"""
from __future__ import annotations

from typing import Any

from apps.payments.razorpay_webhook_readiness import (
    get_razorpay_webhook_handler_readiness,
)


PHASE_6N_WARNING = (
    "Phase 6N is planning-only. NEVER calls Razorpay, NEVER mutates "
    "Order / Payment / Shipment / DiscountOfferLog, NEVER notifies a "
    "customer, NEVER changes env flags. The next phase (Phase 6O) "
    "may introduce sandbox-only mutation against synthetic test "
    "orders behind a NEW env flag, gated by Director sign-off."
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


PHASE_6N_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "call_razorpay_api",
    "create_razorpay_payment_link",
    "capture_razorpay_payment",
    "refund_razorpay_payment",
    "mutate_order_status",
    "mutate_payment_status",
    "create_or_update_shipment",
    "create_or_update_discount_offer",
    "send_whatsapp_template",
    "send_freeform_whatsapp",
    "place_vapi_call",
    "enable_business_mutation_env_flag",
    "enable_customer_notification_env_flag",
    "enable_raw_payload_storage_env_flag",
    "store_full_pii",
    "store_raw_webhook_secret",
    "execute_phase_6n_via_frontend",
)


# Required environment defaults — Phase 6N must NEVER flip any of these.
PHASE_6N_REQUIRED_ENV_DEFAULTS: dict[str, bool] = {
    "RAZORPAY_WEBHOOK_TEST_MODE_ENABLED": False,
    "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED": False,
    "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED": False,
    "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD": False,
}


# Audit kinds Phase 6N may emit. CLI-only; payloads carry no secrets.
PHASE_6N_AUDIT_KINDS: tuple[str, ...] = (
    "razorpay.sandbox_plan.inspected",
    "razorpay.sandbox_readiness.inspected",
)


# ---------------------------------------------------------------------------
# Event-to-status mapping plan
# ---------------------------------------------------------------------------


_EVENT_PLAN: tuple[dict[str, Any], ...] = (
    {
        "razorpayEventName": "payment_link.paid",
        "futureSandboxPaymentStatus": "paid",
        "futureSandboxOrderEffect": "advance_received",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only acknowledgement of an advance payment on a "
            "synthetic test payment link. Phase 6O may flip the "
            "synthetic Order's advance flag; production rows stay "
            "untouched."
        ),
    },
    {
        "razorpayEventName": "payment.captured",
        "futureSandboxPaymentStatus": "captured",
        "futureSandboxOrderEffect": "fully_paid",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only capture confirmation against a synthetic "
            "test order. Customer notification stays disabled."
        ),
    },
    {
        "razorpayEventName": "payment.failed",
        "futureSandboxPaymentStatus": "failed",
        "futureSandboxOrderEffect": "no_change",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only payment-failure logging. No retry, no "
            "customer message, no order-status change."
        ),
    },
    {
        "razorpayEventName": "payment.authorized",
        "futureSandboxPaymentStatus": "authorized",
        "futureSandboxOrderEffect": "advance_authorized",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only authorization acknowledgement. Capture is "
            "still gated by manual review in Phase 6O."
        ),
    },
    {
        "razorpayEventName": "order.paid",
        "futureSandboxPaymentStatus": "captured",
        "futureSandboxOrderEffect": "fully_paid",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only confirmation that a synthetic Razorpay "
            "Order is paid in full. Phase 6O implementation must "
            "verify the order id is on the synthetic allowlist."
        ),
    },
    {
        "razorpayEventName": "payment_link.cancelled",
        "futureSandboxPaymentStatus": "cancelled",
        "futureSandboxOrderEffect": "advance_cancelled",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only cancellation log. Customer is never "
            "notified by Phase 6O code paths."
        ),
    },
    {
        "razorpayEventName": "payment_link.expired",
        "futureSandboxPaymentStatus": "expired",
        "futureSandboxOrderEffect": "advance_expired",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only expiry log. No automatic re-issue of a "
            "payment link in Phase 6O."
        ),
    },
    {
        "razorpayEventName": "refund.created",
        "futureSandboxPaymentStatus": "refund_pending",
        "futureSandboxOrderEffect": "no_change",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only refund-created log. Phase 6O must wait for "
            "refund.processed before flipping any sandbox status."
        ),
    },
    {
        "razorpayEventName": "refund.processed",
        "futureSandboxPaymentStatus": "refunded",
        "futureSandboxOrderEffect": "advance_refunded",
        "manualReviewRequired": True,
        "notes": (
            "Sandbox-only refund-processed acknowledgement. Phase 6O "
            "must NEVER call the Razorpay refunds API; it only reads "
            "what Razorpay reports via webhook."
        ),
    },
)


def _event_mapping_row(spec: dict[str, Any]) -> dict[str, Any]:
    """Wrap each event spec with locked safety booleans + blocker hints."""
    return {
        "razorpayEventName": spec["razorpayEventName"],
        "futureSandboxPaymentStatus": spec["futureSandboxPaymentStatus"],
        "futureSandboxOrderEffect": spec["futureSandboxOrderEffect"],
        "mutationAllowedInPhase6N": False,
        "mutationAllowedInFuturePhase6O": "only_if_synthetic_and_approved",
        "manualReviewRequired": bool(spec.get("manualReviewRequired", True)),
        "customerNotificationAllowed": False,
        "shipmentEffectAllowed": False,
        "discountEffectAllowed": False,
        "idempotencyRequired": True,
        "rollbackRequired": True,
        "blockers": [
            "phase_6n_planning_only_no_mutation_path",
            "phase_6o_must_supply_synthetic_order_resolver",
            "phase_6o_must_supply_director_approval_record",
        ],
        "notes": spec["notes"],
    }


def build_razorpay_event_status_mapping_plan() -> list[dict[str, Any]]:
    """Return the canonical Phase 6N event-to-status mapping plan."""
    return [_event_mapping_row(spec) for spec in _EVENT_PLAN]


# ---------------------------------------------------------------------------
# Synthetic-order eligibility policy
# ---------------------------------------------------------------------------


def build_synthetic_order_eligibility_policy() -> dict[str, Any]:
    return {
        "providerEnvironmentMustBeTest": True,
        "razorpayKeyModeMustBeTest": True,
        "eventMustComeFromPhase6MVerifiedHandler": True,
        "sourceEventIdRequired": True,
        "signatureValidRequired": True,
        "replayWindowValidRequired": True,
        "idempotencyFirstSeenRequired": True,
        "eventMustBeAllowlisted": True,
        "eventMustNotBeDenylisted": True,
        "orderPaymentPaymentLinkReferenceMustBeSynthetic": True,
        "noRealCustomerData": True,
        "noFullPhoneEmailAddressInPayload": True,
        "noCustomerNotification": True,
        "noShipmentCreation": True,
        "noDiscountMutation": True,
        "manualReviewBeforeMutation": True,
        "rollbackPathDefined": True,
        "auditRequiredBeforeAndAfterFutureMutation": True,
        "syntheticReferencePrefixes": [
            "phase6j_internal_test_plan_",
            "phase6n_sandbox_synthetic_",
        ],
        "syntheticOrderResolverPlannedFor": "phase_6o",
        "phase6OMustRefuseIfAnyConditionFails": True,
        "phase6NMustNotInvokeAnyOfThese": True,
    }


# ---------------------------------------------------------------------------
# Manual-review checklist
# ---------------------------------------------------------------------------


def build_phase6n_manual_review_checklist() -> list[dict[str, Any]]:
    return [
        {
            "key": "verifyPhase6MHandlerSafetyCountersZero",
            "description": (
                "Confirm `business_mutation_count` and "
                "`customer_notification_count` are 0 across every "
                "RazorpayWebhookEvent before authoring Phase 6O."
            ),
            "automated": True,
        },
        {
            "key": "verifyEnvFlagsLockedOff",
            "description": (
                "Confirm RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED, "
                "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED, and "
                "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD are all `false` "
                "in `.env.production`."
            ),
            "automated": True,
        },
        {
            "key": "verifyTestKeyMode",
            "description": (
                "Razorpay key id must start with `rzp_test`. Live "
                "credentials disqualify Phase 6N — and Phase 6O — "
                "regardless of any other flag state."
            ),
            "automated": True,
        },
        {
            "key": "verifySyntheticReferenceOnly",
            "description": (
                "Every webhook event reviewed for Phase 6O sandbox "
                "rehearsal must reference a synthetic order id (see "
                "`syntheticReferencePrefixes`). Real production "
                "order ids must be refused."
            ),
            "automated": False,
        },
        {
            "key": "verifyNoFullPiiInPayload",
            "description": (
                "Payload-keys-only audit must not expose card, "
                "vpa, upi, bank, wallet, email, phone, mobile, "
                "address, or customer fields."
            ),
            "automated": True,
        },
        {
            "key": "verifyDirectorSignOff",
            "description": (
                "Written Director sign-off recorded in the Master "
                "Event Ledger before any Phase 6O sandbox mutation "
                "is rehearsed."
            ),
            "automated": False,
        },
        {
            "key": "verifyRollbackDryRun",
            "description": (
                "Rollback dry-run executed in Phase 6O implementation "
                "before any sandbox mutation is committed (per the "
                "rollback plan below)."
            ),
            "automated": False,
        },
        {
            "key": "verifyDocsSyncedThroughPhase6N",
            "description": (
                "nd.md, MASTER_BLUEPRINT_V2.md, BACKEND_API.md, "
                "RUNBOOK.md, and FUTURE_BACKEND_PLAN.md reflect "
                "Phase 6N status before Phase 6O begins."
            ),
            "automated": False,
        },
    ]


# ---------------------------------------------------------------------------
# Rollback plan
# ---------------------------------------------------------------------------


def build_phase6n_rollback_plan() -> dict[str, Any]:
    return {
        "phase": "6N",
        "rollbackTriggers": [
            "any_real_order_payment_shipment_or_discount_mutation_observed",
            "any_customer_notification_observed",
            "raw_secret_or_full_pii_exposure_observed",
            "razorpay_live_key_detected_in_phase_6m_handler_path",
            "manual_review_checklist_failure",
            "director_revokes_sandbox_authorization",
        ],
        "rollbackSteps": [
            {
                "order": 1,
                "action": "set_RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED_to_false",
                "owner": "operator",
                "phase6NEnforced": True,
            },
            {
                "order": 2,
                "action": "set_RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED_to_false",
                "owner": "operator",
                "phase6NEnforced": True,
            },
            {
                "order": 3,
                "action": "recreate_backend_worker_beat_containers_to_pickup_envs",
                "owner": "operator",
                "phase6NEnforced": False,
            },
            {
                "order": 4,
                "action": "run_inspect_razorpay_webhook_handler_readiness_to_confirm_locked",
                "owner": "operator",
                "phase6NEnforced": True,
            },
            {
                "order": 5,
                "action": "audit_recent_RazorpayWebhookEvent_rows_for_safety_counter_drift",
                "owner": "operator",
                "phase6NEnforced": True,
            },
            {
                "order": 6,
                "action": "if_any_synthetic_sandbox_row_was_created_in_phase_6o_mark_status=rolled_back",
                "owner": "phase_6o_implementation",
                "phase6NEnforced": False,
            },
            {
                "order": 7,
                "action": "write_audit_event_kind_razorpay_sandbox_readiness_inspected_with_rollback_reason",
                "owner": "operator",
                "phase6NEnforced": True,
            },
        ],
        "rollbackVerification": [
            "RAZORPAY_WEBHOOK_BUSINESS_MUTATION_ENABLED == false",
            "RAZORPAY_WEBHOOK_NOTIFY_CUSTOMER_ENABLED == false",
            "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD == false",
            "every RazorpayWebhookEvent.business_mutation_was_made == false",
            "every RazorpayWebhookEvent.customer_notification_sent == false",
            "every RazorpayWebhookEvent.raw_secret_exposed == false",
            "every RazorpayWebhookEvent.full_pii_exposed == false",
        ],
        "phase6NCanExecuteRollback": False,
        "rollbackOwnedByOperatorOnly": True,
        "rollbackNeverInvokesProviderApi": True,
    }


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


def _safety_invariants() -> dict[str, Any]:
    return {
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "rawPayloadStorageEnabled": False,
        "providerCallAllowed": False,
        "razorpayApiInvocationAllowed": False,
        "whatsappSendAllowed": False,
        "vapiCallAllowed": False,
        "envFlagFlipAllowed": False,
        "phase6NPathCanMutateProductionRecord": False,
        "phase6NPathCanCreateShipment": False,
        "phase6NPathCanCreateDiscountOffer": False,
        "phase6NPathCanSendCustomerNotification": False,
        "phase6NPathCanCallRazorpay": False,
        "phase6NPathCanFlipEnvFlag": False,
        "phase6NPathCanMutateAuditEventPayload": False,
        "phase6NPathCanWriteToRazorpayWebhookEvent": False,
        "phase6NPathRespectsKillSwitch": True,
    }


def validate_phase6n_no_mutation_invariants(
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure assertion that the composed plan has no mutation paths.

    Returns a typed report. Never raises; tests use this to prove the
    composed plan body itself never declares a mutation-allowed flag.
    """
    plan = plan or get_razorpay_business_mutation_sandbox_plan()
    failures: list[str] = []

    if plan.get("businessMutationEnabled") is not False:
        failures.append("business_mutation_enabled_flag_must_be_false")
    if plan.get("customerNotificationEnabled") is not False:
        failures.append("customer_notification_enabled_flag_must_be_false")
    if plan.get("rawPayloadStorageEnabled") is not False:
        failures.append("raw_payload_storage_enabled_flag_must_be_false")

    invariants = plan.get("safetyInvariants") or {}
    for key, expected in _safety_invariants().items():
        if invariants.get(key) is not expected:
            failures.append(f"safety_invariant_{key}_must_be_{expected}")

    for row in plan.get("eventMappings") or []:
        name = row.get("razorpayEventName") or "unknown"
        if row.get("mutationAllowedInPhase6N") is not False:
            failures.append(
                f"event_{name}_mutation_allowed_in_phase_6n_must_be_false"
            )
        if row.get("customerNotificationAllowed") is not False:
            failures.append(
                f"event_{name}_customer_notification_allowed_must_be_false"
            )
        if row.get("shipmentEffectAllowed") is not False:
            failures.append(f"event_{name}_shipment_effect_must_be_false")
        if row.get("discountEffectAllowed") is not False:
            failures.append(f"event_{name}_discount_effect_must_be_false")
        if row.get("idempotencyRequired") is not True:
            failures.append(f"event_{name}_idempotency_required_must_be_true")
        if row.get("rollbackRequired") is not True:
            failures.append(f"event_{name}_rollback_required_must_be_true")

    rollback = plan.get("rollbackPlan") or {}
    if rollback.get("phase6NCanExecuteRollback") is not False:
        failures.append("phase_6n_must_not_execute_rollback_directly")
    if rollback.get("rollbackNeverInvokesProviderApi") is not True:
        failures.append("rollback_never_invokes_provider_api")

    return {
        "passed": not failures,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Readiness composition
# ---------------------------------------------------------------------------


def _phase_6m_safety_signal() -> dict[str, Any]:
    """Pull the Phase 6M handler readiness counters without asserting."""
    try:
        return get_razorpay_webhook_handler_readiness()
    except Exception as exc:  # pragma: no cover — defensive
        return {
            "phase": "6M",
            "businessMutationCount": -1,
            "customerNotificationCount": -1,
            "rawSecretExposureCount": -1,
            "fullPiiExposureCount": -1,
            "verifiedEventCount": 0,
            "safeToReceiveTestWebhooks": False,
            "safeToStartPhase6N": False,
            "blockers": [f"phase_6m_readiness_lookup_failed:{exc.__class__.__name__}"],
            "warnings": [],
            "nextAction": "fix_phase_6m_readiness_lookup",
        }


def _phase_6n_blockers(phase_6m: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if phase_6m.get("businessMutationEnabled"):
        blockers.append("phase_6m_business_mutation_flag_must_remain_disabled")
    if phase_6m.get("customerNotificationEnabled"):
        blockers.append(
            "phase_6m_customer_notification_flag_must_remain_disabled"
        )
    if phase_6m.get("storeRawPayload"):
        blockers.append(
            "phase_6m_store_raw_payload_flag_must_remain_disabled"
        )
    if (phase_6m.get("businessMutationCount") or 0) > 0:
        blockers.append(
            "phase_6m_business_mutation_count_observed_must_be_zero"
        )
    if (phase_6m.get("customerNotificationCount") or 0) > 0:
        blockers.append(
            "phase_6m_customer_notification_count_observed_must_be_zero"
        )
    if (phase_6m.get("rawSecretExposureCount") or 0) > 0:
        blockers.append(
            "phase_6m_raw_secret_exposure_observed_must_be_zero"
        )
    if (phase_6m.get("fullPiiExposureCount") or 0) > 0:
        blockers.append(
            "phase_6m_full_pii_exposure_observed_must_be_zero"
        )
    return blockers


def _phase_6n_warnings(phase_6m: dict[str, Any]) -> list[str]:
    warnings: list[str] = [PHASE_6N_WARNING]
    if not phase_6m.get("webhookTestModeEnabled"):
        warnings.append(
            "phase_6m_test_mode_disabled_in_current_env_phase_6n_planning_unaffected"
        )
    if (phase_6m.get("verifiedEventCount") or 0) == 0:
        warnings.append(
            "no_phase_6m_verified_event_observed_yet_phase_6n_plan_remains_valid"
        )
    return warnings


def inspect_razorpay_business_mutation_sandbox_readiness() -> dict[str, Any]:
    """Read-only Phase 6N readiness composition.

    Composes the Phase 6M handler readiness signal + safety counters
    + plan completeness checks into a typed Phase 6N readiness
    report. NEVER calls Razorpay; NEVER mutates anything.
    """
    phase_6m = _phase_6m_safety_signal()

    event_mappings = build_razorpay_event_status_mapping_plan()
    eligibility = build_synthetic_order_eligibility_policy()
    checklist = build_phase6n_manual_review_checklist()
    rollback = build_phase6n_rollback_plan()
    invariants = _safety_invariants()

    plan_complete = bool(
        len(event_mappings) == 9
        and eligibility
        and checklist
        and rollback
        and invariants
    )

    blockers = _phase_6n_blockers(phase_6m)
    warnings = _phase_6n_warnings(phase_6m)
    if not plan_complete:
        blockers.append("phase_6n_plan_section_incomplete")

    safety_count_ok = all(
        (phase_6m.get(key) or 0) == 0
        for key in (
            "businessMutationCount",
            "customerNotificationCount",
            "rawSecretExposureCount",
            "fullPiiExposureCount",
        )
    )

    flags_ok = (
        phase_6m.get("businessMutationEnabled") is False
        and phase_6m.get("customerNotificationEnabled") is False
        and phase_6m.get("storeRawPayload") is False
    )

    safe_to_start_phase_6o = bool(
        plan_complete
        and safety_count_ok
        and flags_ok
        and not blockers
    )

    if not safety_count_ok or not flags_ok:
        next_action = "fix_phase_6m_safety_state_before_planning_phase_6o"
    elif not plan_complete:
        next_action = "complete_phase_6n_plan_sections"
    elif blockers:
        next_action = "fix_phase_6n_blockers_before_planning_phase_6o"
    else:
        next_action = (
            "ready_for_phase_6o_sandbox_payment_status_mapping_and_manual_review"
        )

    return {
        "phase": "6N",
        "status": "planning_only",
        "latestCompletedPhase": "6M",
        "nextPhase": "6O",
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "rawPayloadStorageEnabled": False,
        "phase6MWebhookTestModeEnabled": bool(
            phase_6m.get("webhookTestModeEnabled")
        ),
        "phase6MVerifiedEventCount": int(
            phase_6m.get("verifiedEventCount") or 0
        ),
        "phase6MBusinessMutationCount": int(
            phase_6m.get("businessMutationCount") or 0
        ),
        "phase6MCustomerNotificationCount": int(
            phase_6m.get("customerNotificationCount") or 0
        ),
        "phase6MRawSecretExposureCount": int(
            phase_6m.get("rawSecretExposureCount") or 0
        ),
        "phase6MFullPiiExposureCount": int(
            phase_6m.get("fullPiiExposureCount") or 0
        ),
        "planComplete": plan_complete,
        "eventMappingCount": len(event_mappings),
        "manualReviewChecklistSize": len(checklist),
        "rollbackStepCount": len(rollback.get("rollbackSteps") or []),
        "safetyCountersZero": safety_count_ok,
        "phase6MFlagsLockedOff": flags_ok,
        "safeToStartPhase6O": safe_to_start_phase_6o,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
        "requiredEnvDefaults": dict(PHASE_6N_REQUIRED_ENV_DEFAULTS),
        "forbiddenActions": list(PHASE_6N_FORBIDDEN_ACTIONS),
    }


# ---------------------------------------------------------------------------
# Plan composition
# ---------------------------------------------------------------------------


def _phase_6n_audit_plan() -> list[dict[str, Any]]:
    return [
        {
            "kind": "razorpay.sandbox_plan.inspected",
            "tone": "info",
            "emittedBy": "manage.py inspect_razorpay_business_mutation_sandbox_plan",
            "payloadKeys": [
                "phase",
                "status",
                "eventMappingCount",
                "manualReviewChecklistSize",
                "businessMutationEnabled",
            ],
            "neverIncludes": [
                "razorpayKeySecret",
                "razorpayWebhookSecret",
                "rawWebhookPayload",
                "customerEmail",
                "customerPhone",
                "customerName",
                "customerAddress",
                "cardNumber",
                "vpa",
                "upi",
                "bankAccount",
            ],
        },
        {
            "kind": "razorpay.sandbox_readiness.inspected",
            "tone": "info",
            "emittedBy": "manage.py inspect_razorpay_business_mutation_sandbox_readiness",
            "payloadKeys": [
                "phase",
                "safeToStartPhase6O",
                "blockerCount",
                "warningCount",
                "nextAction",
            ],
            "neverIncludes": [
                "razorpayKeySecret",
                "razorpayWebhookSecret",
                "rawWebhookPayload",
                "customerEmail",
                "customerPhone",
                "customerName",
                "customerAddress",
                "cardNumber",
                "vpa",
                "upi",
                "bankAccount",
            ],
        },
    ]


def get_razorpay_business_mutation_sandbox_plan() -> dict[str, Any]:
    """Return the canonical Phase 6N planning JSON.

    Pure data composition. Never queries Razorpay; never mutates the
    DB; never returns raw secrets or PII.
    """
    readiness = inspect_razorpay_business_mutation_sandbox_readiness()
    event_mappings = build_razorpay_event_status_mapping_plan()
    eligibility = build_synthetic_order_eligibility_policy()
    checklist = build_phase6n_manual_review_checklist()
    rollback = build_phase6n_rollback_plan()
    invariants = _safety_invariants()
    audit_plan = _phase_6n_audit_plan()

    plan: dict[str, Any] = {
        "phase": "6N",
        "policyVersion": "phase6n.v1",
        "status": "planning_only",
        "latestCompletedPhase": "6M",
        "nextPhase": "6O",
        "businessMutationEnabled": False,
        "customerNotificationEnabled": False,
        "rawPayloadStorageEnabled": False,
        "safeToStartPhase6O": readiness["safeToStartPhase6O"],
        "blockers": readiness["blockers"],
        "warnings": readiness["warnings"],
        "nextAction": readiness["nextAction"],
        "summary": (
            "Phase 6N is the planning + readiness layer for a future "
            "Phase 6O sandbox-only mutation path against synthetic "
            "test orders. Phase 6N never mutates business state, "
            "never calls Razorpay, never sends a customer "
            "notification, and never flips an env flag."
        ),
        "eventMappings": event_mappings,
        "syntheticEligibilityPolicy": eligibility,
        "manualReviewChecklist": checklist,
        "rollbackPlan": rollback,
        "safetyInvariants": invariants,
        "forbiddenActions": list(PHASE_6N_FORBIDDEN_ACTIONS),
        "requiredEnvDefaults": dict(PHASE_6N_REQUIRED_ENV_DEFAULTS),
        "auditPlan": audit_plan,
    }

    return plan


__all__ = (
    "PHASE_6N_WARNING",
    "PHASE_6N_FORBIDDEN_ACTIONS",
    "PHASE_6N_REQUIRED_ENV_DEFAULTS",
    "PHASE_6N_AUDIT_KINDS",
    "build_razorpay_event_status_mapping_plan",
    "build_synthetic_order_eligibility_policy",
    "build_phase6n_manual_review_checklist",
    "build_phase6n_rollback_plan",
    "validate_phase6n_no_mutation_invariants",
    "inspect_razorpay_business_mutation_sandbox_readiness",
    "get_razorpay_business_mutation_sandbox_plan",
)
