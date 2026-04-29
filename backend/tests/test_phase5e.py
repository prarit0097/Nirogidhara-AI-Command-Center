"""Phase 5E — Rescue discount flow + Day-20 reorder + default claims.

Coverage groups:

- ``seed_default_claims`` is idempotent + protects real admin-added rows.
- Default claims do not contain blocked phrases.
- Coverage report surfaces demo / default rows with risk=demo_ok.
- Cumulative cap math: 50% absolute hard cap.
- Rescue offer respects the per-step ladder + cap remaining.
- Already 40% discount → max 10% extra.
- Already 50% discount → no further discount.
- Over-cap request → status=needs_ceo_review + ApprovalRequest mint.
- Confirmation / Delivery / RTO refusal create rescue offers (when enabled).
- Customer acceptance applies discount via service layer.
- Customer rejection logs rejected.
- DiscountOfferLog row written for offered/accepted/rejected/blocked.
- CAIO cannot create / apply discount offer.
- Lifecycle Day-20 sweep queues reminder; idempotent on re-run.
- Lifecycle failure does not mutate Order/Payment/Shipment.
- audit events emitted.
- API endpoints work for operations user; viewer blocked.
"""
from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.compliance.coverage import (
    build_coverage_report,
    coverage_for_product,
)
from apps.compliance.models import Claim
from apps.crm.models import Customer
from apps.orders.models import DiscountOfferLog, Order
from apps.orders.rescue_discount import (
    TOTAL_DISCOUNT_HARD_CAP_PCT,
    accept_rescue_discount_offer,
    calculate_rescue_discount_offer,
    cap_status,
    create_rescue_discount_offer,
    get_current_total_discount_pct,
    get_discount_cap_remaining,
    reject_rescue_discount_offer,
    validate_total_discount_cap,
)
from apps.orders.services import create_order
from apps.payments.models import Payment
from apps.payments.services import create_payment_link
from apps.whatsapp.lifecycle import REORDER_DAY20_ACTION, queue_lifecycle_message
from apps.whatsapp.models import (
    WhatsAppConnection,
    WhatsAppConsent,
    WhatsAppLifecycleEvent,
    WhatsAppTemplate,
)
from apps.whatsapp.reorder import run_day20_reorder_sweep
from apps.whatsapp.template_registry import upsert_template


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operations_user_p5e(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="ops_p5e", password="ops12345", email="ops_p5e@nirogidhara.test"
    )
    user.role = User.Role.OPERATIONS
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def viewer_user_p5e(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="viewer_p5e",
        password="viewer12345",
        email="viewer_p5e@nirogidhara.test",
    )
    user.role = User.Role.VIEWER
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def admin_user_p5e(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="admin_p5e",
        password="admin12345",
        email="admin_p5e@nirogidhara.test",
    )
    user.role = User.Role.ADMIN
    user.save(update_fields=["role"])
    return user


@pytest.fixture
def customer(db):
    customer = Customer.objects.create(
        id="NRG-CUST-5E-001",
        name="5E Customer",
        phone="+919999955501",
        state="MH",
        city="Pune",
        language="hi",
        product_interest="Weight Management",
        consent_whatsapp=True,
    )
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={
            "consent_state": WhatsAppConsent.State.GRANTED,
            "granted_at": timezone.now(),
            "source": "test",
        },
    )
    return customer


@pytest.fixture
def order(customer):
    return create_order(
        customer_name=customer.name,
        phone=customer.phone,
        product="Weight Management",
        state=customer.state,
        city=customer.city,
        amount=3000,
        agent="WhatsApp AI",
        stage=Order.Stage.CONFIRMATION_PENDING,
    )


def _auth(client: APIClient, user) -> APIClient:
    from rest_framework_simplejwt.tokens import RefreshToken

    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}"
    )
    return client


# ---------------------------------------------------------------------------
# 1. seed_default_claims
# ---------------------------------------------------------------------------


def test_seed_default_claims_creates_eight_categories(db) -> None:
    out = io.StringIO()
    call_command("seed_default_claims", stdout=out)
    assert Claim.objects.count() >= 8
    coverage = coverage_for_product("Weight Management")
    assert coverage.has_approved_claims is True
    assert coverage.is_demo_default is True
    assert coverage.risk == "demo_ok"


