"""Phase 6A — SaaS Foundation read-only DRF endpoints.

Three endpoints under ``/api/v1/saas/``:

- ``GET /api/v1/saas/current-organization/`` — the user's active org.
- ``GET /api/v1/saas/my-organizations/`` — every active org the user
  belongs to (or the default org as a fallback).
- ``GET /api/v1/saas/feature-flags/`` — non-sensitive feature flag map
  for the user's current org.

All endpoints require an authenticated user. None of them mutate state.
``OrganizationSetting`` rows flagged ``is_sensitive=True`` never appear
in any response.
"""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .admin_readiness import get_saas_admin_overview
from .coverage import compute_default_organization_coverage
from .ai_runtime_preview import preview_all_ai_provider_routes
from .integration_runtime import get_all_provider_runtime_previews
from .live_gate import (
    _serialize_request as serialize_live_execution_request,
    approve_live_execution_request,
    create_live_execution_request,
    evaluate_live_execution_gate,
    get_or_create_default_runtime_kill_switch,
    reject_live_execution_request,
    summarize_live_gate_readiness,
)
from .live_gate_policy import list_live_gate_policies
from .live_gate_simulation import (
    approve_single_internal_live_gate_simulation,
    inspect_single_internal_live_gate_simulation,
    list_live_gate_simulations,
    prepare_single_internal_live_gate_simulation,
    reject_single_internal_live_gate_simulation,
    request_single_internal_live_gate_approval,
    rollback_single_internal_live_gate_simulation,
    run_single_internal_live_gate_simulation,
    serialize_live_gate_simulation,
)
from .provider_test_plan import (
    approve_single_provider_test_plan,
    archive_single_provider_test_plan,
    inspect_single_provider_test_plan,
    prepare_single_provider_test_plan,
    reject_single_provider_test_plan,
    serialize_provider_test_plan,
    validate_single_provider_test_plan,
)
from .runtime_dry_run import (
    preview_all_runtime_operations,
    preview_runtime_routing_for_operation,
    summarize_runtime_dry_run_readiness,
)
from .integration_settings import (
    get_org_integration_readiness,
    get_org_integration_settings,
    serialize_integration_setting,
)
from .readiness import compute_org_scoped_api_readiness
from .write_readiness import compute_org_write_path_readiness
from .models import (
    Organization,
    OrganizationIntegrationSetting,
    RuntimeLiveExecutionRequest,
    RuntimeLiveGateSimulation,
    RuntimeProviderTestPlan,
)
from .selectors import (
    get_active_organization_for_user,
    get_default_organization,
    get_default_branch,
    get_organization_feature_flags,
    get_organization_membership_summary,
    get_user_organizations,
    get_user_role_in_organization,
    get_non_sensitive_settings,
)


class AdminSaasPermission(BasePermission):
    """Staff/superuser/global director/admin only."""

    def has_permission(self, request, view):
        user = request.user
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_staff", False) or getattr(
            user, "is_superuser", False
        ):
            return True
        role = getattr(user, "role", "")
        return role in {"director", "admin"}


def _serialize_organization(
    org: Organization | None,
    *,
    user=None,
) -> dict[str, Any] | None:
    """Common, secret-free serialization shape."""
    if org is None:
        return None
    branch = None
    default_branch = (
        org.branches.filter(code="main").first()
        if hasattr(org, "branches")
        else None
    )
    if default_branch is not None:
        branch = {
            "id": default_branch.id,
            "code": default_branch.code,
            "name": default_branch.name,
            "status": default_branch.status,
        }
    role = ""
    if user is not None:
        role = get_user_role_in_organization(user, org)
    return {
        "id": org.id,
        "code": org.code,
        "name": org.name,
        "legalName": org.legal_name,
        "status": org.status,
        "timezone": org.timezone,
        "country": org.country,
        "defaultBranch": branch,
        "userOrgRole": role,
        "createdAt": (
            org.created_at.isoformat() if org.created_at else None
        ),
    }


