"""Phase 16D — dict serializers (camelCase out). Phones are ALWAYS masked.

These are plain functions (project convention for read-only surfaces) rather
than DRF ModelSerializers, so the masking + field allow-list is explicit and a
raw phone can never leak through a wildcard field.
"""
from __future__ import annotations

from typing import Any

from .models import (
    ImportedCallingCampaign,
    ImportedCallQueueItem,
    ImportedDataRow,
    ImportedDataset,
)


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def mask_phone(value: str) -> str:
    """Return ``****<last4>`` — never the full number."""
    d = _digits(value)
    return f"****{d[-4:]}" if len(d) >= 4 else "****"


def serialize_dataset(ds: ImportedDataset) -> dict[str, Any]:
    return {
        "id": ds.pk,
        "name": ds.name,
        "sourceLabel": ds.source_label,
        "problemCategory": ds.problem_category,
        "originalFilename": ds.original_filename,
        "uploadedBy": ds.uploaded_by.username if ds.uploaded_by_id else None,
        "status": ds.status,
        "totalRows": ds.total_rows,
        "validRows": ds.valid_rows,
        "duplicateRows": ds.duplicate_rows,
        "invalidRows": ds.invalid_rows,
        "importedRows": ds.imported_rows,
        "createdAt": ds.created_at,
        "updatedAt": ds.updated_at,
    }


def serialize_row(row: ImportedDataRow) -> dict[str, Any]:
    return {
        "id": row.pk,
        "rowNumber": row.row_number,
        "name": row.raw_name,
        "phoneMasked": mask_phone(row.raw_phone),
        "problemCategory": row.problem_category,
        "city": row.city,
        "state": row.state,
        "product": row.product,
        "oldStatus": row.old_status,
        "lastOrderDate": row.last_order_date,
        "validationStatus": row.validation_status,
        "validationMessage": row.validation_message,
        "linkedLeadId": row.linked_lead_id,
        "linkedCustomerId": row.linked_customer_id,
    }


def serialize_campaign(c: ImportedCallingCampaign) -> dict[str, Any]:
    return {
        "id": c.pk,
        "name": c.name,
        "datasetId": c.dataset_id,
        "problemCategory": c.problem_category,
        "status": c.status,
        "assignedTeam": c.assigned_team,
        "totalContacts": c.total_contacts,
        "pendingCount": c.pending_count,
        "completedCount": c.completed_count,
        "interestedCount": c.interested_count,
        "notInterestedCount": c.not_interested_count,
        "callbackCount": c.callback_count,
        "wrongNumberCount": c.wrong_number_count,
        "orderCreatedCount": c.order_created_count,
        "createdBy": c.created_by.username if c.created_by_id else None,
        "createdAt": c.created_at,
        "updatedAt": c.updated_at,
    }


def serialize_queue_item(q: ImportedCallQueueItem) -> dict[str, Any]:
    row = q.data_row
    return {
        "id": q.pk,
        "campaignId": q.campaign_id,
        "dataRowId": q.data_row_id,
        "name": row.raw_name if row else "",
        "phoneMasked": mask_phone(row.raw_phone) if row else "****",
        "problemCategory": row.problem_category if row else "",
        "city": row.city if row else "",
        "state": row.state if row else "",
        "assignedAgent": q.assigned_agent.username if q.assigned_agent_id else None,
        "status": q.status,
        "lastOutcome": q.last_outcome,
        "callAttempts": q.call_attempts,
        "nextFollowUpAt": q.next_follow_up_at,
        "notes": q.notes,
        "escalationFlag": q.escalation_flag,
        "linkedOrderId": q.linked_order_id,
        "createdAt": q.created_at,
        "updatedAt": q.updated_at,
    }