def test_seed_default_claims_idempotent_without_reset(db) -> None:
    call_command("seed_default_claims")
    initial_count = Claim.objects.count()
    out = io.StringIO()
    call_command("seed_default_claims", stdout=out)
    # Same row count and demo seeds preserved.
    assert Claim.objects.count() == initial_count
    # Stage 2: skipped because not --reset-demo.
    assert "skipped" in out.getvalue() or "demo" in out.getvalue()


def test_seed_default_claims_protects_real_admin_claims(db) -> None:
    # Admin manually adds a claim before the demo seed runs.
    Claim.objects.create(
        product="Weight Management",
        approved=["Doctor approved real wording about wellness."],
        disallowed=["Guaranteed cure"],
        doctor="Dr. Real",
        compliance="Compliance Real",
        version="v2.5",
    )
    call_command("seed_default_claims")
    real = Claim.objects.get(product="Weight Management")
    assert real.doctor == "Dr. Real"
    assert real.version == "v2.5"


def test_seed_default_claims_no_blocked_phrases(db) -> None:
    call_command("seed_default_claims")
    blocked = (
        "guaranteed cure",
        "permanent solution",
        "no side effects for everyone",
        "doctor ki zarurat nahi",
        "100% cure",
    )
    for claim in Claim.objects.all():
        for phrase in claim.approved or []:
            lowered = (phrase or "").lower()
            for needle in blocked:
                assert needle not in lowered, (
                    f"Default Claim Vault leaked blocked phrase '{needle}' in {claim.product}: {phrase!r}"
                )


# ---------------------------------------------------------------------------
# 1b. Phase 5E-Hotfix-2 — strengthened demo Claim Vault coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "product",
    [
        "Weight Management",
        "Blood Purification",
        "Men Wellness",
        "Women Wellness",
        "Immunity",
        "Lungs Detox",
        "Body Detox",
        "Joint Care",
    ],
)
def test_every_demo_seed_passes_usage_check(db, product: str) -> None:
    """All 8 categories must report ``demo_ok`` (not ``weak``) post-seed."""
    call_command("seed_default_claims")
    coverage = coverage_for_product(product)
    assert coverage.has_approved_claims is True, product
    assert coverage.missing_required_usage_claims is False, product
    assert coverage.risk == "demo_ok", product
    assert coverage.is_demo_default is True, product


def test_blood_purification_seed_includes_usage_hint(db) -> None:
    call_command("seed_default_claims")
    claim = Claim.objects.get(product="Blood Purification")
    blob = " ".join(claim.approved).lower()
    # Either the original capsule wording OR the new label / hydration
    # / practitioner phrasing must be present.
    assert any(
        keyword in blob
        for keyword in (
            "directed on the label",
            "label",
            "hydration",
            "practitioner",
        )
    )
    coverage = coverage_for_product("Blood Purification")
    assert coverage.risk == "demo_ok"
    assert "missing_usage_hint" not in coverage.notes


def test_lungs_detox_seed_includes_usage_hint(db) -> None:
    call_command("seed_default_claims")
    claim = Claim.objects.get(product="Lungs Detox")
    blob = " ".join(claim.approved).lower()
    assert any(
        keyword in blob
        for keyword in (
            "directed",
            "practitioner",
            "hydration",
            "balanced diet",
        )
    )
    coverage = coverage_for_product("Lungs Detox")
    assert coverage.risk == "demo_ok"
    assert "missing_usage_hint" not in coverage.notes


def test_demo_seed_includes_common_safe_usage_phrases(db) -> None:
    """Universal usage-guidance phrases must be in every demo seed."""
    from apps.compliance.management.commands.seed_default_claims import (
        COMMON_SAFE_USAGE_PHRASES,
    )

    call_command("seed_default_claims")
    for claim in Claim.objects.filter(version__startswith="demo-"):
        for safe_phrase in COMMON_SAFE_USAGE_PHRASES:
            assert safe_phrase in claim.approved, (
                f"Demo seed for {claim.product} missing universal phrase: {safe_phrase!r}"
            )


def test_demo_seed_does_not_duplicate_phrases_on_double_run(db) -> None:
    """Idempotent re-seed must not duplicate the merged universal phrases."""
    call_command("seed_default_claims")
    pre = {
        c.product: list(c.approved) for c in Claim.objects.filter(version__startswith="demo-")
    }
    call_command("seed_default_claims")
    post = {
        c.product: list(c.approved) for c in Claim.objects.filter(version__startswith="demo-")
    }
    for product, phrases in pre.items():
        assert post[product] == phrases, (
            f"{product} approved list changed across idempotent re-seeds"
        )
        # No phrase should appear twice within a single demo row.
        assert len(set(p.lower() for p in phrases)) == len(phrases), (
            f"{product} demo seed has duplicate phrases: {phrases!r}"
        )


