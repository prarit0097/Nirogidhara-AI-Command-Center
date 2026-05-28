"""CRM write services — pure functions called by views and (eventually) tasks.

No DRF imports here; these functions take typed kwargs, mutate models, write
audit-ledger rows for events the post-save signals don't already cover, and
return the model instance. Views serialize and respond.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .integrations.meta_client import MetaLead, expand_lead
from .models import Customer, Lead, MetaLeadEvent


# Phase 16B — Lead duplicate detection raises this typed error so views can
# translate to a clean DRF 409 / 400 response. Carries the existing Lead's id
# so the operator can navigate to the duplicate.
class LeadDuplicateError(ValueError):
    """Raised when create_lead detects a duplicate.

    Phase 16B-Hotfix-2: Lead uniqueness is **phone-only**. ``field_name`` is
    always ``"phone"`` for the Lead create path; email is optional metadata
    and is NOT a uniqueness key.
    """

    def __init__(self, *, field_name: str, existing_lead_id: str, value_suffix: str = ""):
        self.field_name = field_name
        self.existing_lead_id = existing_lead_id
        self.value_suffix = value_suffix
        super().__init__(
            f"Duplicate {field_name}: lead {existing_lead_id} already exists"
        )

# Cross-app import only for the by_user type hint; runtime never imports User
# here so Django app loading order stays unaffected.
try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


def _phone_digits(phone: str) -> str:
    """Return only the digit characters of a phone string."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _phone_last4(phone: str) -> str:
    """Return last-4 digits for audit / error messages — never the full phone."""
    digits = _phone_digits(phone)
    return digits[-4:] if len(digits) >= 4 else "????"


def normalize_phone(phone: str) -> str:
    """Phase 16B-Hotfix-2 — canonical phone key for duplicate detection.

    Steps:
      - trim, drop spaces / dashes / brackets / dots / plus (keep digits only)
      - Indian-number prefix handling:
        - 12 digits starting with ``91`` (``91XXXXXXXXXX``) → last 10
        - 11 digits starting with ``0`` (``0XXXXXXXXXX``)   → last 10
        - 13 digits starting with ``910`` edge             → last 10
      - any other 10+ digit string → last 10 digits
      - shorter strings → the digits as-is (best effort)

    The canonical key is the last-10-digit local number, so ``+91 98765 43210``,
    ``919876543210``, ``098765 43210`` and ``9876543210`` all collapse to
    ``9876543210``. Returns ``""`` for an empty / digitless input.
    """
    digits = _phone_digits(phone)
    if not digits:
        return ""
    if len(digits) == 12 and digits.startswith("91"):
        return digits[-10:]
    if len(digits) == 11 and digits.startswith("0"):
        return digits[-10:]
    if len(digits) == 13 and digits.startswith("910"):
        return digits[-10:]
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def find_lead_by_phone(phone: str) -> "Lead | None":
    """Return an existing Lead whose normalized phone matches, else None.

    Phase 16B-Hotfix-2: the candidate set is narrowed by the 10-digit key via
    the existing ``crm_lead_phone_idx`` (``phone__contains``), then confirmed by
    normalizing each candidate in Python so formatting differences (``+91`` vs
    bare) collapse to the same key. Falls back to a digit-suffix scan for the
    short-number edge case.
    """
    key = normalize_phone(phone)
    if not key:
        return None
    # `phone__contains=key` cheaply catches the common stored shapes
    # (`+91XXXXXXXXXX`, `XXXXXXXXXX`) where the 10 digits are contiguous.
    for candidate in Lead.objects.filter(phone__contains=key).iterator():
        if normalize_phone(candidate.phone) == key:
            return candidate
    # Defensive fallback for heavily-formatted stored phones (dashes/spaces)
    # where the contiguous-substring filter above misses. Pilot-scale only.
    suffix = key[-4:]
    if len(suffix) == 4:
        for candidate in Lead.objects.filter(phone__contains=suffix).iterator():
            if normalize_phone(candidate.phone) == key:
                return candidate
    return None


