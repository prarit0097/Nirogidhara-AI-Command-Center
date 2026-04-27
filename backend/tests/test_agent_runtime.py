"""Phase 3B tests — per-agent runtime services + endpoints.

Covers:

1. CEO runtime — payload pulled from DB, AgentRun created, CeoBriefing
   refreshed when the run succeeds with usable output.
2. CAIO runtime — AgentRun created, never touches business write paths.
3. Ads runtime — payload includes Meta attribution buckets.
4. RTO runtime — payload exposes high-risk orders + risky shipments.
5. Sales Growth runtime — payload includes call/order/payment slices.
6. CFO runtime — disabled provider returns ``skipped`` cleanly.
7. Compliance runtime — fails closed when the Claim Vault is empty.
8. Permission gates — admin/director allowed, viewer/operations blocked.
9. Status endpoint surfaces the last run per agent.
10. Management command runs CEO + CAIO and persists both AgentRuns.
11. ``ai.agent_runtime.completed`` and ``ai.ceo_brief.generated`` audit
    events fire on the right paths.
"""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.ai_governance.models import AgentRun, CaioAudit, CeoBriefing
from apps.ai_governance.services.agents import ads, caio, ceo, cfo, compliance, rto, sales_growth
from apps.audit.models import AuditEvent
from apps.calls.models import Call
from apps.compliance.models import Claim
from apps.crm.models import Lead
from apps.integrations.ai.base import AdapterResult, AdapterStatus
from apps.orders.models import Order
from apps.shipments.models import Shipment


# ---------- helpers ----------


def _seed_one_claim() -> Claim:
    return Claim.objects.create(
        product="Weight Management",
        approved=["Supports healthy metabolism"],
        disallowed=["Guaranteed weight loss"],
        doctor="Approved",
        compliance="Approved",
        version="v3.2",
    )


def _seed_one_order(**overrides) -> Order:
    defaults = dict(
        id="NRG-RT-001",
        customer_name="Demo",
        phone="+91 9000000000",
        product="Weight Management",
        amount=2640,
        discount_pct=12,
        advance_paid=True,
        advance_amount=499,
        state="Maharashtra",
        city="Pune",
        rto_risk="High",
        rto_score=72,
        agent="Calling AI · Vaani-3",
        stage=Order.Stage.OUT_FOR_DELIVERY,
    )
    defaults.update(overrides)
    return Order.objects.create(**defaults)


def _seed_meta_lead() -> Lead:
    return Lead.objects.create(
        id="LD-RT-META-001",
        name="Meta Lead",
        phone="+91 9000000111",
        state="Maharashtra",
        city="Pune",
        language="Hinglish",
        source="Meta Ads",
        campaign="Monsoon Detox",
        product_interest="Weight Management",
        meta_leadgen_id="lead_test_001",
        meta_campaign_id="camp_777",
        meta_ad_id="ad_42",
        meta_form_id="form_99",
        source_detail="ad_42",
    )


# ---------- 1. CEO runtime ----------


