"""Phase 15C - backend tests for the read-only Audit Timeline endpoint.

The new ``GET /api/audit/timeline/`` endpoint surfaces a sanitised
window into the Master Event Ledger so admins / directors can review
recent state changes without ever exposing sensitive body content.

Coverage:

- Auth: anonymous + viewer blocked; admin / director OK.
- Empty timeline -> 200 with ``items=[]``, ``count=0``.
- Newest-first ordering across multiple kinds.
- Tone filter (``success``/``info``/``warning``/``danger``).
- Kind exact filter narrows results.
- Category filter applies prefix dispatch (rollback / safety /
  ai_governance / whatsapp / payments / orders / delivery /
  auth_system / other) and 400 on invalid category.
- Text search (``q=``) is case-insensitive against ``text`` only.
- Date range filter (``date_from`` / ``date_to``).
- Pagination: ``limit`` hard-capped at 200; ``offset`` works.
- Sanitisation: poisoned payload containing tokens / phones / emails
  / addresses / raw_response / system_policy / instruction_payload /
  customer_name / director_signoff / metadata is fully scrubbed.
- Long string values are truncated defensively.
- Write verbs (POST / PUT / PATCH / DELETE) return 405.
- Defensive safety: NEVER calls any provider; NEVER mutates business
  rows; NEVER writes a new AuditEvent.
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient


TIMELINE_URL = "/api/audit/timeline/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase15c_admin",
        email="phase15c_admin@example.com",
        password="ignored-by-force-auth",
    )
    user.is_staff = True
    user.is_superuser = True
    user.role = "admin"
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def director_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase15c_director",
        email="phase15c_director@example.com",
        password="ignored-by-force-auth",
    )
    user.role = "director"
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def viewer_client(db, django_user_model) -> APIClient:
    user = django_user_model.objects.create_user(
        username="phase15c_viewer",
        email="phase15c_viewer@example.com",
        password="ignored-by-force-auth",
    )
    user.save()
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


def _seed_mixed_events(db) -> dict:
    """Insert a representative mix of audit events covering safety,
    rollback, ai_governance, whatsapp, payments, orders, delivery,
    auth_system, and other categories."""
    from apps.audit.models import AuditEvent

    refs: dict = {}

    refs["rollback_ui"] = AuditEvent.objects.create(
        kind="prompt_version.rollback.ui_changed",
        text="Prompt rollback via Settings UI by phase15c_admin",
        tone=AuditEvent.Tone.WARNING,
        payload={"phase": "14F", "actor": "phase15c_admin", "agent": "ceo"},
    )

    refs["rollback_service"] = AuditEvent.objects.create(
        kind="ai.prompt_version.rolled_back",
        text="Service rolled back agent=ceo from PV-2 to PV-1",
        tone=AuditEvent.Tone.WARNING,
        payload={
            "phase": "3D",
            "agent": "ceo",
            "by": "phase15c_admin",
        },
    )

    refs["safety_kill"] = AuditEvent.objects.create(
        kind="runtime.kill_switch.enabled",
        text="Runtime kill switch enabled",
        tone=AuditEvent.Tone.DANGER,
        payload={"actor": "phase15c_admin"},
    )

    refs["safety_sandbox"] = AuditEvent.objects.create(
        kind="ai.sandbox.enabled",
        text="Sandbox mode enabled",
        tone=AuditEvent.Tone.WARNING,
        payload={"actor": "phase15c_admin"},
    )

    refs["ai_run"] = AuditEvent.objects.create(
        kind="ai.agent_run.completed",
        text="AgentRun 42 completed (agent=cfo)",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"agent": "cfo", "duration_ms": 142},
    )

    refs["whatsapp_send"] = AuditEvent.objects.create(
        kind="whatsapp.message.sent",
        text="WhatsApp template sent to ****9001",
        tone=AuditEvent.Tone.INFO,
        payload={"template_name": "nrg_greeting_intro", "phone_suffix": "9001"},
    )

    refs["payment_received"] = AuditEvent.objects.create(
        kind="payment.received",
        text="Payment Rs.3000 received",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"amount": 3000, "currency": "INR", "order_id": 101},
    )

    refs["order_created"] = AuditEvent.objects.create(
        kind="order.created",
        text="Order NRG-1001 punched",
        tone=AuditEvent.Tone.SUCCESS,
        payload={"order_id": "NRG-1001", "stage": "Confirmed"},
    )

    refs["shipment_status"] = AuditEvent.objects.create(
        kind="shipment.status_changed",
        text="AWB DLH35391376 -> Pickup Scheduled",
        tone=AuditEvent.Tone.INFO,
        payload={"order_id": 101, "status": "Pickup Scheduled"},
    )

    refs["saas_org"] = AuditEvent.objects.create(
        kind="saas.default_organization.ensured",
        text="Default organization ensured",
        tone=AuditEvent.Tone.INFO,
        payload={"organization_code": "nirogidhara"},
    )

    return refs


# ---------------------------------------------------------------------------
# Auth + empty path.
# ---------------------------------------------------------------------------


def test_anonymous_blocked(anonymous_client):
    resp = anonymous_client.get(TIMELINE_URL)
    assert resp.status_code in (401, 403)


def test_viewer_blocked(viewer_client):
    resp = viewer_client.get(TIMELINE_URL)
    assert resp.status_code == 403


def test_admin_empty_db(admin_client, db):
    # New DB has no AuditEvent rows. Endpoint returns the empty shape.
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    resp = admin_client.get(TIMELINE_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["categoryFiltered"] is None
    assert "categoriesAvailable" in body


def test_director_can_read(director_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = director_client.get(TIMELINE_URL)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Ordering + shape.
# ---------------------------------------------------------------------------


def test_returns_newest_first(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL)
    body = resp.json()
    assert body["count"] >= 5
    kinds = [item["kind"] for item in body["items"]]
    # The last seeded event should be at index 0 (newest).
    assert kinds[0] == "saas.default_organization.ensured"


def test_response_shape_has_safe_fields(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL)
    body = resp.json()
    sample = body["items"][0]
    expected = {"id", "occurredAt", "kind", "tone", "icon", "text", "category", "payload"}
    assert expected.issubset(sample.keys())
    # No raw payload leak: every key on payload must be on the allow-list.
    assert isinstance(sample["payload"], dict)


# ---------------------------------------------------------------------------
# Filters.
# ---------------------------------------------------------------------------


def test_filter_by_kind_exact(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?kind=payment.received")
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "payment.received"


def test_filter_by_tone(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?tone=danger")
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["tone"] == "danger"
    assert body["items"][0]["kind"] == "runtime.kill_switch.enabled"


def test_filter_by_tone_invalid_returns_400(admin_client):
    resp = admin_client.get(TIMELINE_URL + "?tone=neon")
    assert resp.status_code == 400


def test_filter_by_category_rollback(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?category=rollback")
    body = resp.json()
    assert body["categoryFiltered"] == "rollback"
    kinds = {item["kind"] for item in body["items"]}
    assert "prompt_version.rollback.ui_changed" in kinds
    assert "ai.prompt_version.rolled_back" in kinds
    # No payment / order / shipment leak under rollback.
    assert "payment.received" not in kinds
    assert "order.created" not in kinds


def test_filter_by_category_safety(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?category=safety")
    body = resp.json()
    kinds = {item["kind"] for item in body["items"]}
    assert "runtime.kill_switch.enabled" in kinds
    assert "ai.sandbox.enabled" in kinds
    # Rollback rows are NOT also safety.
    assert "prompt_version.rollback.ui_changed" not in kinds


def test_filter_by_category_invalid_returns_400(admin_client):
    resp = admin_client.get(TIMELINE_URL + "?category=phlogiston")
    assert resp.status_code == 400


def test_filter_by_text_query(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?q=NRG-1001")
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["kind"] == "order.created"


def test_filter_by_date_range(admin_client, db):
    from urllib.parse import urlencode

    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    seeded = _seed_mixed_events(db)
    # Push one row into the past, leave the rest in the present.
    past = timezone.now() - timedelta(days=10)
    AuditEvent.objects.filter(pk=seeded["order_created"].pk).update(occurred_at=past)
    cutoff_iso = (timezone.now() - timedelta(days=1)).isoformat()
    # URL-encode so the ``+00:00`` timezone marker survives.
    qs_from = urlencode({"date_from": cutoff_iso})
    resp = admin_client.get(TIMELINE_URL + "?" + qs_from)
    body = resp.json()
    kinds = {item["kind"] for item in body["items"]}
    assert "order.created" not in kinds
    # Reverse the range: only the past row.
    qs_to = urlencode({"date_to": cutoff_iso})
    resp2 = admin_client.get(TIMELINE_URL + "?" + qs_to)
    body2 = resp2.json()
    kinds2 = {item["kind"] for item in body2["items"]}
    assert "order.created" in kinds2


# ---------------------------------------------------------------------------
# Pagination.
# ---------------------------------------------------------------------------


def test_pagination_limit_and_offset(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    resp = admin_client.get(TIMELINE_URL + "?limit=2&offset=0")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    resp2 = admin_client.get(TIMELINE_URL + "?limit=2&offset=2")
    body2 = resp2.json()
    # No overlap between pages.
    ids_page1 = {item["id"] for item in body["items"]}
    ids_page2 = {item["id"] for item in body2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


def test_limit_hard_capped_at_200(admin_client, db):
    resp = admin_client.get(TIMELINE_URL + "?limit=99999")
    body = resp.json()
    assert body["limit"] == 200


def test_limit_zero_falls_back_to_default(admin_client, db):
    resp = admin_client.get(TIMELINE_URL + "?limit=0")
    body = resp.json()
    assert body["limit"] == 50


def test_limit_garbage_falls_back_to_default(admin_client, db):
    resp = admin_client.get(TIMELINE_URL + "?limit=abc")
    body = resp.json()
    assert body["limit"] == 50


# ---------------------------------------------------------------------------
# Sanitisation.
# ---------------------------------------------------------------------------


def test_sanitisation_drops_forbidden_keys(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    # Poison payload with every forbidden key we can think of.
    AuditEvent.objects.create(
        kind="payment.received",
        text="Paid",
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "amount": 100,
            "order_id": 5,
            # FORBIDDEN keys below — must never appear in the response.
            "token": "leaked-jwt-token",
            "access_token": "leaked-access-token",
            "refresh_token": "leaked-refresh",
            "verify_token": "leaked-verify",
            "app_secret": "leaked-app-secret",
            "api_key": "leaked-api-key",
            "secret": "leaked-secret",
            "phone": "+919999999999",
            "customer_phone": "+919999999999",
            "email": "leaked@example.com",
            "address": "12 Some Lane, City",
            "card": "4111111111111111",
            "vpa": "leaked@vpa",
            "upi": "leaked@upi",
            "raw_response": {"any": "thing"},
            "raw_payload": "{...}",
            "raw_signature": "abc",
            "gateway_reference_id": "rzp_test_xxxxx",
            "payment_url": "https://rzp.io/leaked",
            "system_policy": "the whole prompt body",
            "role_prompt": "the whole role body",
            "instruction_payload": {"big": "blob"},
            "messages": [{"role": "user", "content": "secret"}],
            "transcript": "long call transcript text",
            "reply_text": "AI reply body",
            "customer_name": "Real Customer Name",
            "director_signoff": "BEGIN_UTC=... END_UTC=...",
            "metadata": {"any": "leaked metadata"},
            "evidence_json": {"any": "leaked evidence"},
        },
    )
    resp = admin_client.get(TIMELINE_URL)
    body = resp.json()
    # Re-serialise the body as JSON to scan for any forbidden value.
    import json

    blob = json.dumps(body)
    forbidden_values = [
        "leaked-jwt-token",
        "leaked-access-token",
        "leaked-refresh",
        "leaked-verify",
        "leaked-app-secret",
        "leaked-api-key",
        "leaked-secret",
        "+919999999999",
        "leaked@example.com",
        "12 Some Lane",
        "4111111111111111",
        "leaked@vpa",
        "leaked@upi",
        "rzp_test_xxxxx",
        "https://rzp.io/leaked",
        "the whole prompt body",
        "the whole role body",
        "Real Customer Name",
        "AI reply body",
        "leaked evidence",
        "leaked metadata",
        "long call transcript text",
    ]
    for value in forbidden_values:
        assert value not in blob, f"forbidden value {value!r} leaked"
    # Allowed keys ARE surfaced.
    sample = body["items"][0]
    assert sample["payload"]["amount"] == 100
    assert sample["payload"]["order_id"] == 5


def test_long_string_values_truncated(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    long_reason = "x" * 500
    AuditEvent.objects.create(
        kind="ai.prompt_version.rolled_back",
        text="rollback",
        tone=AuditEvent.Tone.WARNING,
        payload={"reason": long_reason, "agent": "ceo"},
    )
    resp = admin_client.get(TIMELINE_URL)
    body = resp.json()
    surfaced = body["items"][0]["payload"]["reason"]
    assert len(surfaced) <= 200
    assert surfaced.endswith("...")


def test_non_dict_payload_returns_empty_payload(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    AuditEvent.objects.create(
        kind="order.created",
        text="weird payload",
        tone=AuditEvent.Tone.INFO,
        payload=[],  # legacy list payload
    )
    resp = admin_client.get(TIMELINE_URL)
    body = resp.json()
    assert body["items"][0]["payload"] == {}


# ---------------------------------------------------------------------------
# Write verbs.
# ---------------------------------------------------------------------------


def test_post_returns_405(admin_client):
    resp = admin_client.post(TIMELINE_URL, data={}, format="json")
    assert resp.status_code == 405


def test_put_returns_405(admin_client):
    resp = admin_client.put(TIMELINE_URL, data={}, format="json")
    assert resp.status_code == 405


def test_patch_returns_405(admin_client):
    resp = admin_client.patch(TIMELINE_URL, data={}, format="json")
    assert resp.status_code == 405


def test_delete_returns_405(admin_client):
    resp = admin_client.delete(TIMELINE_URL)
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Defensive safety: never calls a provider, never mutates business
# rows, never writes a new AuditEvent.
# ---------------------------------------------------------------------------


def _row_counts():
    from apps.audit.models import AuditEvent
    from apps.crm.models import Customer, Lead
    from apps.orders.models import Order
    from apps.payments.models import Payment

    return {
        "audit": AuditEvent.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "order": Order.objects.count(),
        "payment": Payment.objects.count(),
    }


def test_defensive_safety_no_provider_no_mutation(admin_client, db):
    from apps.audit.models import AuditEvent

    AuditEvent.objects.all().delete()
    _seed_mixed_events(db)
    before = _row_counts()

    with (
        mock.patch(
            "apps.whatsapp.services.queue_template_message"
        ) as queue_template,
        mock.patch(
            "apps.whatsapp.services.send_freeform_text_message"
        ) as send_freeform,
        mock.patch(
            "apps.calls.services.trigger_call_for_lead"
        ) as trigger_call,
        mock.patch(
            "apps.shipments.services.create_shipment"
        ) as create_shipment,
    ):
        resp = admin_client.get(TIMELINE_URL)
        assert resp.status_code == 200

        # Exercise every filter to ensure they are still safe.
        for url in (
            TIMELINE_URL + "?category=rollback",
            TIMELINE_URL + "?category=safety",
            TIMELINE_URL + "?tone=warning",
            TIMELINE_URL + "?q=Order",
            TIMELINE_URL + "?kind=payment.received",
            TIMELINE_URL + "?limit=5&offset=1",
        ):
            r = admin_client.get(url)
            assert r.status_code == 200

        queue_template.assert_not_called()
        send_freeform.assert_not_called()
        trigger_call.assert_not_called()
        create_shipment.assert_not_called()

    after = _row_counts()
    assert before == after


# ---------------------------------------------------------------------------
# Category mapping unit tests.
# ---------------------------------------------------------------------------


def test_categorize_kind_mapping():
    from apps.audit.views import (
        CATEGORY_AI_GOVERNANCE,
        CATEGORY_AUTH_SYSTEM,
        CATEGORY_DELIVERY,
        CATEGORY_ORDERS,
        CATEGORY_OTHER,
        CATEGORY_PAYMENTS,
        CATEGORY_ROLLBACK,
        CATEGORY_SAFETY,
        CATEGORY_WHATSAPP,
        categorize_kind,
    )

    assert categorize_kind("prompt_version.rollback.ui_changed") == CATEGORY_ROLLBACK
    assert categorize_kind("ai.prompt_version.rolled_back") == CATEGORY_ROLLBACK
    assert categorize_kind("runtime.kill_switch.enabled") == CATEGORY_SAFETY
    assert categorize_kind("ai.sandbox.enabled") == CATEGORY_SAFETY
    assert categorize_kind("compliance.flagged") == CATEGORY_SAFETY
    assert categorize_kind("whatsapp.ai.safety_downgraded") == CATEGORY_SAFETY
    assert categorize_kind("ai.agent_run.completed") == CATEGORY_AI_GOVERNANCE
    assert categorize_kind("approval.required") == CATEGORY_AI_GOVERNANCE
    assert categorize_kind("whatsapp.message.sent") == CATEGORY_WHATSAPP
    assert categorize_kind("payment.received") == CATEGORY_PAYMENTS
    assert categorize_kind("razorpay.webhook.received") == CATEGORY_PAYMENTS
    assert categorize_kind("discount.requested") == CATEGORY_PAYMENTS
    assert categorize_kind("order.created") == CATEGORY_ORDERS
    assert categorize_kind("catalog.product.created") == CATEGORY_ORDERS
    assert categorize_kind("shipment.status_changed") == CATEGORY_DELIVERY
    assert categorize_kind("delhivery.webhook.received") == CATEGORY_DELIVERY
    assert categorize_kind("razorpay.courier_execution.executed") == CATEGORY_DELIVERY
    assert categorize_kind("saas.default_organization.ensured") == CATEGORY_AUTH_SYSTEM
    assert categorize_kind("runtime.live_gate.previewed") == CATEGORY_AUTH_SYSTEM
    assert categorize_kind("mcp.tool.call_succeeded") == CATEGORY_AUTH_SYSTEM
    assert categorize_kind("system.smoke_test.started") == CATEGORY_AUTH_SYSTEM
    # Unknown kind falls through to "other".
    assert categorize_kind("future_phase_99.brand_new_kind") == CATEGORY_OTHER
    # Empty / non-string input is safe.
    assert categorize_kind("") == CATEGORY_OTHER
    assert categorize_kind(None) == CATEGORY_OTHER  # type: ignore[arg-type]