def _check_lead_duplicate(*, phone: str, skip_dedup: bool = False) -> None:
    """Raise LeadDuplicateError if a Lead with the same normalized phone exists.

    Phase 16B-Hotfix-2: duplicate detection is **phone-only**. Email is
    optional metadata and is NOT a uniqueness key — the same email with a
    different phone must be allowed to create a new Lead.

    The Meta Lead Ads webhook ingest path passes ``skip_dedup=True`` because
    that path does its own ``meta_leadgen_id`` based idempotency check.
    """
    if skip_dedup:
        return
    if not (phone or "").strip():
        return
    existing = find_lead_by_phone(phone)
    if existing is not None:
        raise LeadDuplicateError(
            field_name="phone",
            existing_lead_id=existing.id,
            value_suffix=_phone_last4(phone),
        )


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
    # Phase 16B — new optional fields
    consent_call: bool = False,
    consent_whatsapp: bool = False,
    consent_marketing: bool = False,
    email: str = "",
    notes: str = "",
    disease_category: str = "",
    skip_dedup: bool = False,
) -> Lead:
    """Create a Lead with optional consent fields + phone-only duplicate detection.

    Phase 16B-Hotfix-2: raises ``LeadDuplicateError`` only when the normalized
    phone matches an existing Lead. Email is optional metadata — the same
    email with a different phone creates a new Lead. ``skip_dedup=True`` is
    used only by the Meta webhook ingest path (which has its own
    ``meta_leadgen_id`` based idempotency).
    """
    _check_lead_duplicate(phone=phone, skip_dedup=skip_dedup)
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
        consent_call=consent_call,
        consent_whatsapp=consent_whatsapp,
        consent_marketing=consent_marketing,
        email=(email or "").strip().lower(),
        notes=notes,
        disease_category=disease_category,
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
        # Phase 16B note: the Meta webhook path bypasses ``create_lead``'s
        # new duplicate-detection (it has its own ``meta_leadgen_id``
        # idempotency via ``MetaLeadEvent`` + the prior ``existing``
        # lookup above). Defaults for the new Phase 16B Lead fields fall
        # back to the model defaults (consent_call/whatsapp/marketing =
        # False, email/notes/disease_category = "").
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


# ----- Phase 16B — CSV Lead Import -----


@dataclass
class LeadImportRowError:
    """One malformed CSV row + its safe sanitised reason. NEVER contains
    raw phone digits beyond the last 4."""

    row_number: int
    reason: str
    phone_last4: str = ""


@dataclass
class LeadImportResult:
    """Aggregate result of a CSV import run."""

    total_rows: int = 0
    created_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    created_lead_ids: list[str] = field(default_factory=list)
    row_errors: list[LeadImportRowError] = field(default_factory=list)
    truncated_error_list: bool = False


# Max rows accepted per CSV upload (defensive — protects backend from a
# pathological 1-million-row upload). Phase 16B is internal-pilot scope.
LEAD_IMPORT_MAX_ROWS = 1000
LEAD_IMPORT_MAX_ERROR_ROWS = 50

# Canonical column names accepted in the CSV header (case-insensitive).
# Any of these → name field; phone → phone; etc.
_HEADER_ALIASES = {
    "name": "name",
    "full name": "name",
    "fullname": "name",
    "customer": "name",
    "customer name": "name",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "contact": "phone",
    "email": "email",
    "email address": "email",
    "state": "state",
    "city": "city",
    "language": "language",
    "source": "source",
    "campaign": "campaign",
    "product": "product_interest",
    "product interest": "product_interest",
    "interest": "product_interest",
    "disease": "disease_category",
    "disease category": "disease_category",
    "category": "disease_category",
    "notes": "notes",
    "note": "notes",
    "consent_call": "consent_call",
    "consent call": "consent_call",
    "consent_whatsapp": "consent_whatsapp",
    "consent whatsapp": "consent_whatsapp",
    "consent_marketing": "consent_marketing",
    "consent marketing": "consent_marketing",
}


def _truthy(value: str) -> bool:
    """Lenient boolean parser for CSV consent columns."""
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "t"}


