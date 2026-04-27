"""Phase 3E — Business configuration foundation tests.

Covers:
- Product catalog read endpoints (camelCase) + admin/director writes + viewer/operations blocked.
- Discount policy (validate_discount).
- Advance payment policy (default ₹499).
- Reward / penalty deterministic scoring (capped at +100 / -100).
- Approval matrix endpoint shape.
- WhatsApp design constants.
- Compliance hard-stops still hold (Claim Vault still enforced; CAIO still cannot execute).
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.catalog.models import Product, ProductCategory, ProductSKU


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def director_user(db):
    from apps.accounts.models import User

    user = User.objects.create_user(
        username="director_user",
        password="director12345",
        email="director@nirogidhara.test",
    )
    user.role = User.Role.DIRECTOR
    user.save(update_fields=["role"])
    return user


def _seed_catalog():
    category = ProductCategory.objects.create(
        id="CAT-WEIGHT",
        name="Weight Management",
        slug="weight-management",
        description="Ayurvedic weight management formulations.",
        sort_order=1,
    )
    product = Product.objects.create(
        id="PRD-WM-001",
        category=category,
        name="WeightCare 30",
        slug="weightcare-30",
        description="Daily Ayurvedic weight management capsules.",
        default_price_inr=3000,
        default_quantity_label="30 capsules",
        product_cost_inr=900,
        default_usage_instructions="2 capsules after meals, twice daily.",
    )
    sku = ProductSKU.objects.create(
        id="SKU-WM-001-30",
        product=product,
        sku_code="WM-30",
        title="WeightCare · 30-day pack",
        quantity_label="30 capsules",
        mrp_inr=3000,
        selling_price_inr=2640,
        product_cost_inr=900,
        stock_quantity=420,
    )
    return category, product, sku


# ---------------------------------------------------------------------------
# 1. Catalog read endpoints
# ---------------------------------------------------------------------------


def test_catalog_categories_list_camelcase() -> None:
    _seed_catalog()
    res = APIClient().get("/api/catalog/categories/")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) == 1
    row = body[0]
    assert row["id"] == "CAT-WEIGHT"
    assert row["name"] == "Weight Management"
    assert row["slug"] == "weight-management"
    assert row["isActive"] is True
    assert row["sortOrder"] == 1


def test_catalog_products_list_with_skus() -> None:
    _seed_catalog()
    res = APIClient().get("/api/catalog/products/")
    assert res.status_code == 200
    products = res.json()
    assert len(products) == 1
    p = products[0]
    assert p["id"] == "PRD-WM-001"
    assert p["categoryId"] == "CAT-WEIGHT"
    assert p["defaultPriceInr"] == 3000
    assert p["defaultQuantityLabel"] == "30 capsules"
    assert p["productCostInr"] == 900
    assert p["isActive"] is True
    assert isinstance(p["skus"], list)
    assert len(p["skus"]) == 1
    sku = p["skus"][0]
    assert sku["skuCode"] == "WM-30"
    assert sku["sellingPriceInr"] == 2640


def test_catalog_skus_list_filterable_by_product() -> None:
    _, product, _ = _seed_catalog()
    res = APIClient().get(f"/api/catalog/skus/?productId={product.id}")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["productId"] == product.id


# ---------------------------------------------------------------------------
# 2. Catalog write endpoints — role gating
# ---------------------------------------------------------------------------


def test_catalog_write_anonymous_blocked() -> None:
    res = APIClient().post(
        "/api/catalog/categories/",
        {"id": "CAT-X", "name": "X", "slug": "x", "sortOrder": 0, "isActive": True},
        format="json",
    )
    assert res.status_code == 401


def test_catalog_write_viewer_blocked(viewer_user, auth_client) -> None:
    res = auth_client(viewer_user).post(
        "/api/catalog/categories/",
        {"id": "CAT-X", "name": "X", "slug": "x", "sortOrder": 0, "isActive": True},
        format="json",
    )
    assert res.status_code == 403


def test_catalog_write_operations_blocked(operations_user, auth_client) -> None:
    res = auth_client(operations_user).post(
        "/api/catalog/categories/",
        {"id": "CAT-X", "name": "X", "slug": "x", "sortOrder": 0, "isActive": True},
        format="json",
    )
    assert res.status_code == 403


def test_admin_can_create_category(admin_user, auth_client) -> None:
    before = AuditEvent.objects.count()
    res = auth_client(admin_user).post(
        "/api/catalog/categories/",
        {
            "id": "CAT-IMMUNITY",
            "name": "Immunity",
            "slug": "immunity",
            "description": "Immunity formulations",
            "isActive": True,
            "sortOrder": 4,
        },
        format="json",
    )
    assert res.status_code == 201
    assert ProductCategory.objects.filter(id="CAT-IMMUNITY").exists()
    assert AuditEvent.objects.filter(kind="catalog.category.created").count() >= 1
    assert AuditEvent.objects.count() > before


def test_admin_can_create_product(admin_user, auth_client) -> None:
    _seed_catalog()
    res = auth_client(admin_user).post(
        "/api/catalog/products/",
        {
            "id": "PRD-WM-002",
            "categoryId": "CAT-WEIGHT",
            "name": "WeightCare 60",
            "slug": "weightcare-60",
            "description": "Bigger pack.",
            "defaultPriceInr": 5000,
            "defaultQuantityLabel": "60 capsules",
            "productCostInr": 1600,
            "isActive": True,
            "activeClaimProducts": ["Weight Management"],
            "metadata": {},
        },
        format="json",
    )
    assert res.status_code == 201, res.json()
    assert AuditEvent.objects.filter(kind="catalog.product.created").exists()


def test_admin_can_create_sku(admin_user, auth_client) -> None:
    _seed_catalog()
    res = auth_client(admin_user).post(
        "/api/catalog/skus/",
        {
            "id": "SKU-WM-001-60",
            "productId": "PRD-WM-001",
            "skuCode": "WM-60",
            "title": "WeightCare · 60-day pack",
            "quantityLabel": "60 capsules",
            "mrpInr": 5400,
            "sellingPriceInr": 4500,
            "productCostInr": 1600,
            "stockQuantity": 50,
            "isActive": True,
            "metadata": {},
        },
        format="json",
    )
    assert res.status_code == 201, res.json()
    assert AuditEvent.objects.filter(kind="catalog.sku.created").exists()


# ---------------------------------------------------------------------------
# 3. Discount policy
# ---------------------------------------------------------------------------


def test_discount_auto_under_10_percent() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(10, actor_role="operations")
    assert result.allowed is True
    assert result.requires_approval is False
    assert result.policy_band == "auto"


def test_discount_15_percent_requires_approval_for_operations() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(15, actor_role="operations")
    assert result.allowed is False
    assert result.requires_approval is True
    assert result.policy_band == "approval"


def test_discount_15_percent_approved_by_admin() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(
        15,
        actor_role="operations",
        approval_context={"approved_by": "admin", "reason": "VIP customer"},
    )
    assert result.allowed is True
    assert result.policy_band == "approval"


def test_discount_20_percent_self_approved_by_admin() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(
        20,
        actor_role="admin",
        approval_context={"self_approve": True},
    )
    assert result.allowed is True


def test_discount_above_20_blocked_without_director_override() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(
        25,
        actor_role="admin",
        approval_context={"approved_by": "admin"},
    )
    assert result.allowed is False
    assert result.policy_band == "blocked"
    assert "over_hard_cap" in result.notes


def test_discount_above_20_allowed_via_director_override() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(
        25,
        actor_role="director",
        approval_context={"director_override": True, "reason": "festival promo"},
    )
    assert result.allowed is True
    assert result.policy_band == "director_override"


def test_discount_negative_or_over_100_blocked() -> None:
    from apps.orders.discounts import validate_discount

    assert validate_discount(-1, actor_role="admin").allowed is False
    assert validate_discount(101, actor_role="admin").allowed is False


def test_discount_unknown_role_blocked() -> None:
    from apps.orders.discounts import validate_discount

    result = validate_discount(5, actor_role="random-role")
    assert result.allowed is False
    assert "role_not_authorized" in result.notes


# ---------------------------------------------------------------------------
# 4. Advance payment policy
# ---------------------------------------------------------------------------


def test_resolve_advance_amount_default_499() -> None:
    from apps.payments.policies import (
        FIXED_ADVANCE_AMOUNT_INR,
        resolve_advance_amount,
    )

    assert FIXED_ADVANCE_AMOUNT_INR == 499
    assert resolve_advance_amount(None) == 499
    assert resolve_advance_amount(0) == 499
    assert resolve_advance_amount(799) == 799


def test_payment_link_advance_defaults_to_499(operations_user, auth_client) -> None:
    """POST /api/payments/links/ with no amount should default Advance to ₹499."""
    from apps.orders.models import Order

    Order.objects.create(
        id="NRG-PHASE3E-1",
        customer_name="Test",
        phone="+91 9000000099",
        product="Weight Management",
        quantity=1,
        amount=2640,
        state="MH",
        city="Pune",
        rto_risk=Order.RtoRisk.LOW,
        rto_score=10,
        agent="Test agent",
        stage=Order.Stage.ORDER_PUNCHED,
    )
    res = auth_client(operations_user).post(
        "/api/payments/links/",
        {
            "orderId": "NRG-PHASE3E-1",
            # amount intentionally omitted — should default to 499
            "gateway": "Razorpay",
            "type": "Advance",
            "customerName": "Test",
        },
        format="json",
    )
    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["payment"]["amount"] == 499


# ---------------------------------------------------------------------------
# 5. Reward / penalty scoring
# ---------------------------------------------------------------------------


def test_reward_capped_at_100() -> None:
    from apps.rewards.scoring import REWARD_MAX_TOTAL, calculate_order_reward_penalty

    fake_order = {
        "id": "NRG-90011",
        "stage": "Delivered",
        "rto_risk": "Low",
        "advance_paid": True,
        "advance_amount": 499,
        "discount_pct": 5,
        "state": "MH",
        "city": "Pune",
    }
    result = calculate_order_reward_penalty(
        fake_order,
        context={
            "net_profit_inr": 800,
            "customer_satisfaction": "positive",
            "reorder_potential": "high",
            "clean_data": True,
            "compliance_safe": True,
        },
    )
    # Sum of all rewards exceeds 100; must be capped.
    raw = sum(r.points for r in result.rewards)
    assert raw >= REWARD_MAX_TOTAL  # raw 100 (30+25+10+10+10+5+10) — capped at 100
    assert result.reward_total <= REWARD_MAX_TOTAL


def test_penalty_capped_at_100() -> None:
    from apps.rewards.scoring import PENALTY_MAX_TOTAL, calculate_order_reward_penalty

    fake_order = {
        "id": "NRG-90012",
        "stage": "RTO",
        "rto_risk": "High",
        "advance_paid": False,
        "advance_amount": 0,
        "discount_pct": 30,  # > 20% without override
        "state": "",
        "city": "",
        "confirmation_outcome": "cancelled",
    }
    result = calculate_order_reward_penalty(
        fake_order,
        context={
            "risky_claim_logged": True,
            "side_effect_or_legal_mishandled": True,
            "rto_warning_was_raised": True,
            "fake_lead_quality": True,
        },
    )
    assert result.penalty_total == PENALTY_MAX_TOTAL


def test_scoring_records_missing_data() -> None:
    from apps.rewards.scoring import calculate_order_reward_penalty

    fake_order = {
        "id": "NRG-90013",
        "stage": "Delivered",
        "advance_paid": True,
        "advance_amount": 499,
        "state": "MH",
        "city": "Pune",
    }
    result = calculate_order_reward_penalty(fake_order, context={})
    # net_profit / satisfaction / reorder / compliance_safe missing.
    assert "net_profit_inr" in result.missing_data
    assert "customer_satisfaction" in result.missing_data
    assert "reorder_potential" in result.missing_data
    assert "compliance_safe" in result.missing_data


def test_scoring_delivered_simple_reward() -> None:
    from apps.rewards.scoring import calculate_order_reward_penalty

    fake_order = {
        "id": "NRG-90014",
        "stage": "Delivered",
        "advance_paid": True,
        "advance_amount": 499,
        "discount_pct": 5,
        "state": "MH",
        "city": "Pune",
    }
    result = calculate_order_reward_penalty(fake_order, context={"net_profit_inr": 600})
    codes = {r.code for r in result.rewards}
    assert "delivered_order" in codes
    assert "advance_paid" in codes
    assert "healthy_net_profit" in codes
    assert result.net_score > 0


# ---------------------------------------------------------------------------
# 6. Approval matrix endpoint
# ---------------------------------------------------------------------------


def test_approval_matrix_endpoint_returns_actions() -> None:
    res = APIClient().get("/api/ai/approval-matrix/")
    assert res.status_code == 200
    body = res.json()
    assert "actions" in body
    actions = {row["action"] for row in body["actions"]}
    expected = {
        "lead.create",
        "lead.call.trigger",
        "payment.link.advance_499",
        "discount.up_to_10",
        "discount.11_to_20",
        "discount.above_20",
        "shipment.dispatch_after_confirmed",
        "rto.rescue.call_or_message",
        "whatsapp.payment_reminder",
        "whatsapp.broadcast_or_campaign",
        "ai.prompt_version.activate",
        "ai.sandbox.disable",
        "ai.production.live_mode_switch",
        "complaint.medical_emergency",
        "ad.budget_change",
    }
    assert expected <= actions


def test_approval_matrix_director_override_for_above_20_discount() -> None:
    from apps.ai_governance.approval_matrix import lookup_action

    row = lookup_action("discount.above_20")
    assert row is not None
    assert row["approver"] == "director"
    assert row["mode"] == "director_override"


# ---------------------------------------------------------------------------
# 7. WhatsApp design scaffold
# ---------------------------------------------------------------------------


def test_whatsapp_supports_sales_and_support_types() -> None:
    from apps.crm.whatsapp_design import SUPPORTED_MESSAGE_TYPES

    codes = {t.code for t in SUPPORTED_MESSAGE_TYPES}
    expected = {
        "follow_up",
        "payment_reminder",
        "confirmation_reminder",
        "delivery_reminder",
        "rto_rescue",
        "usage_explanation",
        "support_complaint",
        "reorder_reminder",
        "broadcast_campaign",
    }
    assert expected <= codes


def test_whatsapp_broadcast_needs_admin_approval() -> None:
    from apps.crm.whatsapp_design import SUPPORTED_MESSAGE_TYPES

    by_code = {t.code: t for t in SUPPORTED_MESSAGE_TYPES}
    assert by_code["broadcast_campaign"].needs_admin_approval is True
    assert by_code["payment_reminder"].requires_consent is True


# ---------------------------------------------------------------------------
# 8. Compliance hard-stops still hold
# ---------------------------------------------------------------------------


def test_phase3e_does_not_relax_caio_no_execute() -> None:
    """CAIO must still refuse execution intents — Phase 3E adds business
    config but cannot relax §26 #5.
    """
    from apps.ai_governance.services import (
        CAIO_FORBIDDEN_INTENTS,
        run_readonly_agent_analysis,
    )
    from apps.ai_governance.models import AgentRun

    assert "execute" in CAIO_FORBIDDEN_INTENTS
    run = run_readonly_agent_analysis(
        agent="caio",
        input_payload={"intent": "execute"},
        triggered_by="phase3e-test",
    )
    assert run.status == AgentRun.Status.FAILED


def test_phase3e_claim_vault_still_required_for_medical_runs() -> None:
    """When the Claim Vault is empty and the agent is medical/product-bound,
    the run must still fail closed before any LLM dispatch.
    """
    from apps.ai_governance.services import run_readonly_agent_analysis
    from apps.ai_governance.models import AgentRun
    from apps.compliance.models import Claim

    # Claim vault explicitly empty.
    Claim.objects.all().delete()
    run = run_readonly_agent_analysis(
        agent="compliance",
        input_payload={"product": "Weight Management"},
        triggered_by="phase3e-test",
    )
    assert run.status == AgentRun.Status.FAILED
