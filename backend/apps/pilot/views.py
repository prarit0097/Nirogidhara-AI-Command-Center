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
from .models import (
    PilotDecision,
    PilotDryRun,
    PilotPlan,
    PilotPlanReview,
    PilotTask,
    PilotTeamRole,
)
from .permissions import AuthenticatedReadAdminWrite
from .serializers import (
    serialize_decision,
    serialize_dry_run,
    serialize_pilot_event,
    serialize_pilot_plan,
    serialize_pilot_plan_review,
    serialize_pilot_task,
    serialize_pilot_task_event,
)

_VALID_SCENARIOS = {c for c, _ in PilotDryRun.ScenarioType.choices}
_VALID_DECISIONS = {c for c, _ in PilotDecision.Decision.choices}
_VALID_PILOT_TYPES = {c for c, _ in PilotPlan.PilotType.choices}
_VALID_PLAN_DECISIONS = {c for c, _ in PilotPlanReview.Decision.choices}
_VALID_TEAM_ROLES = {c for c, _ in PilotTeamRole.choices}
_VALID_TASK_STATUSES = {c for c, _ in PilotTask.Status.choices}


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


# ===========================================================================
# Phase 16G — Internal Pilot Control Center
# ===========================================================================


def _ref_int(app_label: str, model_name: str, value):
    if value in (None, ""):
        return None
    try:
        from django.apps import apps

        pk = int(value)
        model = apps.get_model(app_label, model_name)
        return pk if model.objects.filter(pk=pk).exists() else None
    except Exception:  # noqa: BLE001
        return None


def _ref_str(app_label: str, model_name: str, value):
    if not value:
        return None
    try:
        from django.apps import apps

        model = apps.get_model(app_label, model_name)
        return value if model.objects.filter(pk=value).exists() else None
    except Exception:  # noqa: BLE001
        return None


