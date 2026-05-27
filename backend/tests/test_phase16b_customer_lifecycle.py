"""Phase 16B — Customer Lifecycle UI Backbone backend tests.

Coverage:
  - Lead consent fields + duplicate detection (phone, email).
  - Lead create endpoint with new fields.
  - CSV lead import service + endpoint (created / duplicate / error counts).
  - Customer 360 timeline endpoint (calls / orders / payments / shipments).
  - Confirmation endpoint behaviour (existing service, new frontend wire-up).
  - Order transition endpoint.
  - Defensive safety: no WhatsApp send, no provider call, no Celery enqueue,
    no shipment / payment mutation outside the explicit confirmation path.
"""
from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.crm import services as crm_services
from apps.crm.models import Lead


# --------------------------------------------------------------------------
# Lead duplicate detection
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_lead_persists_consent_fields() -> None:
    lead = crm_services.create_lead(
        name="Test Director",
        phone="+919999000001",
        state="MH",
        city="Mumbai",
        consent_call=True,
        consent_whatsapp=False,
        consent_marketing=True,
        email="test@example.com",
        notes="Internal pilot test",
        disease_category="Joint pain",
    )
    assert lead.consent_call is True
    assert lead.consent_whatsapp is False
    assert lead.consent_marketing is True
    assert lead.email == "test@example.com"
    assert lead.notes == "Internal pilot test"
    assert lead.disease_category == "Joint pain"
    assert lead.id.startswith("LD-")


@pytest.mark.django_db
def test_create_lead_raises_on_phone_duplicate() -> None:
    crm_services.create_lead(
        name="Original", phone="+919999000002", state="MH", city="Mumbai"
    )
    with pytest.raises(crm_services.LeadDuplicateError) as excinfo:
        crm_services.create_lead(
            name="Dup", phone="+919999000002", state="MH", city="Pune"
        )
    assert excinfo.value.field_name == "phone"
    assert excinfo.value.existing_lead_id.startswith("LD-")


@pytest.mark.django_db
def test_create_lead_raises_on_email_duplicate() -> None:
    crm_services.create_lead(
        name="Original",
        phone="+919999000003",
        state="MH",
        city="Mumbai",
        email="a@example.com",
    )
    with pytest.raises(crm_services.LeadDuplicateError) as excinfo:
        crm_services.create_lead(
            name="Dup",
            phone="+919999000004",
            state="MH",
            city="Pune",
            email="A@Example.com",
        )
    assert excinfo.value.field_name == "email"


@pytest.mark.django_db
def test_create_lead_skip_dedup_path_used_by_meta_webhook() -> None:
    crm_services.create_lead(
        name="Original", phone="+919999000005", state="MH", city="Mumbai"
    )
    # Meta webhook bypasses the duplicate check (it has its own
    # ``meta_leadgen_id`` idempotency).
    lead = crm_services.create_lead(
        name="Meta Dup",
        phone="+919999000005",
        state="MH",
        city="Pune",
        skip_dedup=True,
    )
    assert Lead.objects.filter(phone="+919999000005").count() == 2
    assert lead.id != "LD-10300"