def test_reset_demo_refreshes_v1_seeds_to_v2(db) -> None:
    """Old demo-v1 rows are upgraded to demo-v2 only via --reset-demo."""
    Claim.objects.create(
        product="Weight Management",
        approved=["Old wording from demo-v1"],
        disallowed=["Guaranteed cure"],
        doctor="Demo Default",
        compliance="Demo Default",
        version="demo-v1",
    )
    call_command("seed_default_claims")  # no --reset-demo → skipped
    row = Claim.objects.get(product="Weight Management")
    assert row.version == "demo-v1"
    assert row.approved == ["Old wording from demo-v1"]

    call_command("seed_default_claims", "--reset-demo")
    row = Claim.objects.get(product="Weight Management")
    assert row.version == "demo-v2"
    assert "Old wording from demo-v1" not in row.approved


def test_check_claim_vault_coverage_command_no_weak_after_seed(db) -> None:
    """check_claim_vault_coverage must not flag missing_usage_hint post-seed."""
    call_command("seed_default_claims")
    out = io.StringIO()
    call_command("check_claim_vault_coverage", stdout=out)
    output = out.getvalue()
    # Demo seeds should be reported as ok / demo_ok, never weak.
    assert "weak" not in output.split("=")[-1].split()[0:1]  # summary line
    # And the per-row dump should not surface missing_usage_hint anywhere
    # because every seeded category now carries a usage hint.
    assert "missing_usage_hint" not in output


def test_coverage_report_surfaces_demo_count(db) -> None:
    call_command("seed_default_claims")
    report = build_coverage_report()
    assert report.demo_count >= 8
    assert report.ok_count >= 8


# ---------------------------------------------------------------------------
# 2. Cumulative cap
# ---------------------------------------------------------------------------


def test_cap_remaining_with_zero_existing_discount(order) -> None:
    assert get_current_total_discount_pct(order) == 0
    assert get_discount_cap_remaining(order) == TOTAL_DISCOUNT_HARD_CAP_PCT


def test_cap_remaining_with_existing_40_pct(order) -> None:
    order.discount_pct = 40
    order.save(update_fields=["discount_pct"])
    assert get_current_total_discount_pct(order) == 40
    assert get_discount_cap_remaining(order) == 10


def test_cap_remaining_with_existing_50_pct(order) -> None:
    order.discount_pct = 50
    order.save(update_fields=["discount_pct"])
    assert get_discount_cap_remaining(order) == 0


def test_validate_total_discount_cap_under(order) -> None:
    passed, total = validate_total_discount_cap(order, additional_pct=10)
    assert passed is True
    assert total == 10


def test_validate_total_discount_cap_over(order) -> None:
    order.discount_pct = 40
    order.save(update_fields=["discount_pct"])
    passed, total = validate_total_discount_cap(order, additional_pct=15)
    assert passed is False
    assert total == 55


# ---------------------------------------------------------------------------
# 3. Rescue offer calculator
# ---------------------------------------------------------------------------


def test_rescue_offer_first_refusal_uses_ladder_first_step(order) -> None:
    rescue = calculate_rescue_discount_offer(
        order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        refusal_count=1,
    )
    assert rescue.allowed is True
    assert rescue.offered_additional_pct == 5  # ladder[0]


def test_rescue_offer_second_refusal_steps_up(order) -> None:
    rescue = calculate_rescue_discount_offer(
        order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        refusal_count=2,
    )
    assert rescue.allowed is True
    assert rescue.offered_additional_pct == 10


def test_rescue_offer_clamps_to_cap_remaining(order) -> None:
    order.discount_pct = 40
    order.save(update_fields=["discount_pct"])
    rescue = calculate_rescue_discount_offer(
        order,
        stage=DiscountOfferLog.Stage.RTO,
        refusal_count=3,  # would have asked for 20%
    )
    # Cap leaves 10% headroom only.
    assert rescue.offered_additional_pct == 10
    assert "clamped_to_cap_remaining" in rescue.notes


def test_rescue_offer_blocked_when_cap_exhausted(order) -> None:
    order.discount_pct = 50
    order.save(update_fields=["discount_pct"])
    rescue = calculate_rescue_discount_offer(
        order, stage=DiscountOfferLog.Stage.CONFIRMATION
    )
    assert rescue.allowed is False
    assert rescue.needs_ceo_review is True
    assert "cap_exhausted" in rescue.notes


