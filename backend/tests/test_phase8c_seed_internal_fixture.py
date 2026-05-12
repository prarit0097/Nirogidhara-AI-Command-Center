"""Phase 8C-Hotfix-1 - safe internal sandbox fixture seed tests.

Covers the ``seed_phase8c_internal_controlled_mutation_fixture``
management command:

- dry-run creates no rows
- ``--apply`` creates exactly one Order and one Payment
- rerun is idempotent (reuses existing rows; no duplicates)
- no provider imports / no provider calls
- no real WhatsApp send / no courier call / no customer notification
- ``raw_response.phase8c_sandbox`` is ``True``
- Phase 8C runtime safety proof accepts the seeded pair
- row counts unchanged across the protected business tables
  except for the explicit Order +1 / Payment +1 on the first
  ``--apply``
- ``--json`` flag returns a parseable report
"""
from __future__ import annotations

import importlib
import io
import json

import pytest
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.crm.models import Customer, Lead
from apps.orders.models import DiscountOfferLog, Order
from apps.payments.models import Payment
from apps.payments.phase8c_payment_order_controlled_mutation import (
    _order_is_internal_sandbox,
    _payment_is_internal_sandbox,
    _validate_target_references,
    _validate_target_safety,
)
from apps.shipments.models import RescueAttempt, Shipment, WorkflowStep
from apps.whatsapp.models import (
    WhatsAppHandoffToCall,
    WhatsAppLifecycleEvent,
    WhatsAppMessage,
)


_FIXTURE_ORDER_ID = "phase8c-controlled-order-001"
_FIXTURE_PAYMENT_ID = "phase8c-controlled-payment-001"


def _run(*args) -> dict:
    """Invoke the seed command with --json and return the parsed
    payload. Raises if the command did not write JSON to stdout."""
    out = io.StringIO()
    call_command(
        "seed_phase8c_internal_controlled_mutation_fixture",
        *args,
        "--json",
        stdout=out,
    )
    raw = out.getvalue().strip()
    if not raw:
        raise AssertionError(
            "seed_phase8c_internal_controlled_mutation_fixture wrote "
            "no JSON output."
        )
    return json.loads(raw)


def _protected_table_counts() -> dict[str, int]:
    """Tables that MUST stay at delta 0 across both dry-run and
    apply (i.e. NOT Order, NOT Payment, NOT WhatsAppLifecycleEvent)."""
    return {
        "shipment": Shipment.objects.count(),
        "discount_offer_log": DiscountOfferLog.objects.count(),
        "customer": Customer.objects.count(),
        "lead": Lead.objects.count(),
        "whatsapp_message": WhatsAppMessage.objects.count(),
        "whatsapp_handoff": WhatsAppHandoffToCall.objects.count(),
        "workflow_step": WorkflowStep.objects.count(),
        "rescue_attempt": RescueAttempt.objects.count(),
    }


# ---------------------------------------------------------------------------
# Static-file scan + audit-kind length budget
# ---------------------------------------------------------------------------


