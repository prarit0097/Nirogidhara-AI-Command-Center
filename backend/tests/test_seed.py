"""Verify the seed command produces the same row counts as the frontend mockData."""
from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.agents.models import Agent
from apps.ai_governance.models import CaioAudit, CeoBriefing
from apps.analytics.models import KPITrend
from apps.audit.models import AuditEvent
from apps.calls.models import ActiveCall, Call
from apps.compliance.models import Claim
from apps.crm.models import Customer, Lead
from apps.dashboards.models import DashboardMetric
from apps.learning_engine.models import LearningRecording
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.rewards.models import RewardPenalty
from apps.shipments.models import Shipment


@pytest.fixture
def fresh_seed(db):
    call_command("seed_demo_data", "--reset")


def test_row_counts_match_frontend_fixtures(fresh_seed) -> None:
    assert Lead.objects.count() == 42
    assert Customer.objects.count() == 24
    assert Order.objects.count() == 60
    assert Call.objects.count() == 18
    assert ActiveCall.objects.count() == 1
    assert Payment.objects.count() == 30
    # Shipments come from orders with awb (i > 20 in JS, so 60-21=39).
    assert Shipment.objects.count() == 39
    assert Agent.objects.count() == 19
    assert CeoBriefing.objects.count() == 1
    assert CaioAudit.objects.count() == 5
    assert Claim.objects.count() == 4
    assert RewardPenalty.objects.count() > 0
    assert LearningRecording.objects.count() == 5
    assert DashboardMetric.objects.count() == 12
    # KPI trends: 7 + 7 + 7 + 8 = 29
    assert KPITrend.objects.count() == 29
    # Curated activity feed entries.
    assert AuditEvent.objects.filter(kind="seed.activity").count() == 8


def test_seed_is_idempotent(fresh_seed) -> None:
    """Running --reset twice yields the same counts."""
    call_command("seed_demo_data", "--reset")
    assert Lead.objects.count() == 42
    assert Order.objects.count() == 60