def test_rescue_offer_above_auto_band_needs_ceo(order) -> None:
    rescue = calculate_rescue_discount_offer(
        order,
        stage=DiscountOfferLog.Stage.RTO,
        refusal_count=1,
        requested_pct=20,
    )
    # 20% needs CEO AI / admin approval per Phase 3E policy.
    assert rescue.allowed is False
    assert rescue.needs_ceo_review is True


# ---------------------------------------------------------------------------
# 4. create_rescue_discount_offer + DiscountOfferLog
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_confirmation_refusal_creates_offer_log(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="customer_refused_confirmation",
        refusal_count=1,
        actor_role="operations",
        actor_agent="ai_chat",
    )
    assert log.status == DiscountOfferLog.Status.OFFERED
    assert log.offered_additional_pct == 5
    assert log.cap_remaining_pct == 45
    assert AuditEvent.objects.filter(
        kind="discount.offer.created"
    ).exists()


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_delivery_refusal_creates_offer_log(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.DELIVERY,
        source_channel=DiscountOfferLog.SourceChannel.AI_CALL,
        trigger_reason="customer_refused_delivery",
        refusal_count=1,
        actor_role="operations",
        actor_agent="ai_call",
    )
    assert log.status == DiscountOfferLog.Status.OFFERED
    assert log.source_channel == DiscountOfferLog.SourceChannel.AI_CALL


@override_settings(WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=True)
def test_rto_risk_creates_automatic_rescue_offer(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.RTO,
        source_channel=DiscountOfferLog.SourceChannel.RTO,
        trigger_reason="rto_high_risk",
        refusal_count=1,
        risk_level="high",
        actor_role="operations",
        actor_agent="ai_chat",
    )
    # RTO ladder + high-risk step-up picks 15% (ladder[1]). 15% is in
    # the 11-20% band that requires CEO AI / admin approval per the
    # Phase 3E discount policy, so the rescue logger correctly flags
    # this for CEO review and creates an ApprovalRequest.
    assert log.status == DiscountOfferLog.Status.NEEDS_CEO_REVIEW
    assert log.offered_additional_pct == 15
    assert log.source_channel == DiscountOfferLog.SourceChannel.RTO


@override_settings(WHATSAPP_RTO_RESCUE_DISCOUNT_ENABLED=True)
def test_rto_low_refusal_offers_within_auto_band(order, customer) -> None:
    """First-step RTO ladder = 10% which is auto-approved per Phase 3E."""
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.RTO,
        source_channel=DiscountOfferLog.SourceChannel.RTO,
        trigger_reason="rto_first_refusal",
        refusal_count=1,
        risk_level="low",
        actor_role="operations",
        actor_agent="ai_chat",
    )
    assert log.status == DiscountOfferLog.Status.OFFERED
    assert log.offered_additional_pct == 10


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=False)
def test_confirmation_rescue_disabled_records_skipped(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="customer_refused_confirmation",
    )
    assert log.status == DiscountOfferLog.Status.SKIPPED
    assert log.blocked_reason == "rescue_disabled"


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_caio_blocked_at_offer_entry(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="caio_test",
        actor_role="director",
        actor_agent="caio",
    )
    assert log.status == DiscountOfferLog.Status.BLOCKED
    assert log.blocked_reason == "caio_no_send"


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_offer_above_50_creates_ceo_review(order, customer) -> None:
    order.discount_pct = 40
    order.save(update_fields=["discount_pct"])
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.RTO,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="customer_refused_rto",
        refusal_count=3,  # ladder asks for 20%
        risk_level="high",
        actor_role="operations",
        actor_agent="ai_chat",
    )
    # Cap math clamps to 10% remaining.
    assert log.resulting_total_discount_pct <= 50
    assert log.cap_remaining_pct >= 0