class PilotPlansView(APIView):
    """``GET`` list pilot plans / ``POST`` create a pilot plan (admin)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        qs = PilotPlan.objects.all().order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        pilot_type = request.query_params.get("type")
        if pilot_type:
            qs = qs.filter(pilot_type=pilot_type)
        limit = _parse_int(request.query_params.get("limit"), 50, lo=1, hi=200)
        items = [serialize_pilot_plan(p) for p in qs[:limit]]
        return Response({"items": items, "total": qs.count()})

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get("name", "") or "").strip()
        if not name:
            return Response({"detail": "name_required", "field": "name"}, status=400)
        pilot_type = str(data.get("pilotType", "") or PilotPlan.PilotType.FULL_LIFECYCLE)
        if pilot_type not in _VALID_PILOT_TYPES:
            return Response(
                {
                    "detail": "invalid_pilot_type",
                    "field": "pilotType",
                    "allowed": sorted(_VALID_PILOT_TYPES),
                },
                status=400,
            )

        plan = services.create_pilot_plan(
            name=name,
            pilot_type=pilot_type,
            created_by=request.user,
            owner_team=str(data.get("ownerTeam", "") or ""),
            problem_category=str(data.get("problemCategory", "") or ""),
            product_category=str(data.get("productCategory", "") or ""),
            objective=str(data.get("objective", "") or ""),
            risk_note=str(data.get("riskNote", "") or ""),
            allowed_list_note=str(data.get("allowedListNote", "") or ""),
            max_contacts=data.get("maxContacts") or 0,
            safety_acknowledged=bool(data.get("safetyAcknowledged", False)),
            linked_import_campaign_id=_ref_int(
                "data_imports", "ImportedCallingCampaign",
                data.get("linkedImportCampaignId"),
            ),
            linked_dataset_id=_ref_int(
                "data_imports", "ImportedDataset", data.get("linkedDatasetId"),
            ),
            linked_order_id=_ref_str("orders", "Order", data.get("linkedOrderId")),
            linked_dry_run_id=_ref_int("pilot", "PilotDryRun", data.get("linkedDryRunId")),
        )

        write_event(
            kind="pilot.plan.created",
            text=f"Pilot plan #{plan.pk} '{plan.name}' ({plan.pilot_type}) created",
            payload={
                "pilot_plan_id": plan.pk,
                "pilot_type": plan.pilot_type,
                "status": plan.status,
                "provider_actions_allowed": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_pilot_plan(plan, detail=True), status=201)


class PilotPlanDetailView(APIView):
    """``GET`` detail (+events/reviews/metrics/gate) / ``PATCH`` update (admin)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        out = serialize_pilot_plan(plan, detail=True)
        out["gateStatus"] = services.get_pilot_gate_status(plan)
        out["metrics"] = services.get_pilot_metrics(plan)
        return Response(out)

    def patch(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        fields: dict[str, Any] = {}
        mapping = {
            "name": "name", "pilotType": "pilot_type", "ownerTeam": "owner_team",
            "problemCategory": "problem_category", "productCategory": "product_category",
            "objective": "objective", "riskNote": "risk_note",
            "allowedListNote": "allowed_list_note", "maxContacts": "max_contacts",
            "safetyAcknowledged": "safety_acknowledged",
        }
        for in_key, field in mapping.items():
            if in_key in data:
                fields[field] = data[in_key]
        if "pilotType" in data and data["pilotType"] not in _VALID_PILOT_TYPES:
            return Response({"detail": "invalid_pilot_type", "field": "pilotType"}, status=400)
        if "linkedImportCampaignId" in data:
            fields["linked_import_campaign_id"] = _ref_int(
                "data_imports", "ImportedCallingCampaign", data.get("linkedImportCampaignId")
            )
        if "linkedDatasetId" in data:
            fields["linked_dataset_id"] = _ref_int(
                "data_imports", "ImportedDataset", data.get("linkedDatasetId")
            )
        if "linkedOrderId" in data:
            fields["linked_order_id"] = _ref_str("orders", "Order", data.get("linkedOrderId"))
        if "linkedDryRunId" in data:
            fields["linked_dry_run_id"] = _ref_int("pilot", "PilotDryRun", data.get("linkedDryRunId"))

        services.update_pilot_plan(plan, updated_by=request.user, **fields)
        plan.refresh_from_db()
        return Response(serialize_pilot_plan(plan, detail=True))


class PilotPlanTransitionView(APIView):
    """``POST`` an internal status transition (admin). No provider call."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        action = str(data.get("action", "") or "")
        if action not in services.PILOT_ACTIONS:
            return Response(
                {
                    "detail": "invalid_action",
                    "field": "action",
                    "allowed": sorted(services.PILOT_ACTIONS),
                },
                status=400,
            )
        try:
            services.transition_pilot_plan(
                plan, action, actor=request.user, note=str(data.get("note", "") or "")
            )
        except services.PilotPlanStateError as exc:
            return Response(
                {"detail": "invalid_transition", "reason": str(exc)}, status=409
            )

        write_event(
            kind="pilot.plan.transitioned",
            text=f"Pilot plan #{plan.pk} → {plan.status} ({action})",
            payload={
                "pilot_plan_id": plan.pk,
                "action": action,
                "status": plan.status,
                "provider_actions_allowed": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        plan.refresh_from_db()
        out = serialize_pilot_plan(plan, detail=True)
        out["gateStatus"] = services.get_pilot_gate_status(plan)
        return Response(out)


class PilotPlanReviewView(APIView):
    """``POST`` record an internal Director review (admin). Record-only."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        decision = str(data.get("decision", "") or PilotPlanReview.Decision.REVIEWED)
        if decision not in _VALID_PLAN_DECISIONS:
            return Response(
                {
                    "detail": "invalid_decision",
                    "field": "decision",
                    "allowed": sorted(_VALID_PLAN_DECISIONS),
                },
                status=400,
            )
        review = services.record_pilot_review(
            plan,
            decision=decision,
            note=str(data.get("note", "") or ""),
            decided_by=request.user,
        )
        write_event(
            kind="pilot.plan.reviewed",
            text=f"Pilot plan #{plan.pk} reviewed: {decision}",
            payload={
                "pilot_plan_id": plan.pk,
                "decision": decision,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(serialize_pilot_plan_review(review), status=201)


class PilotPlanEventsView(APIView):
    """``GET`` the internal event log for a pilot plan."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=200)
        events = plan.events.all().order_by("-created_at")[:limit]
        return Response({"items": [serialize_pilot_event(e) for e in events]})


class PilotControlSummaryView(APIView):
    """``GET /api/v1/pilot/control/summary/`` — control-center summary."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        return Response(services.get_pilot_summary())


# ===========================================================================
# Phase 16H — Internal Pilot Execution Workbench + Role-Based Task Queues
# ===========================================================================


def _user_ref(user_id):
    """Resolve an optional assignee user id; else None."""
    if not user_id:
        return None
    try:
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=int(user_id)).first()
    except Exception:  # noqa: BLE001
        return None


class PilotPlanTasksView(APIView):
    """``GET`` list / ``POST`` generate role-based task queues for a plan."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        qs = plan.tasks.all()
        team = request.query_params.get("team")
        if team:
            qs = qs.filter(team_role=team)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response({"items": [serialize_pilot_task(t) for t in qs]})

    def post(self, request, pk: int):
        """Generate the default role-based task queues for this plan."""
        plan = PilotPlan.objects.filter(pk=pk).first()
        if plan is None:
            return Response({"detail": "not_found"}, status=404)
        if plan.status not in {
            PilotPlan.Status.APPROVED_INTERNAL, PilotPlan.Status.RUNNING_INTERNAL,
        }:
            return Response(
                {
                    "detail": "plan_not_ready_for_execution",
                    "reason": "Plan must be approved_internal or running_internal.",
                    "status": plan.status,
                },
                status=409,
            )
        data = request.data if isinstance(request.data, dict) else {}
        teams = data.get("teams")
        if teams is not None and not isinstance(teams, list):
            teams = None
        created = services.generate_tasks_for_plan(
            plan, teams=teams, created_by=request.user
        )
        write_event(
            kind="pilot.tasks.generated",
            text=f"Pilot plan #{plan.pk}: generated {len(created)} internal task(s)",
            payload={
                "pilot_plan_id": plan.pk,
                "created_count": len(created),
                "provider_actions_allowed": False,
                "by": getattr(request.user, "username", ""),
            },
            user=request.user,
        )
        return Response(
            {"items": [serialize_pilot_task(t) for t in created], "created": len(created)},
            status=201,
        )


class PilotTasksView(APIView):
    """``GET`` global task list / ``POST`` create a single task (admin)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        qs = PilotTask.objects.all()
        plan_id = request.query_params.get("plan")
        if plan_id:
            qs = qs.filter(pilot_plan_id=plan_id)
        team = request.query_params.get("team")
        if team:
            qs = qs.filter(team_role=team)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=200)
        return Response({
            "items": [serialize_pilot_task(t) for t in qs[:limit]],
            "total": qs.count(),
        })

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        plan = PilotPlan.objects.filter(pk=data.get("pilotPlanId")).first()
        if plan is None:
            return Response({"detail": "plan_not_found", "field": "pilotPlanId"}, status=400)
        team_role = str(data.get("teamRole", "") or "")
        if team_role not in _VALID_TEAM_ROLES:
            return Response(
                {"detail": "invalid_team_role", "field": "teamRole", "allowed": sorted(_VALID_TEAM_ROLES)},
                status=400,
            )
        title = str(data.get("title", "") or "").strip()
        if not title:
            return Response({"detail": "title_required", "field": "title"}, status=400)
        task = services.create_pilot_task(
            plan, team_role=team_role, title=title, created_by=request.user,
            description=str(data.get("description", "") or ""),
            priority=data.get("priority"),
            sequence=data.get("sequence") or 0,
            assigned_team_label=str(data.get("assignedTeamLabel", "") or ""),
        )
        write_event(
            kind="pilot.task.created",
            text=f"Pilot task #{task.pk} ({task.team_role}) created",
            payload={"pilot_plan_id": plan.pk, "task_id": task.pk, "team_role": task.team_role,
                     "provider_actions_allowed": False, "by": getattr(request.user, "username", "")},
            user=request.user,
        )
        return Response(serialize_pilot_task(task, detail=True), status=201)


class PilotTaskDetailView(APIView):
    """``GET`` detail (+events) / ``PATCH`` update a task (admin)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        task = PilotTask.objects.filter(pk=pk).first()
        if task is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(serialize_pilot_task(task, detail=True))

    def patch(self, request, pk: int):
        task = PilotTask.objects.filter(pk=pk).first()
        if task is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        if "teamRole" in data and data["teamRole"] not in _VALID_TEAM_ROLES:
            return Response({"detail": "invalid_team_role", "field": "teamRole"}, status=400)
        fields: dict[str, Any] = {}
        mapping = {
            "title": "title", "description": "description", "priority": "priority",
            "sequence": "sequence", "teamRole": "team_role",
            "assignedTeamLabel": "assigned_team_label",
        }
        for in_key, field in mapping.items():
            if in_key in data:
                fields[field] = data[in_key]
        if "checklist" in data:
            services.update_task_checklist(task, checklist=data["checklist"], actor=request.user)
        if fields:
            services.update_pilot_task(task, updated_by=request.user, **fields)
        task.refresh_from_db()
        return Response(serialize_pilot_task(task, detail=True))


class PilotTaskTransitionView(APIView):
    """``POST`` an internal task status transition (admin). No provider call."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        task = PilotTask.objects.filter(pk=pk).first()
        if task is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        action = str(data.get("action", "") or "")
        if action not in services.PILOT_TASK_ACTIONS:
            return Response(
                {"detail": "invalid_action", "field": "action", "allowed": sorted(services.PILOT_TASK_ACTIONS)},
                status=400,
            )
        try:
            services.transition_pilot_task(
                task, action, actor=request.user, note=str(data.get("note", "") or "")
            )
        except services.PilotTaskStateError as exc:
            reason = str(exc)
            status_code = 400 if reason == "block_requires_reason" else 409
            return Response({"detail": "invalid_transition", "reason": reason}, status=status_code)
        write_event(
            kind="pilot.task.transitioned",
            text=f"Pilot task #{task.pk} → {task.status} ({action})",
            payload={"task_id": task.pk, "action": action, "status": task.status,
                     "provider_actions_allowed": False, "by": getattr(request.user, "username", "")},
            user=request.user,
        )
        task.refresh_from_db()
        return Response(serialize_pilot_task(task, detail=True))


class PilotTaskAssignView(APIView):
    """``POST`` assign a task to a user and/or team label (admin)."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def post(self, request, pk: int):
        task = PilotTask.objects.filter(pk=pk).first()
        if task is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        assignee = _user_ref(data.get("assigneeId"))
        team_label = str(data.get("teamLabel", "") or "")
        services.assign_pilot_task(task, assignee=assignee, team_label=team_label, actor=request.user)
        write_event(
            kind="pilot.task.assigned",
            text=f"Pilot task #{task.pk} assigned",
            payload={"task_id": task.pk, "provider_actions_allowed": False,
                     "by": getattr(request.user, "username", "")},
            user=request.user,
        )
        task.refresh_from_db()
        return Response(serialize_pilot_task(task, detail=True))


class PilotTaskEventsView(APIView):
    """``GET`` the internal event log for a pilot task."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request, pk: int):
        task = PilotTask.objects.filter(pk=pk).first()
        if task is None:
            return Response({"detail": "not_found"}, status=404)
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=200)
        events = task.events.all().order_by("-created_at")[:limit]
        return Response({"items": [serialize_pilot_task_event(e) for e in events]})


class PilotExecutionSummaryView(APIView):
    """``GET /api/v1/pilot/execution/summary/`` — execution progress dashboard."""

    permission_classes = [AuthenticatedReadAdminWrite]

    def get(self, request):
        plan = None
        plan_id = request.query_params.get("plan")
        if plan_id:
            plan = PilotPlan.objects.filter(pk=plan_id).first()
            if plan is None:
                return Response({"detail": "plan_not_found"}, status=404)
        summary = services.get_execution_summary(plan)
        summary["teamPerformance"] = services.get_team_performance()
        return Response(summary)
