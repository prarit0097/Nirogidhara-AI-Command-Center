"""Phase 16D — Uploaded data → campaign → queue → order services.

Pure functions called by the views. Every external side effect is blocked:
no Vapi/AI call, no WhatsApp/Meta Cloud send, no Razorpay/PayU, no Delhivery,
no AI/LLM, no business Celery enqueue, no kill-switch / sandbox mutation. The
order-creation path reuses ``apps.orders.services.create_order`` which is a
pure DB insert (no provider). CSV content + raw phones are NEVER logged.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.audit.signals import write_event

from .models import (
    ImportedCallingCampaign,
    ImportedCallQueueItem,
    ImportedDataRow,
    ImportedDataset,
)

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


# Cap rows per upload to keep the request + table writes bounded (pilot scale).
MAX_IMPORT_ROWS = 5000

# Header auto-detection. Old/offline data uses inconsistent column names, so we
# map a wide set of aliases onto the canonical field names.
HEADER_ALIASES = {
    "name": "name",
    "full name": "name",
    "fullname": "name",
    "customer": "name",
    "customer name": "name",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "mobile no": "phone",
    "contact": "phone",
    "contact number": "phone",
    "whatsapp": "phone",
    "problem": "problem_category",
    "disease": "problem_category",
    "disease category": "problem_category",
    "category": "problem_category",
    "city": "city",
    "state": "state",
    "notes": "notes",
    "note": "notes",
    "remark": "notes",
    "remarks": "notes",
    "product": "product",
    "medicine": "product",
    "old status": "old_status",
    "status": "old_status",
    "last order date": "last_order_date",
    "last order": "last_order_date",
    "source": "source",
}


@dataclass
class _RowSample:
    row_number: int
    validation_status: str
    reason: str
    phone_last4: str


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _last4(value: str) -> str:
    d = _digits(value)
    return d[-4:] if len(d) >= 4 else "????"


def _detect_mapping(fieldnames: list[str]) -> dict[str, str]:
    """Return {canonical_field: actual_csv_header} for detected columns."""
    mapping: dict[str, str] = {}
    for header in fieldnames or []:
        key = (header or "").strip().lower()
        canonical = HEADER_ALIASES.get(key)
        if canonical and canonical not in mapping:
            mapping[canonical] = header
    return mapping


def _cell(row: dict[str, str], mapping: dict[str, str], field: str) -> str:
    header = mapping.get(field)
    if not header:
        return ""
    return (row.get(header) or "").strip()


@transaction.atomic
def parse_and_validate_dataset(
    *,
    raw_csv: str,
    name: str,
    by_user: "User",
    source_label: str = "",
    problem_category: str = "",
    original_filename: str = "",
) -> ImportedDataset:
    """Parse + validate a CSV blob into an ImportedDataset + ImportedDataRow rows.

    NEVER creates a Lead / Customer / Order during upload — only dataset + row
    rows. Validation per row:
      - missing phone (or no name) → missing_required
      - phone present but normalizes to < 10 digits → invalid_phone
      - normalized phone already seen earlier in this file → duplicate_in_file
      - normalized phone matches an existing Lead/Customer → duplicate_existing
      - else → valid
    """
    # Reuse the canonical CRM phone helpers so dedup matches the live Lead rules.
    from apps.crm.services import find_lead_by_phone, normalize_phone
    from apps.crm.models import Customer

    reader = csv.DictReader(io.StringIO(raw_csv or ""))
    mapping = _detect_mapping(list(reader.fieldnames or []))

    dataset = ImportedDataset.objects.create(
        name=(name or "Untitled dataset").strip()[:160],
        source_label=(source_label or "").strip()[:120],
        problem_category=(problem_category or "").strip()[:120],
        original_filename=(original_filename or "").strip()[:255],
        uploaded_by=by_user if getattr(by_user, "pk", None) else None,
        status=ImportedDataset.Status.READY,
    )

    seen_phones: set[str] = set()
    total = valid = duplicate = invalid = 0
    rows_to_create: list[ImportedDataRow] = []

    for idx, raw_row in enumerate(reader, start=1):
        if total >= MAX_IMPORT_ROWS:
            break
        total += 1

        name_val = _cell(raw_row, mapping, "name")
        phone_val = _cell(raw_row, mapping, "phone")
        category_val = _cell(raw_row, mapping, "problem_category") or problem_category
        normalized = normalize_phone(phone_val)

        status = ImportedDataRow.ValidationStatus.VALID
        message = ""

        if not phone_val or not name_val:
            status = ImportedDataRow.ValidationStatus.MISSING_REQUIRED
            missing = []
            if not name_val:
                missing.append("name")
            if not phone_val:
                missing.append("phone")
            message = f"Missing required: {', '.join(missing)}"
        elif len(normalized) < 10:
            status = ImportedDataRow.ValidationStatus.INVALID_PHONE
            message = "Phone does not normalize to a 10-digit number"
        elif normalized in seen_phones:
            status = ImportedDataRow.ValidationStatus.DUPLICATE_IN_FILE
            message = "Duplicate phone earlier in this file"
        elif (
            find_lead_by_phone(phone_val) is not None
            or Customer.objects.filter(phone__contains=normalized).exists()
        ):
            status = ImportedDataRow.ValidationStatus.DUPLICATE_EXISTING
            message = "Phone matches an existing Lead/Customer"
        else:
            status = ImportedDataRow.ValidationStatus.VALID

        if normalized and status in (
            ImportedDataRow.ValidationStatus.VALID,
            ImportedDataRow.ValidationStatus.DUPLICATE_IN_FILE,
            ImportedDataRow.ValidationStatus.DUPLICATE_EXISTING,
        ):
            seen_phones.add(normalized)

        if status == ImportedDataRow.ValidationStatus.VALID:
            valid += 1
        elif status in (
            ImportedDataRow.ValidationStatus.DUPLICATE_IN_FILE,
            ImportedDataRow.ValidationStatus.DUPLICATE_EXISTING,
        ):
            duplicate += 1
        else:
            invalid += 1

        rows_to_create.append(
            ImportedDataRow(
                dataset=dataset,
                row_number=idx,
                raw_name=name_val[:160],
                raw_phone=phone_val[:32],
                normalized_phone=normalized,
                problem_category=category_val[:120],
                city=_cell(raw_row, mapping, "city")[:80],
                state=_cell(raw_row, mapping, "state")[:60],
                notes=_cell(raw_row, mapping, "notes"),
                product=_cell(raw_row, mapping, "product")[:120],
                source_label=(_cell(raw_row, mapping, "source") or source_label)[:120],
                old_status=_cell(raw_row, mapping, "old_status")[:80],
                last_order_date=_cell(raw_row, mapping, "last_order_date")[:40],
                validation_status=status,
                validation_message=message[:200],
            )
        )

    ImportedDataRow.objects.bulk_create(rows_to_create)

    dataset.total_rows = total
    dataset.valid_rows = valid
    dataset.duplicate_rows = duplicate
    dataset.invalid_rows = invalid
    dataset.save(
        update_fields=["total_rows", "valid_rows", "duplicate_rows", "invalid_rows", "updated_at"]
    )

    # Non-PII audit — counts + detected columns only, never row content / phones.
    write_event(
        kind="imports.dataset.created",
        text=(
            f"Dataset #{dataset.pk} '{dataset.name}' uploaded: "
            f"{total} rows ({valid} valid, {duplicate} dup, {invalid} invalid)"
        ),
        payload={
            "dataset_id": dataset.pk,
            "total_rows": total,
            "valid_rows": valid,
            "duplicate_rows": duplicate,
            "invalid_rows": invalid,
            "detected_columns": sorted(mapping.keys()),
            "by": getattr(by_user, "username", ""),
        },
        user=by_user if getattr(by_user, "pk", None) else None,
    )
    return dataset


def dataset_error_samples(dataset: ImportedDataset, *, limit: int = 20) -> list[dict]:
    """Return up to ``limit`` non-valid row samples (phone masked to last-4)."""
    rows = (
        dataset.rows.exclude(validation_status=ImportedDataRow.ValidationStatus.VALID)
        .exclude(validation_status=ImportedDataRow.ValidationStatus.IMPORTED)
        .order_by("row_number")[:limit]
    )
    return [
        {
            "rowNumber": r.row_number,
            "validationStatus": r.validation_status,
            "reason": r.validation_message,
            "phoneLast4": _last4(r.raw_phone),
        }
        for r in rows
    ]


def problem_breakdown(dataset: ImportedDataset) -> list[dict]:
    """Problem-wise count of VALID rows in a dataset."""
    from django.db.models import Count

    rows = (
        dataset.rows.filter(validation_status=ImportedDataRow.ValidationStatus.VALID)
        .values("problem_category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    return [
        {"problemCategory": r["problem_category"] or "(uncategorised)", "count": r["count"]}
        for r in rows
    ]


@transaction.atomic
def create_campaign_from_dataset(
    *,
    dataset: ImportedDataset,
    by_user: "User",
    name: str = "",
    problem_category: str = "",
    assigned_team: str = "",
) -> ImportedCallingCampaign:
    """Create a calling campaign + one queue item per VALID dataset row."""
    campaign = ImportedCallingCampaign.objects.create(
        name=(name or f"{dataset.name} campaign").strip()[:160],
        dataset=dataset,
        problem_category=(problem_category or dataset.problem_category)[:120],
        status=ImportedCallingCampaign.Status.ACTIVE,
        assigned_team=(assigned_team or "")[:64],
        created_by=by_user if getattr(by_user, "pk", None) else None,
    )

    valid_rows = list(
        dataset.rows.filter(validation_status=ImportedDataRow.ValidationStatus.VALID)
    )
    queue_items = [
        ImportedCallQueueItem(
            campaign=campaign,
            data_row=row,
            status=ImportedCallQueueItem.Status.PENDING,
        )
        for row in valid_rows
    ]
    ImportedCallQueueItem.objects.bulk_create(queue_items)

    campaign.total_contacts = len(queue_items)
    campaign.pending_count = len(queue_items)
    campaign.save(update_fields=["total_contacts", "pending_count", "updated_at"])

    write_event(
        kind="imports.campaign.created",
        text=(
            f"Imported campaign #{campaign.pk} '{campaign.name}' created "
            f"with {len(queue_items)} contacts from dataset #{dataset.pk}"
        ),
        payload={
            "campaign_id": campaign.pk,
            "dataset_id": dataset.pk,
            "total_contacts": len(queue_items),
            "by": getattr(by_user, "username", ""),
        },
        user=by_user if getattr(by_user, "pk", None) else None,
    )
    return campaign


class QueueOutcomeError(ValueError):
    """Raised when an outcome value is not allowed."""


# Outcome → (queue status, campaign counter field or None, escalation flag).
# Counters are incremented at most once per item per outcome category by the
# caller recomputing from scratch is avoided — we adjust incrementally.
_OUTCOME_MAP: dict[str, dict] = {
    "interested": {"status": ImportedCallQueueItem.Status.INTERESTED, "escalation": ""},
    "not_interested": {"status": ImportedCallQueueItem.Status.NOT_INTERESTED, "escalation": ""},
    "callback": {"status": ImportedCallQueueItem.Status.CALLBACK, "escalation": ""},
    "wrong_number": {"status": ImportedCallQueueItem.Status.WRONG_NUMBER, "escalation": ""},
    "no_answer": {"status": ImportedCallQueueItem.Status.CALLED, "escalation": ""},
    "already_ordered": {"status": ImportedCallQueueItem.Status.CLOSED, "escalation": ""},
    "angry_escalation": {"status": ImportedCallQueueItem.Status.CALLED, "escalation": "senior_review"},
    "medical_emergency": {"status": ImportedCallQueueItem.Status.CALLED, "escalation": "medical_emergency"},
}

ALLOWED_OUTCOMES = tuple(_OUTCOME_MAP.keys())


@transaction.atomic
def record_queue_outcome(
    *,
    queue_item: ImportedCallQueueItem,
    outcome: str,
    by_user: "User",
    notes: str = "",
    next_follow_up_at=None,
) -> ImportedCallQueueItem:
    """Record a manual call outcome on a queue item. No provider is contacted."""
    outcome = (outcome or "").strip().lower()
    if outcome not in _OUTCOME_MAP:
        raise QueueOutcomeError(
            f"Unknown outcome '{outcome}'. Allowed: {', '.join(ALLOWED_OUTCOMES)}"
        )

    spec = _OUTCOME_MAP[outcome]
    campaign = queue_item.campaign

    queue_item.status = spec["status"]
    queue_item.last_outcome = outcome
    queue_item.escalation_flag = spec["escalation"]
    queue_item.call_attempts = (queue_item.call_attempts or 0) + 1
    if notes:
        queue_item.notes = notes[:2000]
    if next_follow_up_at is not None:
        queue_item.next_follow_up_at = next_follow_up_at
    queue_item.save()

    # Recompute campaign counters from the queue so they stay correct even when
    # an outcome is changed multiple times for the same item.
    _recompute_campaign_counters(campaign)

    write_event(
        kind="imports.queue.outcome_recorded",
        text=(
            f"Queue item #{queue_item.pk} (campaign #{campaign.pk}) "
            f"outcome: {outcome}"
        ),
        payload={
            "campaign_id": campaign.pk,
            "queue_item_id": queue_item.pk,
            "outcome": outcome,
            "escalation": spec["escalation"],
            "phone_last4": _last4(queue_item.data_row.raw_phone) if queue_item.data_row_id else "????",
            "by": getattr(by_user, "username", ""),
        },
        user=by_user if getattr(by_user, "pk", None) else None,
    )
    return queue_item


def _recompute_campaign_counters(campaign: ImportedCallingCampaign) -> None:
    qs = campaign.queue_items
    S = ImportedCallQueueItem.Status
    campaign.pending_count = qs.filter(status__in=[S.PENDING, S.ASSIGNED]).count()
    campaign.interested_count = qs.filter(status=S.INTERESTED).count()
    campaign.not_interested_count = qs.filter(status=S.NOT_INTERESTED).count()
    campaign.callback_count = qs.filter(status=S.CALLBACK).count()
    campaign.wrong_number_count = qs.filter(status=S.WRONG_NUMBER).count()
    campaign.order_created_count = qs.filter(status=S.ORDER_CREATED).count()
    campaign.completed_count = qs.exclude(status__in=[S.PENDING, S.ASSIGNED]).count()
    campaign.save(
        update_fields=[
            "pending_count",
            "interested_count",
            "not_interested_count",
            "callback_count",
            "wrong_number_count",
            "order_created_count",
            "completed_count",
            "updated_at",
        ]
    )


class QueueOrderError(ValueError):
    """Raised when an order cannot be created from a queue item."""


@transaction.atomic
def create_order_from_queue_item(
    *,
    queue_item: ImportedCallQueueItem,
    by_user: "User",
    product: str = "",
    amount: int = 3000,
    quantity: int = 1,
) -> "Any":
    """Create an internal Order for an INTERESTED queue item.

    Reuses ``apps.orders.services.create_order`` (a pure DB insert — no
    payment / courier / WhatsApp side effect). Links the new order back to the
    queue item + data row, best-effort links/creates a Lead, and flips the
    queue item to ``order_created``.
    """
    from apps.orders.models import Order
    from apps.orders.services import create_order

    if queue_item.status != ImportedCallQueueItem.Status.INTERESTED:
        raise QueueOrderError(
            "Order can only be created from an 'interested' queue item."
        )
    if queue_item.linked_order_id:
        raise QueueOrderError("This queue item already has a linked order.")

    row = queue_item.data_row
    if row is None or not row.raw_phone:
        raise QueueOrderError("Queue item has no contact phone to create an order.")

    order = create_order(
        customer_name=row.raw_name or "Imported customer",
        phone=row.raw_phone,
        product=(product or row.product or "Ayurvedic product")[:120],
        state=row.state or "",
        city=row.city or "",
        quantity=max(1, int(quantity or 1)),
        amount=max(0, int(amount or 0)),
        stage=Order.Stage.ORDER_PUNCHED,
        agent=getattr(by_user, "username", "")[:80],
    )

    # Best-effort link/create a Lead so the imported contact has CRM presence.
    _link_or_create_lead(row, by_user)

    queue_item.linked_order = order
    queue_item.status = ImportedCallQueueItem.Status.ORDER_CREATED
    queue_item.save(update_fields=["linked_order", "status", "updated_at"])

    row.validation_status = ImportedDataRow.ValidationStatus.IMPORTED
    row.save(update_fields=["validation_status", "linked_lead", "updated_at"])

    _recompute_campaign_counters(queue_item.campaign)

    write_event(
        kind="imports.order.created_from_queue",
        text=(
            f"Order {order.id} created from imported queue item #{queue_item.pk} "
            f"(campaign #{queue_item.campaign_id})"
        ),
        payload={
            "campaign_id": queue_item.campaign_id,
            "queue_item_id": queue_item.pk,
            "order_id": order.id,
            "phone_last4": _last4(row.raw_phone),
            "by": getattr(by_user, "username", ""),
        },
        user=by_user if getattr(by_user, "pk", None) else None,
    )
    return order


def _link_or_create_lead(row: ImportedDataRow, by_user: "User") -> None:
    """Link the data row to an existing Lead, or create one (best-effort)."""
    from apps.crm.services import (
        LeadDuplicateError,
        create_lead,
        find_lead_by_phone,
    )

    try:
        existing = find_lead_by_phone(row.raw_phone)
        if existing is not None:
            row.linked_lead = existing
            return
        lead = create_lead(
            name=row.raw_name or "Imported customer",
            phone=row.raw_phone,
            state=row.state or "",
            city=row.city or "",
            source=row.source_label or "Imported Data",
            disease_category=row.problem_category or "",
            notes=row.notes or "",
        )
        row.linked_lead = lead
    except LeadDuplicateError:
        existing = find_lead_by_phone(row.raw_phone)
        if existing is not None:
            row.linked_lead = existing
    except Exception:
        # Lead linkage is best-effort; never block order creation on it.
        return


def get_imports_overview() -> dict:
    """Read-only aggregate KPIs for the Phase 16D dashboard."""
    from django.db.models import Sum

    DS = ImportedDataset
    CAMP = ImportedCallingCampaign
    Q = ImportedCallQueueItem

    ds_agg = DS.objects.exclude(status=DS.Status.ARCHIVED).aggregate(
        valid=Sum("valid_rows"),
        dup=Sum("duplicate_rows"),
        invalid=Sum("invalid_rows"),
    )
    interested = Q.objects.filter(status=Q.Status.INTERESTED).count()
    order_created = Q.objects.filter(status=Q.Status.ORDER_CREATED).count()
    contacted = Q.objects.exclude(
        status__in=[Q.Status.PENDING, Q.Status.ASSIGNED]
    ).count()
    interested_rate = round((interested / contacted) * 100, 1) if contacted else 0.0

    return {
        "datasetCount": DS.objects.exclude(status=DS.Status.ARCHIVED).count(),
        "validContacts": ds_agg["valid"] or 0,
        "duplicateCount": ds_agg["dup"] or 0,
        "invalidCount": ds_agg["invalid"] or 0,
        "activeCampaigns": CAMP.objects.filter(status=CAMP.Status.ACTIVE).count(),
        "pendingCalls": Q.objects.filter(
            status__in=[Q.Status.PENDING, Q.Status.ASSIGNED]
        ).count(),
        "interestedRate": interested_rate,
        "orderCreatedCount": order_created,
    }