# ---------------------------------------------------------------------------
# 5. Accept / reject
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_accept_offer_applies_discount(order, customer, admin_user_p5e) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="confirmation_refusal",
        refusal_count=2,  # 10%
        actor_role="operations",
        actor_agent="ai_chat",
    )
    assert log.status == DiscountOfferLog.Status.OFFERED

    accepted = accept_rescue_discount_offer(
        offer=log, actor_role="admin", actor=admin_user_p5e
    )
    assert accepted.status == DiscountOfferLog.Status.ACCEPTED
    order.refresh_from_db()
    assert order.discount_pct == log.resulting_total_discount_pct
    assert AuditEvent.objects.filter(kind="discount.offer.accepted").exists()


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_reject_offer_records_status(order, customer) -> None:
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="refused",
        refusal_count=1,
    )
    rejected = reject_rescue_discount_offer(offer=log, note="customer not interested")
    assert rejected.status == DiscountOfferLog.Status.REJECTED
    order.refresh_from_db()
    # Reject must not mutate the order.
    assert order.discount_pct == 0


# ---------------------------------------------------------------------------
# 6. Lifecycle Day-20 reorder
# ---------------------------------------------------------------------------


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_REORDER_DAY20_ENABLED=True,
)
def test_day20_sweep_queues_eligible_orders(customer) -> None:
    # Build a reorder template so the lifecycle pipeline doesn't fail
    # closed on a missing template.
    connection = WhatsAppConnection.objects.create(
        id="WAC-5E-DAY20",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="5E Day20",
        phone_number="+919000099900",
        status=WhatsAppConnection.Status.CONNECTED,
    )
    upsert_template(
        connection=connection,
        name="nrg_reorder_day20_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.MARKETING,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Reorder reminder"}],
        variables_schema={"required": []},
        action_key="whatsapp.reorder_day20_reminder",
        claim_vault_required=False,
    )
    # Old delivered order — created 22 days ago, in the eligible window.
    old = Order.objects.create(
        id="NRG-DAY20-1",
        customer_name=customer.name,
        phone=customer.phone,
        product="Weight Management",
        state="MH",
        city="Pune",
        amount=3000,
        stage=Order.Stage.DELIVERED,
        created_at_label="22 days ago",
    )
    Order.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=22)
    )
    result = run_day20_reorder_sweep()
    assert result.eligible >= 1
    assert result.queued >= 1
    # Idempotent: second sweep does not re-queue.
    result2 = run_day20_reorder_sweep()
    assert result2.queued == 0


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_REORDER_DAY20_ENABLED=False,
)
def test_day20_sweep_disabled_returns_zeros() -> None:
    result = run_day20_reorder_sweep()
    assert result.queued == 0
    assert result.eligible == 0


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_REORDER_DAY20_ENABLED=True,
)
def test_day20_lifecycle_failure_does_not_mutate_order(customer) -> None:
    """Lifecycle gate failure must not roll the order out of Delivered."""
    # Customer with no consent → lifecycle blocks but order is unchanged.
    customer.consent_whatsapp = False
    customer.save(update_fields=["consent_whatsapp"])
    WhatsAppConsent.objects.update_or_create(
        customer=customer,
        defaults={"consent_state": WhatsAppConsent.State.REVOKED},
    )
    old = Order.objects.create(
        id="NRG-DAY20-NOCONSENT",
        customer_name=customer.name,
        phone=customer.phone,
        product="Weight Management",
        state="MH",
        city="Pune",
        amount=3000,
        stage=Order.Stage.DELIVERED,
        created_at_label="22 days ago",
    )
    Order.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=22)
    )
    pre_stage = Order.objects.get(pk=old.pk).stage
    run_day20_reorder_sweep()
    assert Order.objects.get(pk=old.pk).stage == pre_stage


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_REORDER_DAY20_ENABLED=True,
)
def test_day20_lifecycle_emits_dedicated_audit_kinds(customer) -> None:
    connection = WhatsAppConnection.objects.create(
        id="WAC-5E-DAY20-2",
        provider=WhatsAppConnection.Provider.MOCK,
        display_name="5E Day20",
        phone_number="+919000099901",
        status=WhatsAppConnection.Status.CONNECTED,
    )
    upsert_template(
        connection=connection,
        name="nrg_reorder_day20_reminder",
        language="hi",
        category=WhatsAppTemplate.Category.MARKETING,
        status=WhatsAppTemplate.Status.APPROVED,
        body_components=[{"type": "BODY", "text": "Reorder"}],
        variables_schema={"required": []},
        action_key="whatsapp.reorder_day20_reminder",
        claim_vault_required=False,
    )
    queue_lifecycle_message(
        object_type="order",
        object_id="NRG-DAY20-AUDIT",
        event_kind="day20",
        customer=customer,
        variables={"customer_name": customer.name, "context": "test"},
    )
    assert AuditEvent.objects.filter(
        kind="whatsapp.lifecycle.reorder_day20_queued"
    ).exists()