def test_phase8c_seed_command_does_not_import_provider_clients() -> None:
    """Phase 8C-Hotfix-1 never calls a provider; the seed command
    must not import any provider client / send helper / dotenv
    (static-file scan; checks actual import lines, not docstring
    mentions)."""
    src_path = importlib.import_module(
        "apps.payments.management.commands."
        "seed_phase8c_internal_controlled_mutation_fixture"
    ).__file__
    with open(src_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    forbidden = [
        "from apps.shipments.integrations.delhivery_client",
        "from apps.whatsapp.services import send_freeform_text_message",
        "from apps.whatsapp.services import queue_template_message",
        "from apps.whatsapp.integrations.whatsapp.meta_cloud_client",
        "from apps.whatsapp.integrations.whatsapp import meta_cloud_client",
        "from apps.payments.integrations.razorpay_client",
        "import razorpay",
        "from dotenv",
        "import dotenv",
    ]
    for needle in forbidden:
        for line in text.splitlines():
            stripped = line.lstrip()
            if not (
                stripped.startswith("from ")
                or stripped.startswith("import ")
            ):
                continue
            if needle in stripped:
                pytest.fail(
                    f"Seed command imports forbidden module: "
                    f"{needle}"
                )


def test_phase8c_seed_audit_kinds_within_length_budget() -> None:
    kinds = (
        "phase8c.fixture.seeded",
        "phase8c.fixture.dry_run",
        "phase8c.fixture.blocked",
    )
    for kind in kinds:
        assert kind.startswith("phase8c.fixture.")
        assert len(kind) <= 64, f"{kind} ({len(kind)} chars)"


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_seed_dry_run_creates_no_rows() -> None:
    before_order_count = Order.objects.count()
    before_payment_count = Payment.objects.count()
    before_protected = _protected_table_counts()
    assert not Order.objects.filter(pk=_FIXTURE_ORDER_ID).exists()
    assert not Payment.objects.filter(
        pk=_FIXTURE_PAYMENT_ID
    ).exists()

    report = _run()  # default = dry-run

    assert report["mode"] == "dry_run"
    assert report["createdOrder"] is False
    assert report["createdPayment"] is False
    assert report["reusedOrder"] is False
    assert report["reusedPayment"] is False
    assert report["countDeltas"] == {}
    assert report["safeForPhase8C"] is False
    assert (
        report["nextAction"]
        == "rerun_with_apply_to_create_phase8c_fixture"
    )
    # Row counts unchanged.
    assert Order.objects.count() == before_order_count
    assert Payment.objects.count() == before_payment_count
    assert _protected_table_counts() == before_protected
    # Dry-run audit row written.
    assert AuditEvent.objects.filter(
        kind="phase8c.fixture.dry_run"
    ).exists()


# ---------------------------------------------------------------------------
# Apply path (first run)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_seed_apply_creates_exactly_one_order_and_one_payment() -> None:
    before_order_count = Order.objects.count()
    before_payment_count = Payment.objects.count()
    before_protected = _protected_table_counts()
    assert not Order.objects.filter(pk=_FIXTURE_ORDER_ID).exists()
    assert not Payment.objects.filter(
        pk=_FIXTURE_PAYMENT_ID
    ).exists()

    report = _run("--apply")

    assert report["mode"] == "apply"
    assert report["createdOrder"] is True
    assert report["createdPayment"] is True
    assert report["reusedOrder"] is False
    assert report["reusedPayment"] is False
    assert report["countDeltas"].get("order") == 1
    assert report["countDeltas"].get("payment") == 1
    # No protected table grew.
    assert _protected_table_counts() == before_protected
    # Exactly one fixture pair exists.
    assert Order.objects.count() == before_order_count + 1
    assert Payment.objects.count() == before_payment_count + 1
    assert Order.objects.filter(pk=_FIXTURE_ORDER_ID).exists()
    assert Payment.objects.filter(pk=_FIXTURE_PAYMENT_ID).exists()
    assert report["safeForPhase8C"] is True
    assert report["nextAction"] == "run_phase8c_dry_run"
    # Audit written.
    assert AuditEvent.objects.filter(
        kind="phase8c.fixture.seeded"
    ).exists()


@pytest.mark.django_db
def test_phase8c_seed_apply_row_field_values_match_spec() -> None:
    _run("--apply")
    order = Order.objects.get(pk=_FIXTURE_ORDER_ID)
    payment = Payment.objects.get(pk=_FIXTURE_PAYMENT_ID)
    # Order fields.
    assert order.customer_name == "Phase 8C Internal Test"
    assert order.phone == "0000000000"
    assert order.product == "Phase 8C Internal Sandbox Product"
    assert order.quantity == 1
    assert order.amount == 100
    assert order.discount_pct == 0
    assert order.advance_paid is False
    assert order.advance_amount == 0
    assert order.payment_status == Order.PaymentStatus.PENDING
    assert order.state == "internal_sandbox"
    assert order.city == "internal_sandbox"
    assert order.rto_risk == Order.RtoRisk.LOW
    assert order.rto_score == 0
    assert order.agent == "Phase8C"
    assert order.stage == "internal_sandbox"
    assert order.created_at_label == "Phase 8C Sandbox"
    # Payment fields.
    assert payment.order_id == _FIXTURE_ORDER_ID
    assert payment.customer == "Phase 8C Internal Test"
    assert payment.customer_email == ""
    assert payment.customer_phone == "0000000000"
    assert payment.amount == 100
    assert payment.gateway == Payment.Gateway.RAZORPAY
    assert payment.status == Payment.Status.PENDING
    assert payment.type == Payment.Type.ADVANCE
    assert payment.time == "Phase 8C Sandbox"
    assert (
        payment.gateway_reference_id
        == "phase8c-controlled-gateway-ref-001"
    )
    assert payment.payment_url == ""
    # raw_response is the source of the sandbox proof.
    raw = payment.raw_response or {}
    assert raw.get("phase8c_sandbox") is True
    assert raw.get("internal_test") is True
    assert raw.get("real_customer") is False
    assert raw.get("provider_call") is False
    assert raw.get("created_by") == (
        "seed_phase8c_internal_controlled_mutation_fixture"
    )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_seed_rerun_is_idempotent_and_reuses() -> None:
    _run("--apply")
    before_order_count = Order.objects.count()
    before_payment_count = Payment.objects.count()
    before_lifecycle = WhatsAppLifecycleEvent.objects.count()
    before_protected = _protected_table_counts()

    report = _run("--apply")

    assert report["mode"] == "apply"
    assert report["createdOrder"] is False
    assert report["createdPayment"] is False
    assert report["reusedOrder"] is True
    assert report["reusedPayment"] is True
    assert report["countDeltas"] == {}
    assert report["safeForPhase8C"] is True
    assert (
        report["nextAction"]
        == "reused_existing_phase8c_fixture_run_dry_run"
    )
    # No table grew on the rerun.
    assert Order.objects.count() == before_order_count
    assert Payment.objects.count() == before_payment_count
    assert WhatsAppLifecycleEvent.objects.count() == before_lifecycle
    assert _protected_table_counts() == before_protected


# ---------------------------------------------------------------------------
# Safety: no provider / WhatsApp / customer notification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_seed_apply_does_not_send_whatsapp_or_notify() -> None:
    """Apply must not grow the WhatsAppMessage table (real send),
    the customer-facing Customer / Lead / Shipment /
    DiscountOfferLog / WhatsAppHandoffToCall / WorkflowStep /
    RescueAttempt tables, regardless of any signal-driven
    observability rows on WhatsAppLifecycleEvent."""
    before = _protected_table_counts()
    _run("--apply")
    after = _protected_table_counts()
    assert before == after


# ---------------------------------------------------------------------------
# Phase 8C safety-proof acceptance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_dry_run_safety_proof_accepts_the_seeded_pair() -> None:
    _run("--apply")
    order = Order.objects.get(pk=_FIXTURE_ORDER_ID)
    payment = Payment.objects.get(pk=_FIXTURE_PAYMENT_ID)
    assert _order_is_internal_sandbox(order) is True
    assert _payment_is_internal_sandbox(payment) is True
    assert _validate_target_safety(order, payment) == []
    assert (
        _validate_target_references(
            target_order_id=order.id,
            target_payment_id=payment.id,
            target_order_reference=(
                "phase8c::controlled::order::001"
            ),
            target_payment_reference=(
                "phase8c::controlled::payment::001"
            ),
        )
        == []
    )


# ---------------------------------------------------------------------------
# --json output shape
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase8c_seed_json_output_includes_all_required_keys() -> None:
    report = _run("--apply")
    required_keys = {
        "phase",
        "fixture",
        "mode",
        "orderId",
        "paymentId",
        "createdOrder",
        "createdPayment",
        "reusedOrder",
        "reusedPayment",
        "beforeCounts",
        "afterCounts",
        "countDeltas",
        "safeForPhase8C",
        "warnings",
        "nextAction",
    }
    for key in required_keys:
        assert key in report, key
    assert report["phase"] == "8C"
    assert report["fixture"] == "phase8c_hotfix_1"
    assert report["orderId"] == _FIXTURE_ORDER_ID
    assert report["paymentId"] == _FIXTURE_PAYMENT_ID