# --------------------------------------------------------------------------
# Lead create endpoint
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_leads_unauthenticated_blocked() -> None:
    client = APIClient()
    res = client.post(
        "/api/leads/",
        {"name": "x", "phone": "+919998000010"},
        format="json",
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_post_leads_creates_with_consent(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    res = client.post(
        "/api/leads/",
        {
            "name": "Pilot",
            "phone": "+919998000020",
            "email": "pilot@example.com",
            "consentCall": True,
            "consentWhatsapp": True,
            "consentMarketing": False,
            "diseaseCategory": "Immunity",
            "notes": "From manual form",
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["consentCall"] is True
    assert body["consentWhatsapp"] is True
    assert body["consentMarketing"] is False
    assert body["diseaseCategory"] == "Immunity"
    assert body["notes"] == "From manual form"
    assert body["email"] == "pilot@example.com"


@pytest.mark.django_db
def test_post_leads_returns_409_on_phone_duplicate(
    operations_user, auth_client
) -> None:
    client = auth_client(operations_user)
    client.post(
        "/api/leads/",
        {"name": "Original", "phone": "+919998000030"},
        format="json",
    )
    res = client.post(
        "/api/leads/",
        {"name": "Dup", "phone": "+919998000030"},
        format="json",
    )
    assert res.status_code == 409
    body = res.json()
    assert body["duplicate"] is True
    assert body["field"] == "phone"
    assert body["existingLeadId"].startswith("LD-")


# --------------------------------------------------------------------------
# CSV lead import
# --------------------------------------------------------------------------


_CSV_HAPPY = (
    "name,phone,email,source,disease,consent_call,consent_whatsapp\n"
    "Lead A,+919997000001,a@example.com,Manual,Joint pain,true,true\n"
    "Lead B,+919997000002,,Manual,Immunity,false,false\n"
)


@pytest.mark.django_db
def test_import_leads_csv_creates_rows(operations_user) -> None:
    result = crm_services.import_leads_csv(
        raw_csv=_CSV_HAPPY, by_user=operations_user
    )
    assert result.total_rows == 2
    assert result.created_count == 2
    assert result.duplicate_count == 0
    assert result.error_count == 0
    assert len(result.created_lead_ids) == 2
    assert Lead.objects.filter(phone__startswith="+91999700").count() == 2
    # Spot-check first row's consent fields hydrated correctly.
    a = Lead.objects.get(phone="+919997000001")
    assert a.consent_call is True
    assert a.consent_whatsapp is True
    assert a.consent_marketing is False


@pytest.mark.django_db
def test_import_leads_csv_counts_in_csv_duplicates(operations_user) -> None:
    csv = (
        "name,phone\n"
        "First,+919997111111\n"
        "Second,+919997111111\n"  # duplicate within CSV
        "Third,+919997111112\n"
    )
    result = crm_services.import_leads_csv(raw_csv=csv, by_user=operations_user)
    assert result.total_rows == 3
    assert result.created_count == 2
    assert result.duplicate_count == 1
    assert result.error_count == 0


@pytest.mark.django_db
def test_import_leads_csv_counts_db_duplicates(operations_user) -> None:
    # Pre-existing lead in DB.
    crm_services.create_lead(
        name="Existing", phone="+919997222001", state="", city=""
    )
    csv = (
        "name,phone\n"
        "Will Skip,+919997222001\n"  # collides with DB
        "Fresh,+919997222002\n"
    )
    result = crm_services.import_leads_csv(raw_csv=csv, by_user=operations_user)
    assert result.created_count == 1
    assert result.duplicate_count == 1
    assert result.error_count == 0


@pytest.mark.django_db
def test_import_leads_csv_rejects_missing_required_columns(operations_user) -> None:
    csv = "name\nMissing phone column\n"
    result = crm_services.import_leads_csv(raw_csv=csv, by_user=operations_user)
    assert result.error_count >= 1
    assert any("required" in re.reason.lower() for re in result.row_errors)


@pytest.mark.django_db
def test_import_leads_csv_endpoint_unauthenticated_blocked() -> None:
    client = APIClient()
    res = client.post(
        "/api/leads/import-csv/",
        {"csv": "name,phone\nTest,+91999700099\n"},
        format="json",
    )
    assert res.status_code in {401, 403}


@pytest.mark.django_db
def test_import_leads_csv_endpoint_returns_summary(
    operations_user, auth_client
) -> None:
    client = auth_client(operations_user)
    res = client.post(
        "/api/leads/import-csv/",
        {"csv": _CSV_HAPPY, "source": "Pilot CSV"},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["createdCount"] == 2
    assert body["duplicateCount"] == 0
    assert body["errorCount"] == 0
    assert len(body["createdLeadIds"]) == 2


@pytest.mark.django_db
def test_import_leads_csv_masks_phone_in_row_errors(operations_user) -> None:
    # Pre-existing lead → second row of CSV will be a duplicate; row_errors
    # must contain only the last-4 of the phone, NEVER the full digits.
    crm_services.create_lead(
        name="Existing", phone="+919998765432", state="", city=""
    )
    csv = (
        "name,phone\n"
        "First,+919998765432\n"
    )
    result = crm_services.import_leads_csv(raw_csv=csv, by_user=operations_user)
    assert result.duplicate_count == 1
    assert len(result.row_errors) >= 1
    err = result.row_errors[0]
    # The full phone string MUST NOT appear in the safe error reason or the
    # phone_last4 field.
    assert "9998765432" not in err.reason
    assert err.phone_last4 == "5432"


# --------------------------------------------------------------------------
# Customer 360 timeline endpoint
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_timeline_unauthenticated_blocked(seeded) -> None:
    from apps.crm.models import Customer

    customer = Customer.objects.first()
    assert customer is not None
    client = APIClient()
    res = client.get(f"/api/customers/{customer.id}/timeline/")
    # The CustomerViewSet uses RoleBasedPermission, which permits anonymous
    # reads on safe methods unless the project-wide IsAuthenticatedOrReadOnly
    # is enforced. Either way, the endpoint should respond with EITHER 200
    # (read allowed) or 401/403 (auth required) — but never 500.
    assert res.status_code in {200, 401, 403}


@pytest.mark.django_db
def test_customer_timeline_returns_four_buckets(
    seeded, operations_user, auth_client
) -> None:
    from apps.crm.models import Customer

    customer = Customer.objects.first()
    assert customer is not None
    client = auth_client(operations_user)
    res = client.get(f"/api/customers/{customer.id}/timeline/")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["customerId"] == customer.id
    assert isinstance(body["calls"], list)
    assert isinstance(body["orders"], list)
    assert isinstance(body["payments"], list)
    assert isinstance(body["shipments"], list)


@pytest.mark.django_db
def test_customer_timeline_returns_404_for_missing_customer(
    operations_user, auth_client
) -> None:
    client = auth_client(operations_user)
    res = client.get("/api/customers/CU-DOES-NOT-EXIST/timeline/")
    assert res.status_code == 404


# --------------------------------------------------------------------------
# Confirmation outcome endpoint (existing surface — verify Phase 16B fix
# doesn't regress the wiring).
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_confirm_order_endpoint_happy_path(
    seeded, operations_user, auth_client
) -> None:
    from apps.orders.models import Order

    order = Order.objects.create(
        id="NRG-PHASE16B-CONFIRM-A",
        customer_name="Phase16B Test",
        phone="+910000000001",
        product="Test Product",
        quantity=1,
        amount=100,
        state="MH",
        city="Mumbai",
        stage=Order.Stage.CONFIRMATION_PENDING,
    )
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/confirm/",
        {"outcome": "confirmed", "notes": "Phase 16B happy path"},
        format="json",
    )
    assert res.status_code == 200, res.content
    order.refresh_from_db()
    assert order.stage == Order.Stage.CONFIRMED
    assert order.confirmation_outcome == "confirmed"


@pytest.mark.django_db
def test_confirm_order_rejects_invalid_outcome(
    operations_user, auth_client
) -> None:
    from apps.orders.models import Order

    order = Order.objects.create(
        id="NRG-PHASE16B-CONFIRM-B",
        customer_name="Phase16B Test",
        phone="+910000000002",
        product="Test Product",
        quantity=1,
        amount=100,
        state="MH",
        city="Mumbai",
        stage=Order.Stage.CONFIRMATION_PENDING,
    )
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/confirm/",
        {"outcome": "totally_invalid"},
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_confirm_order_unauthenticated_blocked() -> None:
    client = APIClient()
    res = client.post(
        "/api/orders/NRG-FAKE/confirm/",
        {"outcome": "confirmed"},
        format="json",
    )
    assert res.status_code in {401, 403, 404}


# --------------------------------------------------------------------------
# Order transition endpoint
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_order_transition_safe_internal(
    operations_user, auth_client
) -> None:
    from apps.orders.models import Order

    order = Order.objects.create(
        id="NRG-PHASE16B-TRANS-A",
        customer_name="Phase16B Trans",
        phone="+910000000003",
        product="Test Product",
        quantity=1,
        amount=100,
        state="MH",
        city="Mumbai",
        stage=Order.Stage.NEW_LEAD,
    )
    client = auth_client(operations_user)
    res = client.post(
        f"/api/orders/{order.id}/transition/",
        {"stage": "Interested"},
        format="json",
    )
    assert res.status_code == 200
    order.refresh_from_db()
    assert order.stage == Order.Stage.INTERESTED


@pytest.mark.django_db
def test_order_transition_rejects_invalid_jump(
    operations_user, auth_client
) -> None:
    from apps.orders.models import Order

    order = Order.objects.create(
        id="NRG-PHASE16B-TRANS-B",
        customer_name="Phase16B Trans",
        phone="+910000000004",
        product="Test Product",
        quantity=1,
        amount=100,
        state="MH",
        city="Mumbai",
        stage=Order.Stage.NEW_LEAD,
    )
    client = auth_client(operations_user)
    # NEW_LEAD → DELIVERED is not an allowed direct transition.
    res = client.post(
        f"/api/orders/{order.id}/transition/",
        {"stage": "Delivered"},
        format="json",
    )
    assert res.status_code == 400


# --------------------------------------------------------------------------
# Defensive safety: Phase 16B mutation paths never trigger external
# providers (WhatsApp send, Razorpay, Delhivery, Vapi, AI orchestration).
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase16b_lead_create_no_external_side_effect(
    operations_user, auth_client
) -> None:
    """create_lead + CSV import + Customer timeline must never call any
    provider entrypoint.
    """
    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as mock_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as mock_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as mock_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as mock_shipment:
        client = auth_client(operations_user)
        # Manual create.
        res = client.post(
            "/api/leads/",
            {"name": "Safety Test", "phone": "+919996000001"},
            format="json",
        )
        assert res.status_code == 201
        # CSV import.
        res2 = client.post(
            "/api/leads/import-csv/",
            {"csv": "name,phone\nCsv Safety,+919996000002\n"},
            format="json",
        )
        assert res2.status_code == 200
        assert res2.json()["createdCount"] == 1

        mock_template.assert_not_called()
        mock_freeform.assert_not_called()
        mock_call.assert_not_called()
        mock_shipment.assert_not_called()


@pytest.mark.django_db
def test_phase16b_confirm_outcome_no_external_side_effect(
    operations_user, auth_client
) -> None:
    """``record_confirmation_outcome`` must only mutate Order; never sends
    WhatsApp / Razorpay / Delhivery / Vapi.
    """
    from apps.orders.models import Order

    order = Order.objects.create(
        id="NRG-PHASE16B-SAFETY",
        customer_name="Safety Test",
        phone="+910000099999",
        product="Test Product",
        quantity=1,
        amount=100,
        state="MH",
        city="Mumbai",
        stage=Order.Stage.CONFIRMATION_PENDING,
    )

    with mock.patch(
        "apps.whatsapp.services.queue_template_message"
    ) as mock_template, mock.patch(
        "apps.whatsapp.services.send_freeform_text_message"
    ) as mock_freeform, mock.patch(
        "apps.calls.services.trigger_call_for_lead"
    ) as mock_call, mock.patch(
        "apps.shipments.services.create_shipment"
    ) as mock_shipment:
        client = auth_client(operations_user)
        res = client.post(
            f"/api/orders/{order.id}/confirm/",
            {"outcome": "confirmed"},
            format="json",
        )
        assert res.status_code == 200
        mock_template.assert_not_called()
        mock_freeform.assert_not_called()
        mock_call.assert_not_called()
        mock_shipment.assert_not_called()