def test_ceo_runtime_creates_agent_run(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/ceo/daily-brief/", format="json")
    assert res.status_code == 201
    body = res.json()
    assert body["agent"] == "ceo"
    assert body["dryRun"] is True
    assert body["status"] in {"skipped", "failed", "success"}
    # Disabled provider → skipped, no LLM dispatched.
    assert body["status"] == "skipped"
    assert AgentRun.objects.filter(agent="ceo").exists()


def test_ceo_runtime_refreshes_briefing_on_success(admin_user, auth_client, settings) -> None:
    """On successful runs with usable output, a new CeoBriefing row appears."""
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    _seed_one_claim()
    fake_result = AdapterResult(
        status=AdapterStatus.SUCCESS,
        provider="openai",
        model="gpt-4o-mini",
        output={
            "summary": "Delivered profit up 14% week over week.",
            "headline": "Strong week — push Men Wellness budget",
            "alerts": ["Rajasthan COD RTO climbing"],
            "recommendations": [
                {
                    "id": "rec-1",
                    "title": "Increase Men Wellness budget by 15%",
                    "reason": "Highest delivered profit-per-lead.",
                    "impact": "+₹2.1L weekly",
                    "requires": "Prarit approval",
                }
            ],
        },
        latency_ms=42,
    )
    before = CeoBriefing.objects.count()
    with patch(
        "apps.integrations.ai.openai_client.dispatch", return_value=fake_result
    ):
        client = auth_client(admin_user)
        res = client.post("/api/ai/agent-runtime/ceo/daily-brief/", format="json")
    assert res.status_code == 201
    assert res.json()["status"] == "success"
    assert CeoBriefing.objects.count() == before + 1
    latest = CeoBriefing.objects.order_by("-updated_at").first()
    assert "Men Wellness" in latest.headline
    assert latest.recommendations.count() == 1
    # Audit ledger captured the briefing-generated kind.
    assert AuditEvent.objects.filter(kind="ai.ceo_brief.generated").exists()


def test_ceo_runtime_does_not_refresh_briefing_when_skipped(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    before = CeoBriefing.objects.count()
    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/ceo/daily-brief/", format="json")
    assert res.status_code == 201
    assert res.json()["status"] == "skipped"
    assert CeoBriefing.objects.count() == before


# ---------- 2. CAIO runtime ----------


def test_caio_runtime_creates_agent_run(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/caio/audit-sweep/", format="json")
    assert res.status_code == 201
    body = res.json()
    assert body["agent"] == "caio"
    assert body["dryRun"] is True
    assert AgentRun.objects.filter(agent="caio").exists()


def test_caio_runtime_payload_does_not_carry_execute_intent(db) -> None:
    """The CAIO runtime must build a payload with no execution intents — if
    any keyword from CAIO_FORBIDDEN_INTENTS leaks in, the LLM call would be
    refused. This guards against future refactors."""
    payload = caio.build_input_payload()
    serialized = str(payload).lower()
    for forbidden in (
        "execute",
        "create_order",
        "create_payment",
        "create_shipment",
        "trigger_call",
        "assign_lead",
        "approve",
    ):
        # Allow these strings to appear inside other words (e.g.
        # ``executable``) — but the top-level keys must not match.
        assert forbidden not in payload, f"CAIO payload leaks intent {forbidden!r}"


# ---------- 3. Ads runtime ----------


def test_ads_runtime_reads_meta_attribution(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    _seed_meta_lead()
    payload = ads.build_input_payload()
    assert payload["meta_total_leads"] >= 1
    campaigns = {row["key"] for row in payload["by_campaign"]}
    assert "camp_777" in campaigns

    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/ads/analyze/", format="json")
    assert res.status_code == 201
    assert AgentRun.objects.filter(agent="ads").exists()


# ---------- 4. RTO runtime ----------


def test_rto_runtime_reads_risk_data(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    order = _seed_one_order()
    Shipment.objects.create(
        awb="DLH00009999",
        order_id=order.id,
        customer=order.customer_name,
        state=order.state,
        city=order.city,
        status="RTO Initiated",
        risk_flag="RTO",
    )
    payload = rto.build_input_payload()
    assert any(o["id"] == order.id for o in payload["high_risk_orders"])
    assert any(s["awb"] == "DLH00009999" for s in payload["risky_shipments"])

    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/rto/analyze/", format="json")
    assert res.status_code == 201
    assert AgentRun.objects.filter(agent="rto").exists()


# ---------- 5. Sales Growth runtime ----------


def test_sales_growth_runtime_reads_calls_orders_payments(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    _seed_one_order()
    Call.objects.create(
        id="CL-SG-001",
        lead_id="LD-99001",
        customer="Demo",
        phone="+91 9000000111",
        agent="Calling AI · Vaani-3",
        language="Hinglish",
        status=Call.Status.COMPLETED,
        sentiment=Call.Sentiment.POSITIVE,
    )
    payload = sales_growth.build_input_payload()
    assert "orders_by_stage" in payload
    assert "call_status" in payload
    assert "advance_ratio" in payload

    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runtime/sales-growth/analyze/", format="json"
    )
    assert res.status_code == 201
    assert AgentRun.objects.filter(agent="sales_growth").exists()


# ---------- 6. CFO runtime — disabled returns skipped ----------


def test_cfo_runtime_skipped_when_disabled(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    _seed_one_order()
    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/cfo/analyze/", format="json")
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "skipped"
    assert body["provider"] == "disabled"


# ---------- 7. Compliance runtime — fails closed without vault ----------


def test_compliance_runtime_fails_closed_when_vault_empty(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "disabled"
    Claim.objects.all().delete()  # vault empty
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runtime/compliance/analyze/", format="json"
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "failed"
    assert "claim" in body["errorMessage"].lower()
    failed_audit = AuditEvent.objects.filter(kind="ai.agent_run.failed").first()
    assert failed_audit is not None


def test_compliance_runtime_succeeds_with_vault(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runtime/compliance/analyze/", format="json"
    )
    assert res.status_code == 201
    body = res.json()
    # disabled provider → skipped (the prompt was built successfully because
    # the vault has at least one approved claim).
    assert body["status"] == "skipped"


# ---------- 8. Permission gating ----------


@pytest.mark.parametrize(
    "url",
    [
        "/api/ai/agent-runtime/ceo/daily-brief/",
        "/api/ai/agent-runtime/caio/audit-sweep/",
        "/api/ai/agent-runtime/ads/analyze/",
        "/api/ai/agent-runtime/rto/analyze/",
        "/api/ai/agent-runtime/sales-growth/analyze/",
        "/api/ai/agent-runtime/cfo/analyze/",
        "/api/ai/agent-runtime/compliance/analyze/",
    ],
)
def test_anonymous_blocked_from_runtime_endpoints(url) -> None:
    res = APIClient().post(url, format="json")
    assert res.status_code in {401, 403}


def test_viewer_blocked_from_runtime(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.post("/api/ai/agent-runtime/ceo/daily-brief/", format="json")
    assert res.status_code == 403


def test_operations_blocked_from_runtime(operations_user, auth_client) -> None:
    client = auth_client(operations_user)
    res = client.post("/api/ai/agent-runtime/ceo/daily-brief/", format="json")
    assert res.status_code == 403


def test_viewer_blocked_from_runtime_status(viewer_user, auth_client) -> None:
    client = auth_client(viewer_user)
    res = client.get("/api/ai/agent-runtime/status/")
    assert res.status_code == 403


# ---------- 9. Status endpoint ----------


def test_runtime_status_returns_last_runs(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    AgentRun.objects.create(
        id="AR-LAST-CEO",
        agent="ceo",
        status=AgentRun.Status.SKIPPED,
        provider="disabled",
    )
    client = auth_client(admin_user)
    res = client.get("/api/ai/agent-runtime/status/")
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "3B"
    assert body["dryRunOnly"] is True
    assert body["lastRuns"]["ceo"]["id"] == "AR-LAST-CEO"
    assert body["lastRuns"]["caio"] is None


# ---------- 10. Management command ----------


def test_run_daily_ai_briefing_command(db, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    out = StringIO()
    call_command("run_daily_ai_briefing", "--triggered-by", "test-cron", stdout=out)
    output = out.getvalue()
    assert "CEO daily briefing" in output
    assert "CAIO audit sweep" in output
    assert AgentRun.objects.filter(agent="ceo", triggered_by="test-cron").exists()
    assert AgentRun.objects.filter(agent="caio", triggered_by="test-cron").exists()


def test_run_daily_ai_briefing_command_skip_caio(db, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    AgentRun.objects.all().delete()
    out = StringIO()
    call_command(
        "run_daily_ai_briefing",
        "--triggered-by",
        "test-cron-2",
        "--skip-caio",
        stdout=out,
    )
    assert AgentRun.objects.filter(agent="ceo").exists()
    assert not AgentRun.objects.filter(agent="caio").exists()


# ---------- 11. Audit kinds ----------


def test_runtime_writes_completed_audit_event(admin_user, auth_client, settings) -> None:
    settings.AI_PROVIDER = "disabled"
    _seed_one_claim()
    AuditEvent.objects.all().delete()
    client = auth_client(admin_user)
    res = client.post("/api/ai/agent-runtime/ads/analyze/", format="json")
    assert res.status_code == 201
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.agent_runtime.completed" in kinds
    assert "ai.agent_run.created" in kinds


def test_compliance_runtime_failure_writes_failed_runtime_audit(
    admin_user, auth_client, settings
) -> None:
    settings.AI_PROVIDER = "disabled"
    Claim.objects.all().delete()
    AuditEvent.objects.all().delete()
    client = auth_client(admin_user)
    res = client.post(
        "/api/ai/agent-runtime/compliance/analyze/", format="json"
    )
    assert res.status_code == 201
    assert res.json()["status"] == "failed"
    kinds = set(AuditEvent.objects.values_list("kind", flat=True))
    assert "ai.agent_runtime.failed" in kinds
