"""Smoke tests for every endpoint in ``frontend/src/services/api.ts``.

Each test asserts:
  1. HTTP 200
  2. The response shape matches what the corresponding TypeScript interface
     in ``frontend/src/types/domain.ts`` expects (key names, types).

If a key gets renamed or removed by accident, these tests catch it before
the frontend breaks.
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def client(seeded) -> APIClient:
    return APIClient()


def test_healthz(client: APIClient) -> None:
    res = client.get("/api/healthz/")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_dashboard_metrics(client: APIClient) -> None:
    res = client.get("/api/dashboard/metrics/")
    assert res.status_code == 200
    data = res.json()
    assert "leadsToday" in data and data["leadsToday"]["value"] == 1240
    assert "netProfit" in data and "deltaPct" in data["netProfit"]


def test_dashboard_activity(client: APIClient) -> None:
    res = client.get("/api/dashboard/activity/")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 8
    sample = data[0]
    assert {"time", "icon", "text", "tone"} <= sample.keys()
    assert sample["tone"] in {"success", "info", "warning", "danger"}


def test_leads_list_and_detail(client: APIClient) -> None:
    res = client.get("/api/leads/")
    assert res.status_code == 200
    leads = res.json()
    assert len(leads) == 42
    sample = leads[0]
    # Required camelCase fields the frontend Lead interface expects.
    assert {
        "id",
        "name",
        "phone",
        "state",
        "city",
        "language",
        "source",
        "campaign",
        "productInterest",
        "status",
        "quality",
        "qualityScore",
        "assignee",
        "duplicate",
        "createdAt",
    } <= sample.keys()
    detail = client.get(f"/api/leads/{sample['id']}/").json()
    assert detail["id"] == sample["id"]


def test_customers_list_and_detail(client: APIClient) -> None:
    res = client.get("/api/customers/")
    assert res.status_code == 200
    customers = res.json()
    assert len(customers) == 24
    c = customers[0]
    assert "consent" in c and {"call", "whatsapp", "marketing"} <= c["consent"].keys()
    assert {"leadId", "diseaseCategory", "lifestyleNotes", "aiSummary", "riskFlags", "reorderProbability"} <= c.keys()
    detail = client.get(f"/api/customers/{c['id']}/").json()
    assert detail["id"] == c["id"]


def test_orders_and_pipeline(client: APIClient) -> None:
    res = client.get("/api/orders/")
    assert res.status_code == 200
    orders = res.json()
    assert len(orders) == 60
    o = orders[0]
    assert {"id", "customerName", "rtoRisk", "rtoScore", "ageHours", "createdAt", "stage"} <= o.keys()

    pipeline = client.get("/api/orders/pipeline/").json()
    assert len(pipeline) == 60


def test_confirmation_queue(client: APIClient) -> None:
    res = client.get("/api/confirmation/queue/")
    assert res.status_code == 200
    queue = res.json()
    if queue:
        assert {"hoursWaiting", "addressConfidence", "checklist"} <= queue[0].keys()


def test_calls_and_active(client: APIClient) -> None:
    calls = client.get("/api/calls/").json()
    assert len(calls) == 18
    assert {"id", "leadId", "customer", "scriptCompliance", "paymentLinkSent"} <= calls[0].keys()

    active = client.get("/api/calls/active/").json()
    assert active["id"] == "CL-LIVE-001"
    assert len(active["transcript"]) == 7
    assert {"who", "text"} <= active["transcript"][0].keys()

    transcript = client.get("/api/calls/active/transcript/").json()
    assert len(transcript) == 7


def test_payments(client: APIClient) -> None:
    res = client.get("/api/payments/")
    assert res.status_code == 200
    payments = res.json()
    assert len(payments) == 30
    assert {"id", "orderId", "customer", "amount", "gateway", "status", "type", "time"} <= payments[0].keys()


def test_shipments(client: APIClient) -> None:
    res = client.get("/api/shipments/")
    assert res.status_code == 200
    shipments = res.json()
    assert len(shipments) >= 30
    assert {"awb", "orderId", "customer", "timeline"} <= shipments[0].keys()
    assert len(shipments[0]["timeline"]) == 5


def test_rto_risk(client: APIClient) -> None:
    res = client.get("/api/rto/risk/")
    assert res.status_code == 200
    risk = res.json()
    if risk:
        assert {"riskReasons", "rescueStatus"} <= risk[0].keys()


def test_agents_and_hierarchy(client: APIClient) -> None:
    agents = client.get("/api/agents/").json()
    assert len(agents) == 19
    assert {"id", "name", "role", "status", "health", "reward", "penalty", "lastAction", "critical", "group"} <= agents[0].keys()

    h = client.get("/api/agents/hierarchy/").json()
    assert h["root"] == "Prarit Sidana (Director)"
    assert h["ceo"] == "CEO AI Agent"
    assert h["caio"] == "CAIO Agent"
    assert len(h["departments"]) == 17  # 19 minus ceo + caio


def test_ceo_briefing(client: APIClient) -> None:
    b = client.get("/api/ai/ceo-briefing/").json()
    assert b["headline"]
    assert len(b["recommendations"]) == 3
    assert {"id", "title", "reason", "impact", "requires"} <= b["recommendations"][0].keys()
    assert len(b["alerts"]) == 2


def test_caio_audits(client: APIClient) -> None:
    audits = client.get("/api/ai/caio-audits/").json()
    assert len(audits) == 5
    assert {"agent", "issue", "severity", "suggestion", "status"} <= audits[0].keys()


def test_rewards(client: APIClient) -> None:
    rewards = client.get("/api/rewards/").json()
    assert len(rewards) > 0
    assert {"name", "reward", "penalty", "net"} <= rewards[0].keys()
    # net should be reward - penalty
    assert rewards[0]["net"] == rewards[0]["reward"] - rewards[0]["penalty"]


def test_compliance_claims(client: APIClient) -> None:
    claims = client.get("/api/compliance/claims/").json()
    assert len(claims) == 4
    assert {"product", "approved", "disallowed", "doctor", "compliance", "version"} <= claims[0].keys()


def test_learning_recordings(client: APIClient) -> None:
    recs = client.get("/api/learning/recordings/").json()
    assert len(recs) == 5
    assert {"id", "agent", "duration", "date", "stage", "qa", "compliance", "outcome"} <= recs[0].keys()


def test_analytics_composite(client: APIClient) -> None:
    a = client.get("/api/analytics/").json()
    assert len(a["funnel"]) == 7
    assert len(a["revenueTrend"]) == 7
    assert len(a["stateRto"]) == 7
    assert len(a["productPerformance"]) == 8
    assert len(a["discountImpact"]) == 6


def test_analytics_subroutes(client: APIClient) -> None:
    assert len(client.get("/api/analytics/funnel/").json()) == 7
    assert len(client.get("/api/analytics/revenue-trend/").json()) == 7
    assert len(client.get("/api/analytics/state-rto/").json()) == 7
    assert len(client.get("/api/analytics/product-performance/").json()) == 8


def test_settings(client: APIClient) -> None:
    s = client.get("/api/settings/").json()
    assert "approvalMatrix" in s
    assert "integrations" in s
    assert "killSwitch" in s


def test_jwt_endpoints_exist(client: APIClient) -> None:
    # Just confirm the routes are registered; real auth flow lives in Phase 2.
    res = client.post("/api/auth/token/", {})
    # 400 = missing creds (route exists). 404 would mean URL is wrong.
    assert res.status_code == 400
