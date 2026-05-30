"""Phase 16F — Controlled Internal Pilot Readiness + End-to-End Dry Run API.

All endpoints require authentication; mutations require director/admin. NOTHING
here calls a provider: a dry-run only reads existing data + configuration and
writes its own `PilotDryRun` / `PilotDecision` rows (+ a non-PII audit). Linked
Lead / Customer / Order / imported-campaign rows are referenced, never mutated.
"""
from __future__ import annotations

from typing import Any

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.signals import write_event

from . import services
from .models import PilotDecision, PilotDryRun
from .permissions import AuthenticatedReadAdminWrite
from .serializers import serialize_decision, serialize_dry_run

_VALID_SCENARIOS = {c for c, _ in PilotDryRun.ScenarioType.choices}
_VALID_DECISIONS = {c for c, _ in PilotDecision.Decision.choices}


def _parse_int(raw, default: int, *, lo: int = 1, hi: int = 200) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class PilotReadinessView(APIView):
    """``GET /api/v1/pilot/readiness/`` — read-only composite readiness."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        return Response(services.build_readiness())


class PilotDryRunsView(APIView):
    """``GET`` list dry-runs / ``POST`` create + evaluate a dry-run."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        qs = PilotDryRun.objects.all().order_by("-created_at")
        scenario = request.query_params.get("scenario")
        if scenario:
            qs = qs.filter(scenario_type=scenario)
        limit = _parse_int(request.query_params.get("limit"), 50, lo=1, hi=200)
        items = [serialize_dry_run(d) for d in qs[:limit]]
        return Response({"items": items, "total": qs.count()})

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get("name", "") or "").strip()
        if not name:
            return Response(
                {"detail": "name_required", "field": "name"}, status=400
            )
        scenario = str(
            data.get("scenarioType", "")
            or PilotDryRun.ScenarioType.FULL_LIFECYCLE
        )
        if scenario not in _VALID_SCENARIOS:
            return Response(
                {
                    "detail": "invalid_scenario",
                    "field": "scenarioType",
                    "allowed": sorted(_VALID_SCENARIOS),
                },
                status=400,
            )

        dry_run = PilotDryRun.objects.create(
            name=name[:160],
            scenario_type=scenario,
            status=PilotDryRun.Status.DRAFT,
            created_by=request.user,
            selected_lead_id=self._ref("crm", "Lead", data.get("selectedLeadId")),
            selected_customer_id=self._ref("crm", "Customer", data.get("selectedCustomerId")),
            selected_order_id=self._ref("orders", "Order", data.get("selectedOrderId")),
            selected_import_campaign_id=self._ref_int(
                "data_imports", "ImportedCallingCampaign", data.get("selectedImportCampaignId")
            ),
            selected_queue_item_id=self._ref_int(
                "data_imports", "ImportedCallQueueItem", data.get("selectedQueueItemId")
            ),
        )

        result = services.evaluate_dry_run(dry_run)

        write_event(
            kind="pilot.dry_run.created",
            text=(
                f"Pilot dry-run #{dry_run.pk} '{dry_run.name}' "
                f"({dry_run.scenario_type}) → {result['status']}"
            ),
            payload={
                "dry_run_id": dry_run.pk,
                "scenario": dry_run.scenario_type,
                "status": result["status"],
                "blocked_gate_count": result["blockedGateCount"],
                "warning_gate_count": result["warningGateCount"],
                "provider_actions_attempted": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )

        dry_run.refresh_from_db()
        return Response(serialize_dry_run(dry_run, detail=True), status=201)

    @staticmethod
    def _ref(app_label: str, model_name: str, value):
        """Validate an optional CharField-PK reference exists; else None."""
        if not value:
            return None
        try:
            from django.apps import apps

            model = apps.get_model(app_label, model_name)
            return value if model.objects.filter(pk=value).exists() else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _ref_int(app_label: str, model_name: str, value):
        """Validate an optional int-PK reference exists; else None."""
        if value in (None, ""):
            return None
        try:
            from django.apps import apps

            pk = int(value)
            model = apps.get_model(app_label, model_name)
            return pk if model.objects.filter(pk=pk).exists() else None
        except Exception:  # noqa: BLE001
            return None


class PilotDryRunDetailView(APIView):
    """``GET /api/v1/pilot/dry-runs/<id>/`` — full detail + decisions."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        dry_run = PilotDryRun.objects.filter(pk=pk).first()
        if dry_run is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(serialize_dry_run(dry_run, detail=True))


class PilotDryRunReviewView(APIView):
    """``POST /api/v1/pilot/dry-runs/<id>/review/`` — director/admin review."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        dry_run = PilotDryRun.objects.filter(pk=pk).first()
        if dry_run is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        decision = str(data.get("decision", "") or PilotDecision.Decision.REVIEWED)
        if decision not in _VALID_DECISIONS:
            return Response(
                {
                    "detail": "invalid_decision",
                    "field": "decision",
                    "allowed": sorted(_VALID_DECISIONS),
                },
                status=400,
            )
        checklist = data.get("signoffChecklist")
        if not isinstance(checklist, dict):
            checklist = {}
        # Defensive: the live-provider-gate item must never be marked approved
        # from this internal review surface.
        checklist["live_provider_gate_not_approved"] = True

        dec = PilotDecision.objects.create(
            dry_run=dry_run,
            decision=decision,
            note=str(data.get("note", "") or "")[:4000],
            signoff_checklist={k: bool(v) for k, v in checklist.items()},
            decided_by=request.user,
        )

        write_event(
            kind="pilot.dry_run.reviewed",
            text=f"Pilot dry-run #{dry_run.pk} reviewed: {decision}",
            payload={
                "dry_run_id": dry_run.pk,
                "decision": decision,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )

        return Response(serialize_decision(dec), status=201)