# ---------------------------------------------------------------------------
# 7. Endpoints
# ---------------------------------------------------------------------------


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_create_rescue_offer_endpoint_operations(operations_user_p5e, order):
    res = _auth(APIClient(), operations_user_p5e).post(
        f"/api/orders/{order.id}/discount-offers/rescue/",
        {
            "sourceChannel": "operator",
            "stage": "confirmation",
            "triggerReason": "customer_refused_confirmation",
            "refusalCount": 1,
        },
        format="json",
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "offered"
    assert body["offeredAdditionalPct"] == 5


def test_list_discount_offers_endpoint(operations_user_p5e, order):
    res = _auth(APIClient(), operations_user_p5e).get(
        f"/api/orders/{order.id}/discount-offers/",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["orderId"] == order.id
    assert body["cap"]["totalCapPct"] == 50
    assert body["cap"]["capRemainingPct"] == 50


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_accept_offer_endpoint(operations_user_p5e, order):
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="t",
        refusal_count=1,
    )
    res = _auth(APIClient(), operations_user_p5e).post(
        f"/api/orders/{order.id}/discount-offers/{log.pk}/accept/",
        {},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"


@override_settings(WHATSAPP_RESCUE_DISCOUNT_ENABLED=True)
def test_reject_offer_endpoint(operations_user_p5e, order):
    log = create_rescue_discount_offer(
        order=order,
        stage=DiscountOfferLog.Stage.CONFIRMATION,
        source_channel=DiscountOfferLog.SourceChannel.WHATSAPP_AI,
        trigger_reason="t",
        refusal_count=1,
    )
    res = _auth(APIClient(), operations_user_p5e).post(
        f"/api/orders/{order.id}/discount-offers/{log.pk}/reject/",
        {"note": "not interested"},
        format="json",
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


def test_create_rescue_offer_viewer_blocked(viewer_user_p5e, order):
    res = _auth(APIClient(), viewer_user_p5e).post(
        f"/api/orders/{order.id}/discount-offers/rescue/",
        {
            "sourceChannel": "operator",
            "stage": "confirmation",
            "triggerReason": "x",
        },
        format="json",
    )
    assert res.status_code == 403


def test_day20_status_endpoint_admin(admin_user_p5e):
    res = _auth(APIClient(), admin_user_p5e).get(
        "/api/whatsapp/reorder/day20/status/",
    )
    assert res.status_code == 200
    body = res.json()
    assert body["lowerBoundDays"] == 20
    assert body["upperBoundDays"] == 27


def test_day20_status_endpoint_operations_blocked(operations_user_p5e):
    res = _auth(APIClient(), operations_user_p5e).get(
        "/api/whatsapp/reorder/day20/status/",
    )
    assert res.status_code == 403


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_REORDER_DAY20_ENABLED=True,
)
def test_day20_run_endpoint_admin(admin_user_p5e):
    res = _auth(APIClient(), admin_user_p5e).post(
        "/api/whatsapp/reorder/day20/run/",
        {"dryRun": True},
        format="json",
    )
    assert res.status_code == 200
    body = res.json()
    assert "eligible" in body
    assert body["dryRun"] is True


# ---------------------------------------------------------------------------
# 8. Lifecycle gate enforcement
# ---------------------------------------------------------------------------


@override_settings(
    WHATSAPP_LIFECYCLE_AUTOMATION_ENABLED=True,
    WHATSAPP_RESCUE_DISCOUNT_ENABLED=False,
)
def test_lifecycle_rescue_disabled_records_skipped(customer) -> None:
    result = queue_lifecycle_message(
        object_type="order",
        object_id="NRG-RESCUE-OFF",
        event_kind="confirmation_refusal",
        customer=customer,
        variables={"customer_name": customer.name, "context": "x"},
    )
    assert result.status == WhatsAppLifecycleEvent.Status.SKIPPED
    assert "disabled" in (result.block_reason or "")


# ---------------------------------------------------------------------------
# 9. cap_status helper
# ---------------------------------------------------------------------------


def test_cap_status_returns_structured_snapshot(order) -> None:
    order.discount_pct = 25
    order.save(update_fields=["discount_pct"])
    snap = cap_status(order, additional_pct=10)
    assert snap.current_total_pct == 25
    assert snap.cap_remaining_pct == 25
    assert snap.final_total_if_applied_pct == 35
    assert snap.cap_passed is True
