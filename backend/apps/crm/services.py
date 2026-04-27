"""CRM write services — pure functions called by views and (eventually) tasks.

No DRF imports here; these functions take typed kwargs, mutate models, write
audit-ledger rows for events the post-save signals don't already cover, and
return the model instance. Views serialize and respond.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .integrations.meta_client import MetaLead, expand_lead
from .models import Customer, Lead, MetaLeadEvent

# Cross-app import only for the by_user type hint; runtime never imports User
# here so Django app loading order stays unaffected.
try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


@transaction.atomic
def create_lead(
    *,
    name: str,
    phone: str,
    state: str,
    city: str,
    language: str = "Hinglish",
    source: str = "Manual",
    campaign: str = "",
    product_interest: str = "",
    quality: str = Lead.Quality.WARM,
    quality_score: int = 50,
    assignee: str = "",
    duplicate: bool = False,
) -> Lead:
    lead = Lead.objects.create(
        id=next_id("LD", Lead, base=10300),
        name=name,
        phone=phone,
        state=state,
        city=city,
        language=language,
        source=source,
        campaign=campaign,
        product_interest=product_interest,
        status=Lead.Status.NEW,
        quality=quality,
        quality_score=quality_score,
        assignee=assignee,
        duplicate=duplicate,
        created_at_label="just now",
    )
    # `lead.created` AuditEvent is fired by the existing post_save signal.
    return lead


@transaction.atomic
def update_lead(lead: Lead, *, by_user: "User", **patch: Any) -> Lead:
    """Apply a partial patch and log a `lead.updated` AuditEvent."""
    if not patch:
        return lead
    allowed = {
        "name",
        "phone",
        "state",
        "city",
        "language",
        "source",
        "campaign",
        "product_interest",
        "status",
        "quality",
        "quality_score",
        "assignee",
        "duplicate",
    }
    changed: dict[str, Any] = {}
    for key, value in patch.items():
        if key in allowed and getattr(lead, key) != value:
            setattr(lead, key, value)
            changed[key] = value
    if not changed:
        return lead
    lead.save(update_fields=list(changed.keys()))
    write_event(
        kind="lead.updated",
        text=f"Lead {lead.id} updated by {getattr(by_user, 'username', 'system')}",
        tone=AuditEvent.Tone.INFO,
        payload={"lead_id": lead.id, "changes": list(changed.keys()), "by": getattr(by_user, "username", "")},
    )
    return lead


@transaction.atomic
def assign_lead(lead: Lead, *, assignee: str, by_user: "User") -> Lead:
    if not assignee:
        raise ValueError("assignee is required")
    if lead.assignee == assignee:
        return lead
    lead.assignee = assignee
    lead.save(update_fields=["assignee"])
    write_event(
        kind="lead.assigned",
        text=f"Lead {lead.id} assigned to {assignee}",
        tone=AuditEvent.Tone.INFO,
        payload={"lead_id": lead.id, "assignee": assignee, "by": getattr(by_user, "username", "")},
    )
    return lead


@transaction.atomic
def upsert_customer(
    *,
    by_user: "User",
    customer_id: str | None = None,
    lead_id: str | None = None,
    **fields: Any,
) -> Customer:
    """Create-or-update a Customer. Returns the persisted row.

    If ``customer_id`` matches an existing row, fields are patched in. Otherwise
    a new row is created with a fresh ``CU-NNNN`` id.
    """
    allowed = {
        "name",
        "phone",
        "state",
        "city",
        "language",
        "product_interest",
        "disease_category",
        "lifestyle_notes",
        "objections",
        "ai_summary",
        "risk_flags",
        "reorder_probability",
        "satisfaction",
        "consent_call",
        "consent_whatsapp",
        "consent_marketing",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}

    if customer_id:
        try:
            customer = Customer.objects.get(pk=customer_id)
        except Customer.DoesNotExist as exc:
            raise ValueError(f"Customer {customer_id} not found") from exc
        for key, value in payload.items():
            setattr(customer, key, value)
        customer.save(update_fields=list(payload.keys()) if payload else None)
        action = "updated"
    else:
        customer = Customer.objects.create(
            id=next_id("CU", Customer, base=5100),
            lead_id=lead_id,
            **payload,
        )
        action = "created"

    write_event(
        kind="customer.upserted",
        text=f"Customer {customer.id} {action} by {getattr(by_user, 'username', 'system')}",
        tone=AuditEvent.Tone.INFO,
        payload={"customer_id": customer.id, "action": action, "by": getattr(by_user, "username", "")},
    )
    return customer


# ----- Phase 2E — Meta Lead Ads ingestion -----


@transaction.atomic
def ingest_meta_lead(meta_lead: MetaLead) -> tuple[Lead, str]:
    """Idempotently turn a parsed ``MetaLead`` into a ``Lead`` row.

    Returns ``(lead, action)`` where ``action`` is one of:

    - ``"created"`` — new Lead row written
    - ``"updated"`` — existing Lead refreshed with the latest Meta data
    - ``"duplicate"`` — same ``leadgen_id`` already processed; no-op

    Idempotency is enforced two ways:
    1. ``MetaLeadEvent`` (PK = ``leadgen_id``). Duplicate inserts raise
       ``IntegrityError`` — the webhook view catches that earlier.
    2. ``Lead.meta_leadgen_id`` lookup as a defensive belt-and-braces check
       in case the event row got cleaned up but the Lead remains.

    The function is also resilient to webhook fixtures that omit fields the
    real Meta delivery would carry — missing values fall back to safe
    defaults (``Hinglish`` language, ``Meta Ads`` source, etc.).
    """
    expanded = expand_lead(meta_lead)

    # Belt + braces: even if the WebhookEvent row was wiped, never overwrite
    # an existing Lead with a duplicate insert.
    existing = Lead.objects.filter(meta_leadgen_id=expanded.leadgen_id).first()

    fields = {
        "name": expanded.name or (existing.name if existing else "Meta Lead"),
        "phone": expanded.phone or (existing.phone if existing else ""),
        "state": expanded.state or (existing.state if existing else ""),
        "city": expanded.city or (existing.city if existing else ""),
        "language": expanded.language or "Hinglish",
        "source": "Meta Ads",
        "campaign": expanded.campaign_id or (existing.campaign if existing else ""),
        "product_interest": expanded.product_interest
        or (existing.product_interest if existing else ""),
        "meta_leadgen_id": expanded.leadgen_id,
        "meta_page_id": expanded.page_id,
        "meta_form_id": expanded.form_id,
        "meta_ad_id": expanded.ad_id,
        "meta_campaign_id": expanded.campaign_id,
        "source_detail": expanded.source_detail or "Meta Ads",
        "raw_source_payload": dict(expanded.raw or {}),
    }

    if existing is not None:
        # Refresh attribution metadata + any newly-discovered field. Don't
        # downgrade existing values to blanks if the webhook is sparse.
        for key, value in fields.items():
            if value:
                setattr(existing, key, value)
        existing.save()
        action = "updated"
        lead = existing
    else:
        lead = Lead.objects.create(
            id=next_id("LD", Lead, base=10300),
            status=Lead.Status.NEW,
            quality=Lead.Quality.WARM,
            quality_score=50,
            assignee="",
            duplicate=False,
            created_at_label="just now",
            **fields,
        )
        action = "created"

    write_event(
        kind="lead.meta_ingested",
        text=f"Lead {lead.id} {action} from Meta Ads (leadgen {expanded.leadgen_id})",
        tone=AuditEvent.Tone.INFO,
        payload={
            "lead_id": lead.id,
            "action": action,
            "leadgen_id": expanded.leadgen_id,
            "page_id": expanded.page_id,
            "form_id": expanded.form_id,
            "ad_id": expanded.ad_id,
            "campaign_id": expanded.campaign_id,
        },
    )
    return lead, action


def record_meta_event(
    *,
    meta_lead: MetaLead,
    lead: Lead | None,
    error_message: str = "",
    payload: dict | None = None,
) -> MetaLeadEvent:
    """Persist the per-leadgen idempotency row.

    The webhook view is responsible for wrapping this in the same
    transaction as ``ingest_meta_lead`` so a failed ingest doesn't leave a
    stale ``ok`` event behind.
    """
    return MetaLeadEvent.objects.create(
        leadgen_id=meta_lead.leadgen_id,
        page_id=meta_lead.page_id,
        form_id=meta_lead.form_id,
        ad_id=meta_lead.ad_id,
        campaign_id=meta_lead.campaign_id,
        lead_id=getattr(lead, "id", "") or "",
        status=MetaLeadEvent.Status.ERROR if error_message else MetaLeadEvent.Status.OK,
        error_message=error_message[:5000] if error_message else "",
        payload=dict(payload or meta_lead.raw or {}),
    )