def import_leads_csv(
    *,
    raw_csv: str,
    by_user: "User",
    default_source: str = "CSV Import",
) -> LeadImportResult:
    """Parse a CSV blob and create Lead rows safely.

    Rules:
      - Header row required.
      - Required columns: ``name``, ``phone``. Missing either → row error.
      - Optional columns map per ``_HEADER_ALIASES``.
      - Duplicate phones (across the CSV OR against existing Leads) are
        SKIPPED, NOT overwritten. Counted in ``duplicate_count``.
      - Row errors are capped at LEAD_IMPORT_MAX_ERROR_ROWS to keep the
        response payload small; ``truncated_error_list`` is set True past
        the cap.
      - NEVER sends WhatsApp, never calls a customer, never triggers any
        external provider. Only inserts Lead rows.
      - PII in the response is masked to phone last-4.
    """
    result = LeadImportResult()
    try:
        reader = csv.DictReader(io.StringIO(raw_csv))
    except Exception as exc:  # noqa: BLE001 - malformed CSV
        result.error_count = 1
        result.row_errors.append(
            LeadImportRowError(row_number=0, reason=f"Malformed CSV: {exc}")
        )
        return result

    if not reader.fieldnames:
        result.error_count = 1
        result.row_errors.append(
            LeadImportRowError(row_number=0, reason="CSV has no header row")
        )
        return result

    # Build a lowercased-header → canonical-column map for this CSV.
    header_map: dict[str, str] = {}
    for raw_header in reader.fieldnames:
        if raw_header is None:
            continue
        key = raw_header.strip().lower()
        if key in _HEADER_ALIASES:
            header_map[raw_header] = _HEADER_ALIASES[key]

    if "name" not in header_map.values() or "phone" not in header_map.values():
        result.error_count = 1
        result.row_errors.append(
            LeadImportRowError(
                row_number=0,
                reason="CSV missing required header(s): 'name' and 'phone'",
            )
        )
        return result

    # Track NORMALIZED phones SEEN within this CSV so two rows in the same
    # upload with the same phone (any formatting) get the second one
    # classified as a duplicate. Phase 16B-Hotfix-2: phone-only — email is
    # NOT a dedup key.
    seen_phones_in_csv: set[str] = set()

    for row_idx, raw_row in enumerate(reader, start=2):  # row 1 = header
        if result.total_rows >= LEAD_IMPORT_MAX_ROWS:
            result.error_count += 1
            if len(result.row_errors) < LEAD_IMPORT_MAX_ERROR_ROWS:
                result.row_errors.append(
                    LeadImportRowError(
                        row_number=row_idx,
                        reason=(
                            f"Row capped — Phase 16B max {LEAD_IMPORT_MAX_ROWS} rows per import"
                        ),
                    )
                )
            else:
                result.truncated_error_list = True
            continue
        result.total_rows += 1

        # Translate the row into canonical kwargs.
        canonical: dict[str, str] = {}
        for raw_header, raw_value in raw_row.items():
            if raw_header is None or raw_header not in header_map:
                continue
            canonical_key = header_map[raw_header]
            canonical[canonical_key] = (raw_value or "").strip()

        name = canonical.get("name", "")
        phone = canonical.get("phone", "")
        email = canonical.get("email", "").lower()

        if not name or not phone:
            result.error_count += 1
            if len(result.row_errors) < LEAD_IMPORT_MAX_ERROR_ROWS:
                result.row_errors.append(
                    LeadImportRowError(
                        row_number=row_idx,
                        reason="Missing required 'name' or 'phone'",
                        phone_last4=_phone_last4(phone),
                    )
                )
            else:
                result.truncated_error_list = True
            continue

        # In-CSV duplicate check — phone-only, normalized.
        phone_key = normalize_phone(phone)
        if phone_key and phone_key in seen_phones_in_csv:
            result.duplicate_count += 1
            if len(result.row_errors) < LEAD_IMPORT_MAX_ERROR_ROWS:
                result.row_errors.append(
                    LeadImportRowError(
                        row_number=row_idx,
                        reason="Duplicate phone within CSV",
                        phone_last4=_phone_last4(phone),
                    )
                )
            else:
                result.truncated_error_list = True
            continue

        if phone_key:
            seen_phones_in_csv.add(phone_key)

        try:
            lead = create_lead(
                name=name,
                phone=phone,
                state=canonical.get("state", ""),
                city=canonical.get("city", ""),
                language=canonical.get("language") or "Hinglish",
                source=canonical.get("source") or default_source,
                campaign=canonical.get("campaign", ""),
                product_interest=canonical.get("product_interest", ""),
                consent_call=_truthy(canonical.get("consent_call", "")),
                consent_whatsapp=_truthy(canonical.get("consent_whatsapp", "")),
                consent_marketing=_truthy(canonical.get("consent_marketing", "")),
                email=email,
                notes=canonical.get("notes", ""),
                disease_category=canonical.get("disease_category", ""),
            )
        except LeadDuplicateError:
            # Already-existing Lead in DB (same normalized phone). Count + skip.
            result.duplicate_count += 1
            if len(result.row_errors) < LEAD_IMPORT_MAX_ERROR_ROWS:
                result.row_errors.append(
                    LeadImportRowError(
                        row_number=row_idx,
                        reason="Duplicate phone of existing Lead",
                        phone_last4=_phone_last4(phone),
                    )
                )
            else:
                result.truncated_error_list = True
            continue
        except Exception as exc:  # noqa: BLE001 - per-row guard
            result.error_count += 1
            if len(result.row_errors) < LEAD_IMPORT_MAX_ERROR_ROWS:
                result.row_errors.append(
                    LeadImportRowError(
                        row_number=row_idx,
                        reason=str(exc)[:240],
                        phone_last4=_phone_last4(phone),
                    )
                )
            else:
                result.truncated_error_list = True
            continue

        result.created_count += 1
        result.created_lead_ids.append(lead.id)

    write_event(
        kind="lead.csv_import",
        text=(
            f"CSV lead import by {getattr(by_user, 'username', 'system')}: "
            f"{result.created_count} created, {result.duplicate_count} duplicates, "
            f"{result.error_count} errors"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "by": getattr(by_user, "username", ""),
            "total_rows": result.total_rows,
            "created_count": result.created_count,
            "duplicate_count": result.duplicate_count,
            "error_count": result.error_count,
        },
    )
    return result


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
