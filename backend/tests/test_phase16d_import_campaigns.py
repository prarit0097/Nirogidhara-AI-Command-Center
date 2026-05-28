"""Phase 16D — Uploaded Customer Data Campaigns + Calling Lifecycle tests.

Coverage:
  - Auth required for upload / list / campaign / queue / outcome.
  - CSV upload creates a dataset + rows with correct valid/duplicate/invalid counts.
  - Invalid phone, missing required, duplicate-in-file, duplicate-existing each
    classified correctly. Email is NOT a dedup key (same email + new phone OK).
  - Create campaign from valid rows creates one queue item per valid row.
  - Record outcome updates the queue item + campaign counters.
  - Interested → create internal Order via the safe order service (no provider).
  - Medical emergency / angry outcomes set escalation flags.
  - Permissions: non-admin cannot upload or create a campaign; viewer cannot
    record outcomes; operations (calling agent) can.
  - Defensive: no WhatsApp / payment / courier / Vapi / provider call;
    RuntimeKillSwitch + SandboxState untouched.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.crm import services as crm_services
from apps.crm.models import Lead
from apps.data_imports.models import (
    ImportedCallingCampaign,
    ImportedCallQueueItem,
    ImportedDataRow,
    ImportedDataset,
)
from apps.orders.models import Order

UPLOAD = "/api/v1/imports/datasets/upload/"
DATASETS = "/api/v1/imports/datasets/"
CAMPAIGNS = "/api/v1/imports/campaigns/"
OVERVIEW = "/api/v1/imports/overview/"


@pytest.fixture
def director_user(db):
    user = User.objects.create_user(
        username="d16d", password="d16d12345", email="d16d@nirogidhara.test"
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _csv(rows: list[str]) -> str:
    header = "name,phone,disease,city,state,notes,email"
    return "\n".join([header, *rows])


# Valid, invalid-phone, missing-name, dup-in-file, (dup-existing added per-test).
SAMPLE_ROWS = [
    "Ramesh,+919812345678,Joint pain,Mumbai,MH,old customer,a@x.com",
    "Suresh,12345,Immunity,Pune,MH,bad phone,b@x.com",       # invalid_phone
    ",+919811111111,Weight,Delhi,DL,no name,c@x.com",         # missing_required
    "Ramesh Again,9812345678,Joint pain,Mumbai,MH,dup,a2@x.com",  # dup_in_file
]


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_requires_auth() -> None:
    res = APIClient().post(UPLOAD, {"name": "x", "csv": _csv(SAMPLE_ROWS)}, format="json")
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_datasets_list_requires_auth() -> None:
    assert APIClient().get(DATASETS).status_code in {401, 403}


@pytest.mark.django_db
def test_overview_requires_auth() -> None:
    assert APIClient().get(OVERVIEW).status_code in {401, 403}


# --------------------------------------------------------------------------
# Upload + validation
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_creates_dataset_and_classifies_rows(director_user, auth_client) -> None:
    res = auth_client(director_user).post(
        UPLOAD,
        {"name": "Old joint-pain data", "csv": _csv(SAMPLE_ROWS), "problemCategory": "Joint pain"},
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["totalRows"] == 4
    assert body["validRows"] == 1
    assert body["invalidRows"] == 2  # invalid_phone + missing_required
    assert body["duplicateRows"] == 1  # duplicate_in_file

    dataset = ImportedDataset.objects.get(pk=body["id"])
    statuses = sorted(dataset.rows.values_list("validation_status", flat=True))
    assert statuses == [
        "duplicate_in_file",
        "invalid_phone",
        "missing_required",
        "valid",
    ]
    # Error samples never expose full phone — masked to last-4.
    for sample in body["errorSamples"]:
        assert "phoneLast4" in sample
        assert len(sample["phoneLast4"]) <= 4


@pytest.mark.django_db
def test_upload_detects_existing_lead_duplicate(director_user, auth_client) -> None:
    crm_services.create_lead(
        name="Existing", phone="+919812345678", state="MH", city="Mumbai"
    )
    res = auth_client(director_user).post(
        UPLOAD,
        {"name": "ds", "csv": _csv(["Ramesh,9812345678,Joint pain,Mumbai,MH,,a@x.com"])},
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["duplicateRows"] == 1
    assert body["validRows"] == 0
    row = ImportedDataRow.objects.get(dataset_id=body["id"])
    assert row.validation_status == "duplicate_existing"


@pytest.mark.django_db
def test_upload_same_email_different_phone_both_valid(director_user, auth_client) -> None:
    """Email is NOT a dedup key — two different phones with the same email are
    both valid."""
    rows = [
        "Aaa,+919800000001,Immunity,Pune,MH,,shared@x.com",
        "Bbb,+919800000002,Immunity,Pune,MH,,shared@x.com",
    ]
    res = auth_client(director_user).post(
        UPLOAD, {"name": "ds", "csv": _csv(rows)}, format="json"
    )
    assert res.status_code == 201, res.content
    assert res.json()["validRows"] == 2


@pytest.mark.django_db
def test_upload_blank_csv_rejected(director_user, auth_client) -> None:
    res = auth_client(director_user).post(
        UPLOAD, {"name": "ds", "csv": "   "}, format="json"
    )
    assert res.status_code == 400
    assert res.json()["field"] == "csv"


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_non_admin_cannot_upload(operations_user, viewer_user, auth_client) -> None:
    for user in (operations_user, viewer_user):
        res = auth_client(user).post(
            UPLOAD, {"name": "ds", "csv": _csv(SAMPLE_ROWS)}, format="json"
        )
        assert res.status_code == 403, (user.role, res.content)


@pytest.mark.django_db
def test_non_admin_can_read_datasets(viewer_user, auth_client) -> None:
    assert auth_client(viewer_user).get(DATASETS).status_code == 200


# --------------------------------------------------------------------------
# Campaign + queue
# --------------------------------------------------------------------------


def _upload_dataset(client) -> int:
    res = client.post(
        UPLOAD,
        {"name": "ds", "csv": _csv(SAMPLE_ROWS)},
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()["id"]


@pytest.mark.django_db
def test_create_campaign_creates_one_queue_item_per_valid_row(
    director_user, auth_client
) -> None:
    client = auth_client(director_user)
    ds_id = _upload_dataset(client)
    res = client.post(
        f"{DATASETS}{ds_id}/create-campaign/", {"name": "Campaign A"}, format="json"
    )
    assert res.status_code == 201, res.content
    campaign = res.json()
    assert campaign["totalContacts"] == 1  # only 1 valid row
    assert campaign["pendingCount"] == 1
    items = ImportedCallQueueItem.objects.filter(campaign_id=campaign["id"])
    assert items.count() == 1
    assert items.first().status == "pending"


@pytest.mark.django_db
def test_create_campaign_non_admin_blocked(
    director_user, operations_user, auth_client
) -> None:
    ds_id = _upload_dataset(auth_client(director_user))
    res = auth_client(operations_user).post(
        f"{DATASETS}{ds_id}/create-campaign/", {"name": "x"}, format="json"
    )
    assert res.status_code == 403


@pytest.mark.django_db
def test_create_campaign_no_valid_rows_rejected(director_user, auth_client) -> None:
    client = auth_client(director_user)
    # All-invalid CSV.
    res = client.post(
        UPLOAD, {"name": "bad", "csv": _csv(["Suresh,123,Immunity,Pune,MH,,b@x.com"])}, format="json"
    )
    ds_id = res.json()["id"]
    res2 = client.post(f"{DATASETS}{ds_id}/create-campaign/", {}, format="json")
    assert res2.status_code == 400
    assert res2.json()["detail"] == "no_valid_rows"


# --------------------------------------------------------------------------
# Outcome recording
# --------------------------------------------------------------------------


def _make_campaign_with_item(client) -> int:
    ds_id = _upload_dataset(client)
    res = client.post(f"{DATASETS}{ds_id}/create-campaign/", {"name": "C"}, format="json")
    campaign_id = res.json()["id"]
    item = ImportedCallQueueItem.objects.filter(campaign_id=campaign_id).first()
    return item.pk


@pytest.mark.django_db
def test_record_outcome_interested(director_user, auth_client) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/outcome/",
        {"outcome": "interested", "notes": "wants product"},
        format="json",
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["status"] == "interested"
    assert body["lastOutcome"] == "interested"
    assert body["callAttempts"] == 1


@pytest.mark.django_db
def test_record_outcome_medical_emergency_sets_escalation(
    director_user, auth_client
) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/outcome/",
        {"outcome": "medical_emergency"},
        format="json",
    )
    assert res.status_code == 200, res.content
    assert res.json()["escalationFlag"] == "medical_emergency"


@pytest.mark.django_db
def test_record_outcome_angry_sets_senior_review(director_user, auth_client) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/outcome/",
        {"outcome": "angry_escalation"},
        format="json",
    )
    assert res.json()["escalationFlag"] == "senior_review"


@pytest.mark.django_db
def test_record_outcome_invalid_rejected(director_user, auth_client) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/outcome/", {"outcome": "bogus"}, format="json"
    )
    assert res.status_code == 400
    assert res.json()["field"] == "outcome"


@pytest.mark.django_db
def test_outcome_requires_auth() -> None:
    assert (
        APIClient()
        .post("/api/v1/imports/queue/1/outcome/", {"outcome": "interested"}, format="json")
        .status_code
        in {401, 403}
    )


@pytest.mark.django_db
def test_outcome_viewer_blocked_operations_allowed(
    director_user, viewer_user, operations_user, auth_client
) -> None:
    item_id = _make_campaign_with_item(auth_client(director_user))
    # Viewer cannot record.
    res_v = auth_client(viewer_user).post(
        f"/api/v1/imports/queue/{item_id}/outcome/", {"outcome": "callback"}, format="json"
    )
    assert res_v.status_code == 403
    # Operations (calling agent) can record.
    res_o = auth_client(operations_user).post(
        f"/api/v1/imports/queue/{item_id}/outcome/", {"outcome": "callback"}, format="json"
    )
    assert res_o.status_code == 200, res_o.content


# --------------------------------------------------------------------------
# Order creation from interested queue item
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_order_from_interested_item(director_user, auth_client) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)
    client.post(
        f"/api/v1/imports/queue/{item_id}/outcome/", {"outcome": "interested"}, format="json"
    )
    orders_before = Order.objects.count()
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/create-order/",
        {"product": "Joint Care", "amount": 3000},
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["orderId"].startswith("NRG-")
    assert body["orderStage"] == "Order Punched"
    assert Order.objects.count() == orders_before + 1

    item = ImportedCallQueueItem.objects.get(pk=item_id)
    assert item.status == "order_created"
    assert item.linked_order_id == body["orderId"]
    # The data row is linked to a Lead (best-effort CRM presence).
    assert item.data_row.validation_status == "imported"
    assert Lead.objects.filter(id=item.data_row.linked_lead_id).exists()


@pytest.mark.django_db
def test_create_order_requires_interested_status(director_user, auth_client) -> None:
    client = auth_client(director_user)
    item_id = _make_campaign_with_item(client)  # status=pending
    res = client.post(
        f"/api/v1/imports/queue/{item_id}/create-order/", {}, format="json"
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "order_not_allowed"


# --------------------------------------------------------------------------
# Defensive — no provider/business side effects, safety state untouched
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16d_full_flow_triggers_no_provider_side_effect(
    director_user, auth_client
) -> None:
    from apps.ai_governance.sandbox import is_sandbox_enabled
    from apps.saas.models import RuntimeKillSwitch

    sandbox_before = is_sandbox_enabled()
    killswitch_before = RuntimeKillSwitch.objects.count()

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as wa_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as wa_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as vapi_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as courier:
        client = auth_client(director_user)
        ds_id = _upload_dataset(client)
        camp = client.post(
            f"{DATASETS}{ds_id}/create-campaign/", {"name": "C"}, format="json"
        ).json()
        item = ImportedCallQueueItem.objects.filter(campaign_id=camp["id"]).first()
        client.post(
            f"/api/v1/imports/queue/{item.pk}/outcome/",
            {"outcome": "interested"},
            format="json",
        )
        client.post(
            f"/api/v1/imports/queue/{item.pk}/create-order/", {}, format="json"
        )

    wa_template.assert_not_called()
    wa_freeform.assert_not_called()
    vapi_call.assert_not_called()
    courier.assert_not_called()

    assert is_sandbox_enabled() == sandbox_before
    assert RuntimeKillSwitch.objects.count() == killswitch_before


@pytest.mark.django_db
def test_overview_returns_kpis(director_user, auth_client) -> None:
    client = auth_client(director_user)
    _upload_dataset(client)
    res = client.get(OVERVIEW)
    assert res.status_code == 200, res.content
    body = res.json()
    for key in (
        "datasetCount",
        "validContacts",
        "duplicateCount",
        "invalidCount",
        "activeCampaigns",
        "pendingCalls",
        "interestedRate",
        "orderCreatedCount",
    ):
        assert key in body
    assert body["datasetCount"] >= 1