class CurrentOrganizationView(APIView):
    """``GET /api/v1/saas/current-organization/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = get_active_organization_for_user(user)
        payload: dict[str, Any] = {
            "organization": _serialize_organization(org, user=user),
            "membershipSummary": (
                get_organization_membership_summary(org)
                if org is not None
                else {"total": 0, "active": 0, "byRole": {}}
            ),
            "settings": get_non_sensitive_settings(org),
            "featureFlags": get_organization_feature_flags(org),
        }
        return Response(payload)


class MyOrganizationsView(APIView):
    """``GET /api/v1/saas/my-organizations/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        orgs = get_user_organizations(user)
        return Response(
            {
                "count": len(orgs),
                "organizations": [
                    _serialize_organization(org, user=user) for org in orgs
                ],
            }
        )


class FeatureFlagsView(APIView):
    """``GET /api/v1/saas/feature-flags/``."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = get_active_organization_for_user(user)
        return Response(
            {
                "organization": _serialize_organization(org, user=user),
                "featureFlags": get_organization_feature_flags(org),
            }
        )


class DataCoverageView(APIView):
    """``GET /api/v1/saas/data-coverage/`` — Phase 6B coverage report.

    Read-only. Mirrors the ``inspect_default_organization_coverage``
    management command's JSON output. Auth required; the response
    carries no secrets and no full phone numbers (it's row counts only).
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_default_organization_coverage())


class OrgScopeReadinessView(APIView):
    """``GET /api/v1/saas/org-scope-readiness/`` — Phase 6C diagnostic.

    Read-only. Mirrors the ``inspect_org_scoped_api_readiness``
    management command. Auth required; carries no secrets / no PII.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_org_scoped_api_readiness())


class WritePathReadinessView(APIView):
    """``GET /api/v1/saas/write-path-readiness/`` — Phase 6D diagnostic.

    Read-only. Mirrors the ``inspect_org_write_path_readiness``
    management command. Auth required; carries no secrets / no PII.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(compute_org_write_path_readiness())


def _get_admin_org(request) -> Organization | None:
    org_id = request.query_params.get("organizationId")
    if org_id:
        return Organization.objects.filter(id=org_id).first()
    return get_default_organization()


def _integration_payload(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "providerType": "provider_type",
        "status": "status",
        "displayName": "display_name",
        "config": "config",
        "secretRefs": "secret_refs",
        "isActive": "is_active",
        "lastValidatedAt": "last_validated_at",
        "validationStatus": "validation_status",
        "validationMessage": "validation_message",
        "metadata": "metadata",
    }
    payload: dict[str, Any] = {}
    for source, target in allowed.items():
        if source in data:
            payload[target] = data[source]
    return payload


class SaasAdminOverviewView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(get_saas_admin_overview())


class SaasAdminOrganizationsView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        orgs = Organization.objects.order_by("name")
        return Response(
            {
                "count": orgs.count(),
                "organizations": [
                    _serialize_organization(org, user=request.user)
                    | {
                        "membershipSummary": (
                            get_organization_membership_summary(org)
                        ),
                        "featureFlags": get_organization_feature_flags(org),
                        "integrationSettingsCount": (
                            org.integration_settings.count()
                        ),
                    }
                    for org in orgs
                ],
            }
        )


class SaasAdminOrganizationDetailView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request, organization_id):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            return Response(
                {"detail": "Organization not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "organization": _serialize_organization(org, user=request.user),
                "membershipSummary": get_organization_membership_summary(org),
                "featureFlags": get_organization_feature_flags(org),
                "integrationSettings": get_org_integration_settings(org),
                "integrationReadiness": get_org_integration_readiness(org),
            }
        )


