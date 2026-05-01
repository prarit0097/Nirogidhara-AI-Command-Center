"""Phase 5F-Gate approved customer pilot readiness helpers.

Everything in this module is either read-only or preparation-only. It never
calls a WhatsApp provider, never dispatches an LLM, and never mutates
Order/Payment/Shipment/DiscountOfferLog rows.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.shipments.models import Shipment

from .meta_one_number_test import (
    _digits_only,
    get_allowed_test_numbers,
    is_number_allowed_for_live_meta_test,
)
from .models import (
    WhatsAppConsent,
    WhatsAppMessage,
    WhatsAppPilotCohortMember,
)


PILOT_SOURCE_DEFAULT = "approved_customer_pilot"


def mask_phone(value: str) -> str:
    digits = _digits_only(value or "")
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    suffix = digits[-4:]
    if len(digits) >= 12:
        return f"+{digits[:2]}{'*' * 5}{suffix}"
    return f"{'*' * (len(digits) - 4)}{suffix}"


def phone_suffix(value: str) -> str:
    digits = _digits_only(value or "")
    return digits[-4:] if digits else ""


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def find_customer_by_phone(phone: str) -> Customer | None:
    digits = _digits_only(phone or "")
    if not digits:
        return None
    candidates = {
        f"+{digits}",
        digits,
        digits[-10:] if len(digits) >= 10 else digits,
    }
    for needle in candidates:
        match = Customer.objects.filter(phone__iexact=needle).first()
        if match is not None:
            return match
    return Customer.objects.filter(phone__icontains=digits[-10:]).first()


def consent_is_verified(customer: Customer) -> bool:
    if not bool(customer.consent_whatsapp):
        return False
    consent = WhatsAppConsent.objects.filter(customer=customer).first()
    return bool(
        consent is not None
        and consent.consent_state == WhatsAppConsent.State.GRANTED
    )


def _latest_message(customer: Customer, direction: str) -> WhatsAppMessage | None:
    return (
        WhatsAppMessage.objects.filter(customer=customer, direction=direction)
        .order_by("-created_at")
        .first()
    )


def _recent_safety_issue(customer: Customer, *, since) -> bool:
    suffix = phone_suffix(customer.phone)
    return AuditEvent.objects.filter(
        kind__in=[
            "whatsapp.ai.auto_reply_guard_blocked",
            "whatsapp.send.blocked",
            "whatsapp.ai.reply_blocked",
            "whatsapp.ai.handoff_required",
        ],
        occurred_at__gte=since,
        payload__phone_suffix=suffix,
    ).exists()


def get_single_tenant_saas_guardrail_audit() -> dict[str, Any]:
    """Lightweight read-only SaaS gap report for future multi-tenant work."""
    return {
        "mode": "single_tenant_current",
        "organizationModelExists": False,
        "tenantModelExists": False,
        "branchModelExists": False,
        "userRolesExist": True,
        "auditOrgBranchContextExists": False,
        "featureFlagsPerOrgExist": False,
        "whatsappSettingsPerOrgExist": False,
        "safeInterfacesAdded": [
            "get_single_tenant_saas_guardrail_audit",
            "get_whatsapp_pilot_readiness_summary",
        ],
        "deferred": [
            "Do not introduce Organization/Tenant/Branch migrations during this pilot gate.",
            "Keep WhatsApp settings single-tenant until a dedicated SaaS phase adds data isolation.",
            "Add org/branch context to AuditEvent only with a full migration and API contract review.",
        ],
        "nextAction": "document_saas_gaps_before_multi_tenant_build",
    }


def get_whatsapp_pilot_readiness_summary(
    hours: float | int | None = 2,
) -> dict[str, Any]:
    h = 2.0
    if hours is not None:
        try:
            h = max(5 / 60, min(168.0, float(hours)))
        except (TypeError, ValueError):
            h = 2.0
    now = timezone.now()
    since = now - timedelta(hours=h)

    auto_reply_enabled = bool(
        getattr(settings, "WHATSAPP_AI_AUTO_REPLY_ENABLED", False)
    )
    limited_test_mode = bool(
        getattr(settings, "WHATSAPP_LIVE_META_LIMITED_TEST_MODE", False)
    )
    call_handoff = bool(getattr(settings, "WHATSAPP_CALL_HANDOFF_ENABLED", False))
    lifecycle = bool(
        getattr(settings, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED", False)
    )
    rescue = bool(getattr(settings, "WHATSAPP_RESCUE_DISCOUNT_ENABLED", False))
    rto = bool(getattr(settings, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED", False))
    reorder = bool(getattr(settings, "WHATSAPP_REORDER_DAY20_ENABLED", False))
    campaigns_locked = True
    broadcast_locked = True
    dashboard_available = True

    allowed_numbers = set(get_allowed_test_numbers())
    unexpected_sends = 0
    for msg in (
        WhatsAppMessage.objects.filter(
            direction=WhatsAppMessage.Direction.OUTBOUND,
            sent_at__gte=since,
        )
        .exclude(provider_message_id="")
        .select_related("customer")
    ):
        if not is_number_allowed_for_live_meta_test(msg.customer.phone):
            unexpected_sends += 1

    mutation_counts = {
        "ordersCreatedInWindow": Order.objects.filter(created_at__gte=since).count(),
        "paymentsCreatedInWindow": Payment.objects.filter(
            created_at__gte=since
        ).count(),
        "shipmentsCreatedInWindow": Shipment.objects.filter(
            created_at__gte=since
        ).count(),
        "discountOfferLogsCreatedInWindow": DiscountOfferLog.objects.filter(
            created_at__gte=since
        ).count(),
    }
    mutation_total = sum(mutation_counts.values())

    global_blockers: list[str] = []
    if auto_reply_enabled:
        global_blockers.append("WHATSAPP_AI_AUTO_REPLY_ENABLED must remain false.")
    if not limited_test_mode:
        global_blockers.append("WHATSAPP_LIVE_META_LIMITED_TEST_MODE must be true.")
    if not campaigns_locked:
        global_blockers.append("Campaigns must remain locked.")
    if not broadcast_locked:
        global_blockers.append("Broadcast sending must remain locked.")
    for enabled, label in (
        (call_handoff, "WHATSAPP_CALL_HANDOFF_ENABLED"),
        (lifecycle, "WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED"),
        (rescue, "WHATSAPP_RESCUE_DISCOUNT_ENABLED"),
        (rto, "WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED"),
        (reorder, "WHATSAPP_REORDER_DAY20_ENABLED"),
    ):
        if enabled:
            global_blockers.append(f"{label} must remain false.")
    if unexpected_sends:
        global_blockers.append("Unexpected outbound sends outside allow-list found.")
    if mutation_total:
        global_blockers.append("Business mutation count is non-zero in the window.")
    if not dashboard_available:
        global_blockers.append("Monitoring dashboard is unavailable.")

    members = []
    total = approved = pending = paused = consent_missing = ready = 0
    for member in (
        WhatsAppPilotCohortMember.objects.select_related("customer")
        .order_by("customer__id")
    ):
        total += 1
        if member.status == WhatsAppPilotCohortMember.Status.APPROVED:
            approved += 1
        if member.status == WhatsAppPilotCohortMember.Status.PENDING:
            pending += 1
        if member.status == WhatsAppPilotCohortMember.Status.PAUSED:
            paused += 1

        customer = member.customer
        verified = consent_is_verified(customer) and member.consent_verified
        if not verified:
            consent_missing += 1
        latest_in = _latest_message(customer, WhatsAppMessage.Direction.INBOUND)
        latest_out = _latest_message(customer, WhatsAppMessage.Direction.OUTBOUND)
        allowed = (
            is_number_allowed_for_live_meta_test(customer.phone)
            if limited_test_mode
            else True
        )
        recent_issue = _recent_safety_issue(customer, since=since)
        member_blockers: list[str] = []
        if not verified:
            member_blockers.append("consent_not_verified")
        if member.status != WhatsAppPilotCohortMember.Status.APPROVED:
            member_blockers.append(f"status_{member.status}")
        if not allowed:
            member_blockers.append("phone_not_allowed_in_limited_mode")
        if member.max_auto_replies_per_day <= 0:
            member_blockers.append("daily_cap_missing")
        if recent_issue:
            member_blockers.append("recent_safety_issue")

        member_ready = not global_blockers and not member_blockers
        if member_ready:
            ready += 1
        members.append(
            {
                "customerId": customer.id,
                "customerName": customer.name,
                "maskedPhone": member.phone_masked or mask_phone(customer.phone),
                "phoneSuffix": member.phone_suffix or phone_suffix(customer.phone),
                "status": member.status,
                "consentRequired": member.consent_required,
                "consentVerified": verified,
                "source": member.source,
                "approvedAt": iso(member.approved_at),
                "dailyCap": member.max_auto_replies_per_day,
                "lastInboundAt": iso(
                    latest_in.delivered_at or latest_in.created_at
                    if latest_in
                    else None
                ),
                "lastOutboundAt": iso(
                    latest_out.sent_at or latest_out.created_at
                    if latest_out
                    else None
                ),
                "latestStatus": latest_out.status if latest_out else "",
                "phoneAllowedInLimitedMode": allowed,
                "recentSafetyIssue": recent_issue,
                "ready": member_ready,
                "blockers": member_blockers,
            }
        )

    if total == 0:
        next_action = "prepare_approved_customer_pilot_members"
    elif global_blockers:
        next_action = "fix_global_pilot_blockers"
    elif consent_missing:
        next_action = "verify_customer_consent_before_pilot"
    elif ready == 0:
        next_action = "approve_or_unpause_pilot_members"
    else:
        next_action = "ready_for_tiny_approved_customer_pilot"

    return {
        "windowHours": h,
        "generatedAt": iso(now),
        "totalPilotMembers": total,
        "approvedCount": approved,
        "pendingCount": pending,
        "pausedCount": paused,
        "consentMissingCount": consent_missing,
        "readyForPilotCount": ready,
        "members": members,
        "blockers": global_blockers,
        "nextAction": next_action,
        "safety": {
            "autoReplyEnabled": auto_reply_enabled,
            "limitedTestMode": limited_test_mode,
            "campaignsLocked": campaigns_locked,
            "broadcastLocked": broadcast_locked,
            "callHandoffEnabled": call_handoff,
            "lifecycleEnabled": lifecycle,
            "rescueDiscountEnabled": rescue,
            "rtoRescueEnabled": rto,
            "reorderEnabled": reorder,
            "allowedListSize": len(allowed_numbers),
            "unexpectedNonAllowedSendsCount": unexpected_sends,
            "mutationCounts": mutation_counts,
            "mutationTotal": mutation_total,
            "dashboardAvailable": dashboard_available,
        },
        "saasGuardrails": get_single_tenant_saas_guardrail_audit(),
    }


@transaction.atomic
def prepare_whatsapp_customer_pilot_member(
    *,
    phone: str,
    name: str,
    source: str = PILOT_SOURCE_DEFAULT,
    actor=None,
) -> tuple[WhatsAppPilotCohortMember, bool, bool]:
    digits = _digits_only(phone or "")
    if not digits:
        raise ValueError("phone is required")
    customer = find_customer_by_phone(phone)
    created_customer = False
    if customer is None:
        customer = Customer.objects.create(
            id=next_id("NRG-CUST", Customer, base=900001),
            name=name or "Approved Pilot Customer",
            phone=f"+{digits}",
            state="",
            city="",
            language="Hinglish",
            product_interest="",
            consent_whatsapp=False,
        )
        created_customer = True
    else:
        changed = []
        if name and customer.name != name:
            customer.name = name
            changed.append("name")
        if changed:
            customer.save(update_fields=changed)

    verified = consent_is_verified(customer)
    status = (
        WhatsAppPilotCohortMember.Status.APPROVED
        if verified
        else WhatsAppPilotCohortMember.Status.PENDING
    )
    now = timezone.now()
    member, created_member = WhatsAppPilotCohortMember.objects.get_or_create(
        customer=customer,
        defaults={
            "phone_masked": mask_phone(customer.phone),
            "phone_suffix": phone_suffix(customer.phone),
            "status": status,
            "consent_verified": verified,
            "source": source,
            "approved_by": actor if verified else None,
            "approved_at": now if verified else None,
            "metadata": {"prepared_by": getattr(actor, "username", "system")},
        },
    )
    if not created_member:
        member.phone_masked = mask_phone(customer.phone)
        member.phone_suffix = phone_suffix(customer.phone)
        member.status = (
            status
            if member.status != WhatsAppPilotCohortMember.Status.PAUSED
            else member.status
        )
        member.consent_verified = verified
        member.source = source or member.source
        if verified and member.approved_at is None:
            member.approved_at = now
            member.approved_by = actor
        member.save(
            update_fields=[
                "phone_masked",
                "phone_suffix",
                "status",
                "consent_verified",
                "source",
                "approved_at",
                "approved_by",
                "updated_at",
            ]
        )

    write_event(
        kind="whatsapp.pilot.member_prepared",
        text=f"WhatsApp customer pilot member prepared - {member.customer_id}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "customer_id": customer.id,
            "phone_suffix": member.phone_suffix,
            "status": member.status,
            "consent_verified": verified,
            "source": member.source,
            "created_customer": created_customer,
            "created_member": created_member,
            "actor": getattr(actor, "username", "system"),
        },
    )
    return member, created_customer, created_member


@transaction.atomic
def pause_whatsapp_customer_pilot_member(
    *,
    phone: str,
    reason: str,
    actor=None,
) -> WhatsAppPilotCohortMember:
    customer = find_customer_by_phone(phone)
    if customer is None:
        raise ValueError("customer not found")
    member = WhatsAppPilotCohortMember.objects.filter(customer=customer).first()
    if member is None:
        raise ValueError("pilot member not found")
    member.status = WhatsAppPilotCohortMember.Status.PAUSED
    member.notes = reason or member.notes
    metadata = dict(member.metadata or {})
    metadata["pauseReason"] = reason
    metadata["pausedBy"] = getattr(actor, "username", "system")
    metadata["pausedAt"] = iso(timezone.now())
    member.metadata = metadata
    member.save(update_fields=["status", "notes", "metadata", "updated_at"])
    write_event(
        kind="whatsapp.pilot.member_paused",
        text=f"WhatsApp customer pilot member paused - {member.customer_id}",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "customer_id": customer.id,
            "phone_suffix": member.phone_suffix,
            "reason": reason,
            "actor": getattr(actor, "username", "system"),
        },
    )
    return member
