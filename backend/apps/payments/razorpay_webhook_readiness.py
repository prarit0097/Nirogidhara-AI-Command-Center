"""Phase 6M — Razorpay webhook handler readiness selector.

Pure read-only. Composes the Phase 6M settings snapshot + a count of
recorded `RazorpayWebhookEvent` rows (per status / safety counters)
and returns a typed readiness report. NEVER calls Razorpay; NEVER
exposes the raw webhook secret.
"""
from __future__ import annotations

from typing import Any

from .models import RazorpayWebhookEvent
from .razorpay_webhooks import get_razorpay_webhook_settings


def get_razorpay_webhook_handler_readiness() -> dict[str, Any]:
    snapshot = get_razorpay_webhook_settings()

    qs = RazorpayWebhookEvent.objects.all()
    Status = RazorpayWebhookEvent.ProcessingStatus

    event_count = qs.count()
    verified_count = qs.filter(
        processing_status__in=[Status.STORED, Status.VERIFIED]
    ).count()
    duplicate_count = qs.filter(
        processing_status=Status.DUPLICATE
    ).count() + qs.filter(duplicate_count__gt=0).count()
    blocked_count = qs.filter(
        processing_status__in=[Status.BLOCKED, Status.IGNORED]
    ).count()
    business_mutation_count = qs.filter(business_mutation_was_made=True).count()
    customer_notification_count = qs.filter(
        customer_notification_sent=True
    ).count()
    raw_secret_exposure_count = qs.filter(raw_secret_exposed=True).count()
    full_pii_exposure_count = qs.filter(full_pii_exposed=True).count()

    blockers: list[str] = []
    warnings: list[str] = []
    if not snapshot["testModeEnabled"]:
        blockers.append("razorpay_webhook_test_mode_disabled")
    if not snapshot["webhookSecretPresent"]:
        blockers.append("razorpay_webhook_secret_missing")
    if snapshot["businessMutationEnabled"]:
        blockers.append(
            "phase_6m_business_mutation_must_remain_disabled"
        )
    if snapshot["notifyCustomerEnabled"]:
        blockers.append(
            "phase_6m_customer_notification_must_remain_disabled"
        )
    if business_mutation_count:
        blockers.append("phase_6m_business_mutation_count_must_be_zero")
    if customer_notification_count:
        blockers.append(
            "phase_6m_customer_notification_count_must_be_zero"
        )
    if snapshot["storeRawPayload"]:
        warnings.append(
            "RAZORPAY_WEBHOOK_STORE_RAW_PAYLOAD=true; consider keeping "
            "raw payloads off in Phase 6M."
        )

    safe_to_receive = (
        snapshot["testModeEnabled"]
        and snapshot["webhookSecretPresent"]
        and not snapshot["businessMutationEnabled"]
        and not snapshot["notifyCustomerEnabled"]
        and business_mutation_count == 0
        and customer_notification_count == 0
    )
    safe_to_start_phase_6n = (
        safe_to_receive
        and verified_count >= 1
        and raw_secret_exposure_count == 0
        and full_pii_exposure_count == 0
    )

    if not safe_to_receive:
        next_action = "fix_razorpay_webhook_handler_blockers"
    elif verified_count == 0:
        next_action = "send_synthetic_test_event_via_simulator"
    else:
        next_action = (
            "ready_for_phase_6n_razorpay_webhook_business_mutation_sandbox_plan"
        )

    return {
        "phase": "6M",
        "webhookTestModeEnabled": snapshot["testModeEnabled"],
        "webhookSecretPresent": snapshot["webhookSecretPresent"],
        "businessMutationEnabled": snapshot["businessMutationEnabled"],
        "customerNotificationEnabled": snapshot["notifyCustomerEnabled"],
        "storeRawPayload": snapshot["storeRawPayload"],
        "allowTestEventsOnly": snapshot["allowTestEventsOnly"],
        "replayWindowSeconds": snapshot["replayWindowSeconds"],
        "allowedEvents": snapshot["allowedEvents"],
        "deniedEvents": snapshot["deniedEvents"],
        "eventCount": event_count,
        "verifiedEventCount": verified_count,
        "duplicateEventCount": duplicate_count,
        "blockedEventCount": blocked_count,
        "businessMutationCount": business_mutation_count,
        "customerNotificationCount": customer_notification_count,
        "rawSecretExposureCount": raw_secret_exposure_count,
        "fullPiiExposureCount": full_pii_exposure_count,
        "safeToReceiveTestWebhooks": safe_to_receive,
        "safeToStartPhase6N": safe_to_start_phase_6n,
        "blockers": blockers,
        "warnings": warnings,
        "nextAction": next_action,
    }


__all__ = ("get_razorpay_webhook_handler_readiness",)