class SaasIntegrationSettingsView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(
            {
                "organization": _serialize_organization(
                    org,
                    user=request.user,
                ),
                "settings": get_org_integration_settings(org),
                "runtimeUsesPerOrgSettings": False,
            }
        )

    def post(self, request):
        org_id = request.data.get("organizationId")
        org = (
            Organization.objects.filter(id=org_id).first()
            if org_id
            else get_default_organization()
        )
        if org is None:
            return Response(
                {"detail": "Organization not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = _integration_payload(dict(request.data))
        payload["organization"] = org
        try:
            setting = OrganizationIntegrationSetting.objects.create(**payload)
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            serialize_integration_setting(setting),
            status=status.HTTP_201_CREATED,
        )


class SaasIntegrationSettingDetailView(APIView):
    permission_classes = [AdminSaasPermission]

    def patch(self, request, setting_id):
        setting = OrganizationIntegrationSetting.objects.filter(
            id=setting_id
        ).first()
        if setting is None:
            return Response(
                {"detail": "Integration setting not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = _integration_payload(dict(request.data))
        payload.pop("provider_type", None)
        for field, value in payload.items():
            setattr(setting, field, value)
        try:
            setting.save()
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_integration_setting(setting))


class SaasIntegrationReadinessView(APIView):
    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(get_org_integration_readiness(org))


class RuntimeDryRunView(APIView):
    """``GET /api/v1/saas/runtime-dry-run/[?operation=<type>]`` — Phase 6G.

    Read-only. Returns the controlled runtime dry-run preview for the
    admin's organization (or the default org). Strict invariants:
    ``runtimeSource="env_config"``, ``perOrgRuntimeEnabled=False``,
    ``dryRun=True``, ``liveExecutionAllowed=False``,
    ``externalCallWillBeMade=False``.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        operation = (request.query_params.get("operation") or "").strip()
        include_ai = (
            request.query_params.get("include_ai") or "true"
        ).lower() not in {"false", "0", "no"}
        if operation and operation != "all":
            return Response(
                preview_runtime_routing_for_operation(operation, org=org)
            )
        return Response(
            preview_all_runtime_operations(org, include_ai=include_ai)
        )


class AiProviderRoutingView(APIView):
    """``GET /api/v1/saas/ai-provider-routing/`` — Phase 6G AI preview."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(preview_all_ai_provider_routes())


class ControlledRuntimeReadinessView(APIView):
    """``GET /api/v1/saas/controlled-runtime-readiness/`` — Phase 6G summary."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(summarize_runtime_dry_run_readiness(org))


class RuntimeRoutingReadinessView(APIView):
    """``GET /api/v1/saas/runtime-routing-readiness/`` — Phase 6F preview.

    Read-only. Returns the per-provider runtime preview for the current
    admin's organization (or the default org). Strict invariants:

    - ``runtimeUsesPerOrgSettings=False`` always in this phase.
    - No raw secrets returned. ENV: refs return presence (true/false)
      and a masked label only.
    - No external provider calls.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(get_all_provider_runtime_previews(org))


class RuntimeLiveGateView(APIView):
    """``GET /api/v1/saas/runtime-live-gate/``.

    Authenticated read-only overview of the Phase 6H live audit gate.
    No endpoint in this view executes a provider call.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(summarize_live_gate_readiness(org))


class RuntimeLiveGateRequestsView(APIView):
    """List or create audit-only live execution requests."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [AdminSaasPermission()]

    def get(self, request):
        rows = RuntimeLiveExecutionRequest.objects.order_by("-created_at")[
            :50
        ]
        return Response(
            {
                "count": len(rows),
                "requests": [
                    serialize_live_execution_request(row) for row in rows
                ],
                "dryRun": True,
                "liveExecutionAllowed": False,
                "externalCallWillBeMade": False,
            }
        )

    def post(self, request):
        operation = (
            request.data.get("operationType")
            or request.data.get("operation")
            or ""
        ).strip()
        if not operation:
            return Response(
                {"detail": "operationType is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row = create_live_execution_request(
            operation,
            request=request,
            user=request.user,
            payload=request.data.get("payload") or {},
            live_requested=bool(
                request.data.get("liveRequested")
                if "liveRequested" in request.data
                else True
            ),
        )
        return Response(
            serialize_live_execution_request(row),
            status=status.HTTP_201_CREATED,
        )


class RuntimeLiveGatePoliciesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(
            {
                "policies": [
                    policy.to_dict() for policy in list_live_gate_policies()
                ],
                "dryRun": True,
                "liveExecutionAllowed": False,
                "externalCallWillBeMade": False,
            }
        )


class RuntimeLiveGateKillSwitchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, _request):
        switch = get_or_create_default_runtime_kill_switch()
        return Response(
            {
                "scope": switch.scope,
                "enabled": switch.enabled,
                "reason": switch.reason,
                "dryRun": True,
                "liveExecutionAllowed": False,
                "externalCallWillBeMade": False,
                "killSwitchActive": switch.enabled,
                "approvalStatus": "",
                "gateDecision": (
                    "blocked_by_kill_switch"
                    if switch.enabled
                    else "kill_switch_disabled"
                ),
                "blockers": ["global_runtime_kill_switch_enabled"]
                if switch.enabled
                else [],
                "warnings": [
                    "Phase 6H does not execute external calls even when disabled."
                ],
                "nextAction": "keep_live_execution_blocked",
            }
        )


class RuntimeLiveGatePreviewView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request):
        operation = (
            request.data.get("operationType")
            or request.data.get("operation")
            or ""
        ).strip()
        if not operation:
            return Response(
                {"detail": "operationType is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        decision = evaluate_live_execution_gate(
            operation,
            request=request,
            user=request.user,
            payload=request.data.get("payload") or {},
            live_requested=bool(request.data.get("liveRequested", False)),
            audit_preview=True,
        )
        return Response(decision)


class RuntimeLiveGateApproveView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, request_id):
        row = RuntimeLiveExecutionRequest.objects.filter(id=request_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live execution request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = approve_live_execution_request(
            request_id,
            request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_execution_request(row))


class RuntimeLiveGateRejectView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, request_id):
        row = RuntimeLiveExecutionRequest.objects.filter(id=request_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live execution request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = reject_live_execution_request(
            request_id,
            request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_execution_request(row))


class RuntimeLiveGateSimulationsView(APIView):
    """List Phase 6I live-gate simulations or prepare a new one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_admin_org(request)
        report = list_live_gate_simulations()
        report["summary"] = inspect_single_internal_live_gate_simulation(
            organization=org
        )
        return Response(report)


class RuntimeLiveGateSimulationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, _request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(serialize_live_gate_simulation(row))


class RuntimeLiveGateSimulationPrepareView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request):
        operation = (
            request.data.get("operationType")
            or request.data.get("operation")
            or "razorpay.create_order"
        ).strip()
        try:
            row = prepare_single_internal_live_gate_simulation(
                operation_type=operation,
                organization=_get_admin_org(request),
                user=request.user,
                payload=request.data.get("payload") or None,
                reason=request.data.get("reason") or "",
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            serialize_live_gate_simulation(row),
            status=status.HTTP_201_CREATED,
        )


class RuntimeLiveGateSimulationRequestApprovalView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = request_single_internal_live_gate_approval(
            simulation_id,
            user=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_gate_simulation(row))


class RuntimeLiveGateSimulationApproveView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = approve_single_internal_live_gate_simulation(
            simulation_id,
            approver=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_gate_simulation(row))


class RuntimeLiveGateSimulationRejectView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = reject_single_internal_live_gate_simulation(
            simulation_id,
            rejector=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_gate_simulation(row))


class RuntimeLiveGateSimulationRunView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = run_single_internal_live_gate_simulation(
            simulation_id,
            user=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_gate_simulation(row))


class RuntimeLiveGateSimulationRollbackView(APIView):
    permission_classes = [AdminSaasPermission]

    def post(self, request, simulation_id):
        row = RuntimeLiveGateSimulation.objects.filter(id=simulation_id).first()
        if row is None:
            return Response(
                {"detail": "Runtime live-gate simulation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = rollback_single_internal_live_gate_simulation(
            simulation_id,
            user=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_live_gate_simulation(row))


class ProviderTestPlansListView(APIView):
    """``GET /api/v1/saas/provider-test-plans/`` — Phase 6J.

    Read-only. Returns the inspector report for the current org.
    POST/PATCH/DELETE return 405. No raw secrets ever returned.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(inspect_single_provider_test_plan(organization=org))


class ProviderTestPlanDetailView(APIView):
    """``GET /api/v1/saas/provider-test-plans/<plan_id>/`` — Phase 6J."""

    permission_classes = [IsAuthenticated]

    def get(self, _request, plan_id):
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(serialize_provider_test_plan(plan))


class ProviderTestPlanPrepareView(APIView):
    """``POST /api/v1/saas/provider-test-plans/prepare/`` — Phase 6J.

    Admin-only. Creates a new ``RuntimeProviderTestPlan``. Phase 6J
    NEVER calls a provider; this endpoint records intent only.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request):
        operation = (
            request.data.get("operationType")
            or request.data.get("operation_type")
            or "razorpay.create_order"
        )
        org_id = request.data.get("organizationId")
        org = (
            Organization.objects.filter(id=org_id).first()
            if org_id
            else _get_admin_org(request)
        )
        plan = prepare_single_provider_test_plan(
            operation_type=operation,
            organization=org,
            user=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(
            serialize_provider_test_plan(plan),
            status=status.HTTP_201_CREATED,
        )


class ProviderTestPlanValidateView(APIView):
    """``POST /api/v1/saas/provider-test-plans/<plan_id>/validate/``."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, plan_id):
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        plan = validate_single_provider_test_plan(plan_id, user=request.user)
        return Response(serialize_provider_test_plan(plan))


class ProviderTestPlanApproveView(APIView):
    """``POST /api/v1/saas/provider-test-plans/<plan_id>/approve/``.

    Approval ONLY enables the future Phase 6K execution gate. It NEVER
    unlocks a provider call in Phase 6J.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request, plan_id):
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        plan = approve_single_provider_test_plan(
            plan_id,
            approver=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_provider_test_plan(plan))


class ProviderTestPlanRejectView(APIView):
    """``POST /api/v1/saas/provider-test-plans/<plan_id>/reject/``."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, plan_id):
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        plan = reject_single_provider_test_plan(
            plan_id,
            rejector=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_provider_test_plan(plan))


class ProviderTestPlanArchiveView(APIView):
    """``POST /api/v1/saas/provider-test-plans/<plan_id>/archive/``."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, plan_id):
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        plan = archive_single_provider_test_plan(
            plan_id,
            user=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_provider_test_plan(plan))


__all__ = (
    "CurrentOrganizationView",
    "MyOrganizationsView",
    "FeatureFlagsView",
    "DataCoverageView",
    "OrgScopeReadinessView",
    "WritePathReadinessView",
    "SaasAdminOverviewView",
    "SaasAdminOrganizationsView",
    "SaasAdminOrganizationDetailView",
    "SaasIntegrationSettingsView",
    "SaasIntegrationSettingDetailView",
    "SaasIntegrationReadinessView",
    "RuntimeRoutingReadinessView",
    "RuntimeDryRunView",
    "AiProviderRoutingView",
    "ControlledRuntimeReadinessView",
    "RuntimeLiveGateView",
    "RuntimeLiveGateRequestsView",
    "RuntimeLiveGatePoliciesView",
    "RuntimeLiveGateKillSwitchView",
    "RuntimeLiveGatePreviewView",
    "RuntimeLiveGateApproveView",
    "RuntimeLiveGateRejectView",
    "RuntimeLiveGateSimulationsView",
    "RuntimeLiveGateSimulationDetailView",
    "RuntimeLiveGateSimulationPrepareView",
    "RuntimeLiveGateSimulationRequestApprovalView",
    "RuntimeLiveGateSimulationApproveView",
    "RuntimeLiveGateSimulationRejectView",
    "RuntimeLiveGateSimulationRunView",
    "RuntimeLiveGateSimulationRollbackView",
    "ProviderTestPlansListView",
    "ProviderTestPlanDetailView",
    "ProviderTestPlanPrepareView",
    "ProviderTestPlanValidateView",
    "ProviderTestPlanApproveView",
    "ProviderTestPlanRejectView",
    "ProviderTestPlanArchiveView",
)
