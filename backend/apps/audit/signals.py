"""Cross-app signal receivers that write to the Master Event Ledger.

Connecting receivers here (rather than in each app) keeps the audit module the
single owner of ``AuditEvent`` writes — apps emit ``post_save``/``post_delete``
naturally, audit translates them into ledger rows.

Phase 4A also adds a fan-out receiver on ``AuditEvent`` itself that
publishes the row to the Channels ``audit_events`` group so dashboards
can stream new events live. The publisher is wrapped in
``transaction.on_commit`` and a broad ``try/except`` so a missing
Redis / Channels failure can never break the underlying write.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditEvent
from .realtime import publish_audit_event

ICON_BY_KIND: dict[str, str] = {
    # Existing (Phase 1).
    "lead.created": "user-plus",
    "order.created": "shopping-bag",
    "order.status_changed": "refresh-cw",
    "payment.received": "indian-rupee",
    "shipment.status_changed": "truck",
    "rto.flagged": "alert-triangle",
    "reward.assigned": "award",
    "compliance.flagged": "shield-alert",
    # Phase 2A — explicit writes from the service layer.
    "lead.updated": "user-cog",
    "lead.assigned": "user-check",
    "customer.upserted": "users",
    "confirmation.outcome": "check-circle-2",
    "payment.link_created": "link",
    "shipment.created": "package",
    "rescue.attempted": "phone-call",
    "rescue.updated": "phone-forwarded",
    # Phase 2C — Delhivery webhook outcomes.
    "shipment.delivered": "package-check",
    "shipment.ndr": "alert-octagon",
    "shipment.rto_initiated": "package-x",
    "shipment.rto_delivered": "rotate-ccw",
    # Phase 2D — Vapi voice events.
    "call.triggered": "phone-outgoing",
    "call.started": "phone-incoming",
    "call.completed": "phone-off",
    "call.failed": "phone-missed",
    "call.transcript": "file-text",
    "call.analysis": "sparkles",
    "call.handoff_flagged": "alert-triangle",
    # Phase 2E — Meta Lead Ads ingestion.
    "lead.meta_ingested": "facebook",
    # Phase 3A — AgentRun lifecycle.
    "ai.agent_run.created": "sparkles",
    "ai.agent_run.completed": "check-circle",
    "ai.agent_run.failed": "x-circle",
    # Phase 3B — per-agent runtime outcomes.
    "ai.ceo_brief.generated": "presentation",
    "ai.caio_sweep.completed": "shield-check",
    "ai.agent_runtime.completed": "play-circle",
    "ai.agent_runtime.failed": "alert-octagon",
    # Phase 3C — Celery scheduler + cost / fallback tracking.
    "ai.scheduler.daily_briefing.started": "alarm-clock",
    "ai.scheduler.daily_briefing.completed": "alarm-check",
    "ai.scheduler.daily_briefing.failed": "alarm-clock-off",
    "ai.provider.fallback_used": "shuffle",
    "ai.cost_tracked": "indian-rupee",
    # Phase 3D — sandbox + prompt versioning + budget guards.
    "ai.prompt_version.created": "file-plus",
    "ai.prompt_version.activated": "play",
    "ai.prompt_version.rolled_back": "rotate-ccw",
    "ai.sandbox.enabled": "shield-half",
    "ai.sandbox.disabled": "shield-off",
    "ai.budget.warning": "gauge",
    "ai.budget.blocked": "ban",
    # Phase 4C — approval matrix middleware enforcement.
    "ai.approval.requested": "user-check",
    "ai.approval.auto_approved": "badge-check",
    "ai.approval.approved": "check-circle",
    "ai.approval.rejected": "x-circle",
    "ai.approval.blocked": "ban",
    "ai.approval.escalated": "alert-triangle",
    "ai.approval.expired": "timer-off",
    "ai.agent_run.approval_requested": "user-plus",
    # Phase 4D — Approved Action Execution Layer.
    "ai.approval.executed": "play-circle",
    "ai.approval.execution_failed": "alert-octagon",
    "ai.approval.execution_skipped": "skip-forward",
    # Phase 4B — reward / penalty engine.
    "ai.reward.calculated": "award",
    "ai.penalty.applied": "minus-circle",
    "ai.reward_penalty.sweep_started": "play",
    "ai.reward_penalty.sweep_completed": "check-circle",
    "ai.reward_penalty.sweep_failed": "x-circle",
    "ai.reward_penalty.leaderboard_updated": "trophy",
    # Phase 3E — catalog admin + business policy events.
    "catalog.category.created": "folder-plus",
    "catalog.category.updated": "folder-edit",
    "catalog.product.created": "package-plus",
    "catalog.product.updated": "package-edit",
    "catalog.sku.created": "tag",
    "catalog.sku.updated": "tag-edit",
    "discount.requested": "percent",
    "discount.approved": "badge-check",
    "discount.blocked": "ban",
    # Phase 4E — Approved Action Execution Layer expansion (discount apply).
    "discount.applied": "percent",
    "approval.required": "user-check",
    "whatsapp.message_queued": "message-circle",
    "whatsapp.broadcast.requested": "megaphone",
    "whatsapp.escalation.requested": "alert-triangle",
    # Phase 5A — WhatsApp Live Sender Foundation lifecycle kinds.
    "whatsapp.message.queued": "send",
    "whatsapp.message.sent": "send",
    "whatsapp.message.delivered": "check-check",
    "whatsapp.message.read": "eye",
    "whatsapp.message.failed": "alert-octagon",
    "whatsapp.template.sent": "file-text",
    "whatsapp.send.blocked": "ban",
    "whatsapp.webhook.received": "webhook",
    "whatsapp.inbound.received": "message-circle",
    "whatsapp.inbound.escalated": "alert-triangle",
    "whatsapp.consent.updated": "user-check",
    "whatsapp.opt_out.received": "user-x",
    "whatsapp.connection.configured": "plug",
    "whatsapp.connection.status_changed": "activity",
    "whatsapp.connection.error": "x-circle",
    "whatsapp.template.synced": "refresh-cw",
    "whatsapp.template.activated": "play",
    "whatsapp.template.deactivated": "pause",
    # Phase 5B — Inbox / Customer 360 lifecycle audit kinds.
    "whatsapp.conversation.opened": "message-square",
    "whatsapp.conversation.updated": "edit-3",
    "whatsapp.conversation.assigned": "user-plus",
    "whatsapp.conversation.read": "check",
    "whatsapp.internal_note.created": "sticky-note",
    "whatsapp.template.manual_send_requested": "send",
    # Phase 5C — WhatsApp AI Chat Sales Agent.
    "whatsapp.ai.run_started": "play",
    "whatsapp.ai.run_completed": "check-circle",
    "whatsapp.ai.run_failed": "x-circle",
    "whatsapp.ai.reply_auto_sent": "send",
    "whatsapp.ai.reply_blocked": "ban",
    "whatsapp.ai.suggestion_stored": "lightbulb",
    "whatsapp.ai.greeting_sent": "hand",
    "whatsapp.ai.greeting_blocked": "ban",
    "whatsapp.ai.language_detected": "languages",
    "whatsapp.ai.category_detected": "tag",
    "whatsapp.ai.address_updated": "map-pin",
    "whatsapp.ai.order_draft_created": "file-text",
    "whatsapp.ai.order_booked": "shopping-bag",
    "whatsapp.ai.payment_link_created": "link",
    "whatsapp.ai.handoff_required": "alert-triangle",
    "whatsapp.ai.discount_objection_handled": "message-circle",
    "whatsapp.ai.discount_offered": "percent",
    "whatsapp.ai.discount_blocked": "ban",
    # Phase 5E-Smoke-Fix-3 — server-side safety flag corrector.
    "whatsapp.ai.safety_downgraded": "shield-off",
    # Phase 5D — Chat-to-call handoff + lifecycle automation.
    "whatsapp.handoff.call_requested": "phone",
    "whatsapp.handoff.call_triggered": "phone-outgoing",
    "whatsapp.handoff.call_failed": "phone-missed",
    "whatsapp.handoff.call_skipped": "phone-off",
    "whatsapp.handoff.call_skipped_duplicate": "skip-forward",
    "whatsapp.lifecycle.queued": "send",
    "whatsapp.lifecycle.sent": "send",
    "whatsapp.lifecycle.blocked": "ban",
    "whatsapp.lifecycle.skipped_duplicate": "skip-forward",
    "whatsapp.lifecycle.failed": "alert-octagon",
    "whatsapp.ai.order_moved_to_confirmation": "check-circle-2",
    "compliance.claim_coverage.checked": "shield-check",
    # Phase 5E — Rescue discount + Day-20 reorder + default claim seeds.
    "discount.offer.created": "percent",
    "discount.offer.sent": "send",
    "discount.offer.accepted": "badge-check",
    "discount.offer.rejected": "x-circle",
    "discount.offer.blocked": "ban",
    "discount.offer.needs_ceo_review": "alert-triangle",
    "whatsapp.lifecycle.rescue_discount_queued": "percent",
    "whatsapp.lifecycle.rescue_discount_sent": "percent",
    "whatsapp.lifecycle.reorder_day20_queued": "calendar-clock",
    "whatsapp.lifecycle.reorder_day20_sent": "calendar-check",
    "compliance.default_claims.seeded": "shield-check",
    # Phase 5E-Smoke — controlled mock + OpenAI smoke testing harness.
    "system.smoke_test.started": "play",
    "system.smoke_test.completed": "check-circle",
    "system.smoke_test.failed": "x-circle",
    "system.smoke_test.warning": "alert-triangle",
    # Phase 5F-Gate — Limited Live Meta WhatsApp One-Number Test.
    "whatsapp.meta_test.started": "play",
    "whatsapp.meta_test.config_ok": "shield-check",
    "whatsapp.meta_test.config_failed": "shield-off",
    "whatsapp.meta_test.blocked_number": "ban",
    "whatsapp.meta_test.template_missing": "alert-triangle",
    "whatsapp.meta_test.sent": "send",
    "whatsapp.meta_test.failed": "x-circle",
    "whatsapp.meta_test.completed": "check-circle",
    # Phase 5F-Gate Hardening Hotfix.
    "whatsapp.meta_test.duplicate_idempotency": "copy",
    "whatsapp.meta_test.webhook_subscription_checked": "shield-question",
    # Phase 5F-Gate Controlled AI Auto-Reply Test Harness.
    "whatsapp.ai.controlled_test.started": "play",
    "whatsapp.ai.controlled_test.dry_run_passed": "check-circle",
    "whatsapp.ai.controlled_test.sent": "send",
    "whatsapp.ai.controlled_test.blocked": "ban",
    "whatsapp.ai.controlled_test.completed": "check-circle",
    # Phase 5F-Gate Deterministic Grounded Reply Builder.
    "whatsapp.ai.deterministic_grounded_reply_used": "shield-check",
    "whatsapp.ai.deterministic_grounded_reply_blocked": "shield-off",
    # Phase 5F-Gate Objection & Handoff Reason Refinement.
    "whatsapp.ai.objection_detected": "tag",
    "whatsapp.ai.objection_reply_used": "shield-check",
    "whatsapp.ai.objection_reply_blocked": "shield-off",
    "whatsapp.ai.human_request_detected": "phone-call",
    # Phase 5F-Gate Internal Allowed-Number Cohort Tooling.
    "whatsapp.internal_cohort.number_prepared": "user-check",
    # Phase 5F-Gate Approved Customer Pilot Readiness.
    "whatsapp.pilot.member_saved": "user-check",
    "whatsapp.pilot.member_prepared": "user-check",
    "whatsapp.pilot.member_paused": "pause",
    # Phase 5F-Gate Limited Auto-Reply Flag Plan.
    "whatsapp.ai.auto_reply_flag_path_used": "send",
    "whatsapp.ai.auto_reply_guard_blocked": "shield-off",
}


def write_event(*, kind: str, text: str, tone: str = AuditEvent.Tone.INFO, payload: dict | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        kind=kind,
        text=text,
        tone=tone,
        icon=ICON_BY_KIND.get(kind, "activity"),
        payload=payload or {},
    )


@receiver(post_save, sender=AuditEvent, dispatch_uid="audit.event_created_publish")
def _on_audit_event_created(sender, instance: AuditEvent, created: bool, **_):
    """Phase 4A — publish new AuditEvent rows to the WebSocket fanout group.

    Updates are skipped intentionally (Phase 4A streams creates only).
    The publish is fire-and-forget: failures are logged inside
    :func:`publish_audit_event`, never raised.
    """
    if not created:
        return
    publish_audit_event(instance)


@receiver(
    post_save,
    sender="whatsapp.WhatsAppPilotCohortMember",
    dispatch_uid="audit.whatsapp_pilot_member_saved",
)
def _on_whatsapp_pilot_member_saved(sender, instance, created, **_):
    write_event(
        kind="whatsapp.pilot.member_saved",
        text=f"WhatsApp pilot member {instance.customer_id} {'created' if created else 'updated'}",
        tone=AuditEvent.Tone.INFO,
        payload={
            "customer_id": instance.customer_id,
            "status": instance.status,
            "phone_suffix": instance.phone_suffix,
            "consent_verified": instance.consent_verified,
            "created": created,
        },
    )


@receiver(post_save, sender="crm.Lead", dispatch_uid="audit.lead_created")
def _on_lead_saved(sender, instance, created, **_):
    if not created:
        return
    write_event(
        kind="lead.created",
        text=f"New lead {instance.name} ({instance.state}) via {instance.source}",
        tone=AuditEvent.Tone.INFO,
        payload={"lead_id": instance.id, "source": instance.source},
    )


@receiver(post_save, sender="orders.Order", dispatch_uid="audit.order_status")
def _on_order_saved(sender, instance, created, **_):
    if created:
        write_event(
            kind="order.created",
            text=f"Order {instance.id} punched · {instance.product} · ₹{instance.amount}",
            tone=AuditEvent.Tone.SUCCESS,
            payload={"order_id": instance.id, "stage": instance.stage},
        )
        return
    write_event(
        kind="order.status_changed",
        text=f"Order {instance.id} → {instance.stage}",
        tone=AuditEvent.Tone.INFO,
        payload={"order_id": instance.id, "stage": instance.stage},
    )


@receiver(post_save, sender="payments.Payment", dispatch_uid="audit.payment_received")
def _on_payment_saved(sender, instance, created, **_):
    if not created or instance.status != "Paid":
        return
    write_event(
        kind="payment.received",
        text=f"Payment ₹{instance.amount} received from {instance.customer} ({instance.gateway})",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"payment_id": instance.id, "order_id": instance.order_id},
    )


@receiver(post_save, sender="shipments.Shipment", dispatch_uid="audit.shipment_status")
def _on_shipment_saved(sender, instance, created, **_):
    write_event(
        kind="shipment.status_changed",
        text=f"AWB {instance.awb} · {instance.status} · {instance.city}",
        tone=AuditEvent.Tone.INFO,
        payload={"awb": instance.awb, "order_id": instance.order_id},
    )
