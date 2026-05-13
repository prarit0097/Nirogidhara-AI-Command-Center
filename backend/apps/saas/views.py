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
from .provider_execution import (
    archive_single_provider_execution_attempt,
    inspect_single_provider_execution_attempt,
    prepare_single_provider_execution_attempt,
    rollback_single_provider_execution_attempt,
    serialize_execution_attempt,
)
from .razorpay_audit_review import (
    inspect_razorpay_webhook_readiness,
    plan_razorpay_webhook_readiness,
    review_razorpay_test_execution_audit,
)
from .razorpay_business_mutation_plan import (
    get_razorpay_business_mutation_sandbox_plan,
    inspect_razorpay_business_mutation_sandbox_readiness,
)
from apps.payments.razorpay_sandbox_status_mapping import (
    approve_phase6o_sandbox_status_review,
    archive_phase6o_sandbox_status_review,
    inspect_phase6o_sandbox_status_mapping_readiness,
    prepare_phase6o_sandbox_status_review,
    preview_phase6o_status_mapping_for_event,
    reject_phase6o_sandbox_status_review,
    summarize_phase6o_reviews,
    _serialize_review as _serialize_phase6o_review,
)
from apps.payments.razorpay_sandbox_paid_status_mutation import (
    inspect_phase6p_paid_status_mutation_readiness,
    preview_phase6p_paid_status_mutation,
    summarize_phase6p_paid_status_mutation_attempts,
    _serialize_attempt as _serialize_phase6p_attempt,
)
from apps.payments.razorpay_payment_order_workflow_gate import (
    inspect_phase6q_payment_order_workflow_gate_readiness,
    preview_phase6q_payment_order_workflow_gate,
    summarize_phase6q_payment_order_workflow_gates,
    _serialize_gate as _serialize_phase6q_gate,
)
from apps.payments.razorpay_payment_dispatch_readiness import (
    inspect_phase6r_payment_dispatch_readiness,
    preview_phase6r_payment_dispatch_readiness_gate,
    summarize_phase6r_payment_dispatch_readiness_gates,
    _serialize_readiness as _serialize_phase6r_readiness,
)
from apps.payments.razorpay_payment_dispatch_pilot_plan import (
    inspect_phase6s_payment_dispatch_pilot_plan_readiness,
    preview_phase6s_payment_dispatch_pilot_plan,
    summarize_phase6s_payment_dispatch_pilot_plans,
    _serialize_pilot_plan as _serialize_phase6s_pilot_plan,
)
from apps.payments.razorpay_phase6_final_audit_lock import (
    inspect_phase6t_final_audit_lock_readiness,
    preview_phase6t_final_audit_lock,
    summarize_phase6t_final_audit_locks,
    _serialize_audit_lock as _serialize_phase6t_audit_lock,
)
from apps.payments.razorpay_controlled_pilot_gate import (
    inspect_phase7b_controlled_pilot_gate_readiness,
    preview_phase7b_controlled_pilot_gate,
    serialize_phase7b_dry_run_record as _serialize_phase7b_dry_run_record,
    serialize_phase7b_gate as _serialize_phase7b_gate,
    serialize_phase7b_rollback_dry_run_record as _serialize_phase7b_rollback_dry_run_record,
    summarize_phase7b_controlled_pilot_gates,
)
from apps.payments.razorpay_controlled_pilot_execution import (
    inspect_phase7d_razorpay_test_execution_readiness,
    preview_phase7d_razorpay_test_execution_attempt,
    serialize_phase7d_attempt as _serialize_phase7d_attempt,
    serialize_phase7d_rollback as _serialize_phase7d_rollback,
    summarize_phase7d_attempts,
)
from apps.payments.razorpay_whatsapp_internal_notification import (
    inspect_phase7e_readiness,
    preview_phase7e_gate,
    serialize_phase7e_dry_run_record as _serialize_phase7e_dry_run_record,
    serialize_phase7e_gate as _serialize_phase7e_gate,
    summarize_phase7e_gates,
)
from apps.payments.razorpay_courier_readiness import (
    inspect_phase7f_readiness,
    preview_phase7f_gate,
    serialize_phase7f_dry_run_record as _serialize_phase7f_dry_run_record,
    serialize_phase7f_gate as _serialize_phase7f_gate,
    summarize_phase7f_gates,
)
from apps.payments.razorpay_courier_execution import (
    inspect_phase7g_courier_execution_readiness,
    preview_phase7g_courier_execution_attempt,
    serialize_phase7g_attempt as _serialize_phase7g_attempt,
    serialize_phase7g_rollback as _serialize_phase7g_rollback,
    summarize_phase7g_attempts,
)
from apps.payments.models import (
    RazorpayControlledPilotExecutionAttempt,
    RazorpayControlledPilotExecutionGate,
    RazorpayControlledPilotExecutionRollback,
    RazorpayControlledPilotGateDryRunRecord,
    RazorpayControlledPilotGateRollbackDryRunRecord,
    RazorpayCourierExecutionAttempt,
    RazorpayCourierExecutionRollback,
    RazorpayPaymentDispatchPilotPlan,
    RazorpayPaymentDispatchReadinessGate,
    RazorpayPaymentOrderWorkflowGate,
    RazorpayPhase6FinalAuditLock,
    RazorpaySandboxPaidStatusMutationAttempt,
    RazorpaySandboxStatusReview,
    RazorpayCourierReadinessDryRunRecord,
    RazorpayCourierReadinessGate,
    RazorpayWhatsAppInternalNotificationDryRunRecord,
    RazorpayWhatsAppInternalNotificationGate,
)
from apps.payments.razorpay_webhook_readiness import (
    get_razorpay_webhook_handler_readiness,
)
from apps.payments.models import RazorpayWebhookEvent
from apps.payments.management.commands.inspect_razorpay_webhook_events import (
    _serialize as _serialize_razorpay_webhook_event,
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
    RuntimeProviderExecutionAttempt,
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


class ProviderExecutionAttemptsListView(APIView):
    """``GET /api/v1/saas/provider-execution-attempts/`` — Phase 6K.

    Read-only inspector for Razorpay test-mode execution attempts.
    Auth required. POST/PATCH/DELETE return 405 (the actual provider
    execution is CLI-only in Phase 6K).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_admin_org(request)
        return Response(
            inspect_single_provider_execution_attempt(organization=org)
        )


class ProviderExecutionAttemptDetailView(APIView):
    """``GET /api/v1/saas/provider-execution-attempts/<execution_id>/``."""

    permission_classes = [IsAuthenticated]

    def get(self, _request, execution_id):
        attempt = RuntimeProviderExecutionAttempt.objects.filter(
            execution_id=execution_id
        ).first()
        if attempt is None:
            return Response(
                {"detail": "Provider execution attempt not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(serialize_execution_attempt(attempt))


class ProviderExecutionAttemptPrepareView(APIView):
    """``POST /api/v1/saas/provider-execution-attempts/prepare/``.

    Admin-only. Creates an attempt row in ``prepared``/``blocked``;
    NEVER calls Razorpay. Actual execution remains CLI-only via
    ``manage.py execute_single_razorpay_test_order``.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request):
        plan_id = request.data.get("planId") or request.data.get("plan_id")
        if not plan_id:
            return Response(
                {"detail": "planId required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        plan = RuntimeProviderTestPlan.objects.filter(plan_id=plan_id).first()
        if plan is None:
            return Response(
                {"detail": "Provider test plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        attempt = prepare_single_provider_execution_attempt(
            plan_id, actor=request.user
        )
        return Response(
            serialize_execution_attempt(attempt),
            status=status.HTTP_201_CREATED,
        )


class ProviderExecutionAttemptRollbackView(APIView):
    """``POST /api/v1/saas/provider-execution-attempts/<execution_id>/rollback/``."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, execution_id):
        attempt = RuntimeProviderExecutionAttempt.objects.filter(
            execution_id=execution_id
        ).first()
        if attempt is None:
            return Response(
                {"detail": "Provider execution attempt not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        attempt = rollback_single_provider_execution_attempt(
            execution_id,
            actor=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_execution_attempt(attempt))


class ProviderExecutionAttemptArchiveView(APIView):
    """``POST /api/v1/saas/provider-execution-attempts/<execution_id>/archive/``."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, execution_id):
        attempt = RuntimeProviderExecutionAttempt.objects.filter(
            execution_id=execution_id
        ).first()
        if attempt is None:
            return Response(
                {"detail": "Provider execution attempt not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        attempt = archive_single_provider_execution_attempt(
            execution_id,
            actor=request.user,
            reason=request.data.get("reason") or "",
        )
        return Response(serialize_execution_attempt(attempt))


class RazorpayExecutionAuditReviewView(APIView):
    """``GET /api/v1/saas/razorpay/execution-audit/?execution_id=<ID>``.

    Phase 6L — read-only audit review of one Phase 6K Razorpay
    test-mode execution attempt. Auth required. POST returns 405.
    NEVER calls Razorpay. NEVER returns the raw provider response.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        execution_id = (
            request.query_params.get("execution_id")
            or request.query_params.get("executionId")
            or ""
        ).strip()
        if not execution_id:
            return Response(
                {"detail": "execution_id query parameter required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            review_razorpay_test_execution_audit(execution_id)
        )


class RazorpayWebhookReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/webhook-readiness/`` — Phase 6L.

    Read-only env + Phase 6K artefact sanity check. Reports presence
    only — never the raw webhook secret value. Auth required; POST
    returns 405.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(inspect_razorpay_webhook_readiness())


class RazorpayWebhookPlanView(APIView):
    """``GET /api/v1/saas/razorpay/webhook-plan/`` — Phase 6L policy doc.

    Returns the canonical Razorpay webhook readiness plan. Pure
    policy — does NOT register a webhook receiver. Auth required;
    POST returns 405.
    """

    permission_classes = [IsAuthenticated]

    def get(self, _request):
        return Response(plan_razorpay_webhook_readiness())


class RazorpayWebhookHandlerReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/webhook-handler-readiness/`` — Phase 6M.

    Read-only Phase 6M handler readiness report. Auth + admin only.
    POST/PATCH/DELETE return 405. NEVER returns the raw webhook
    secret.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(get_razorpay_webhook_handler_readiness())


class RazorpayWebhookEventsListView(APIView):
    """``GET /api/v1/saas/razorpay/webhook-events/`` — Phase 6M."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        qs = RazorpayWebhookEvent.objects.all().order_by("-received_at")
        event_name = (request.query_params.get("event_name") or "").strip()
        if event_name:
            qs = qs.filter(event_name=event_name)
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            qs = qs.filter(processing_status=status_filter)
        rows = list(qs[:limit])
        return Response(
            {
                "limit": limit,
                "count": len(rows),
                "events": [_serialize_razorpay_webhook_event(row) for row in rows],
                "businessMutationWasMade": False,
                "customerNotificationSent": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayWebhookEventDetailView(APIView):
    """``GET /api/v1/saas/razorpay/webhook-events/<id>/`` — Phase 6M."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, event_id):
        row = RazorpayWebhookEvent.objects.filter(id=event_id).first()
        if row is None:
            return Response(
                {"detail": "Razorpay webhook event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_razorpay_webhook_event(row))


class RazorpayWebhookSimulateView(APIView):
    """``POST /api/v1/saas/razorpay/webhook-events/simulate/`` — Phase 6M.

    Admin-only. Test-mode-only. Mirrors the
    ``simulate_razorpay_webhook_event`` management command via the
    same service path. NEVER calls Razorpay; NEVER mutates business
    records.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request):
        from django.conf import settings as _settings

        secret = getattr(_settings, "RAZORPAY_WEBHOOK_SECRET", "") or ""
        if not secret:
            return Response(
                {
                    "detail": "RAZORPAY_WEBHOOK_SECRET is not set; cannot sign synthetic event.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        event_name = (
            request.data.get("eventName")
            or request.data.get("event")
            or ""
        ).strip()
        if not event_name:
            return Response(
                {"detail": "eventName required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            amount_paise = int(request.data.get("amountPaise") or 100)
        except (TypeError, ValueError):
            amount_paise = 100

        # Build + sign + dispatch. We import the helpers locally so the
        # admin call goes through the same code path as the CLI.
        import json as _json
        from datetime import datetime, timezone
        from uuid import uuid4
        from apps.payments.management.commands.simulate_razorpay_webhook_event import (
            _build_payload,
        )
        from apps.payments.razorpay_webhooks import (
            compute_razorpay_signature,
            process_razorpay_webhook,
        )

        order_id = (
            request.data.get("orderId") or "order_Sks3KPf0vntKhf"
        )
        payment_id = request.data.get("paymentId") or "pay_test_phase6m"
        refund_id = request.data.get("refundId") or "rfnd_test_phase6m"
        payment_link_id = (
            request.data.get("paymentLinkId") or "plink_test_phase6m"
        )
        event_id = (
            request.data.get("eventId") or f"evt_test_{uuid4().hex[:16]}"
        )
        created_at_epoch = int(datetime.now(tz=timezone.utc).timestamp())
        payload = _build_payload(
            event_name=event_name,
            amount_paise=amount_paise,
            order_id=order_id,
            payment_id=payment_id,
            refund_id=refund_id,
            payment_link_id=payment_link_id,
            created_at_epoch=created_at_epoch,
        )
        body = _json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = compute_razorpay_signature(body, secret)
        result = process_razorpay_webhook(
            raw_body=body,
            headers={
                "x-razorpay-signature": signature,
                "x-razorpay-event-id": event_id,
                "content-type": "application/json",
                "user-agent": "razorpay-simulator/phase6m-admin",
            },
            request_meta={"source": "saas-admin-simulator"},
        )
        return Response(result)


class RazorpaySandboxStatusMappingReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-status-mapping-readiness/`` — Phase 6O.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates business tables.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase6o_sandbox_status_mapping_readiness())


class RazorpaySandboxStatusReviewsListView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-status-reviews/`` — Phase 6O list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6o_reviews(limit=limit)
        # Locked-False posture asserted in the response shape so the
        # frontend can render a "Disabled" badge straight from the API.
        return Response(
            {
                "phase": "6O",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "businessMutationWasMade": False,
                "customerNotificationSent": False,
                "providerCallAttempted": False,
            }
        )


class RazorpaySandboxStatusReviewDetailView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-status-reviews/<id>/`` — Phase 6O."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = RazorpaySandboxStatusReview.objects.filter(pk=pk).first()
        if row is None:
            return Response(
                {"detail": "Phase 6O sandbox review not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6o_review(row))


class RazorpaySandboxStatusReviewPrepareView(APIView):
    """``POST /api/v1/saas/razorpay/sandbox-status-reviews/prepare/`` — Phase 6O.

    Requires admin auth. NEVER mutates business tables. NEVER calls
    Razorpay. Refuses unless ``RAZORPAY_SANDBOX_STATUS_MAPPING_ENABLED``
    is ``True`` AND the source event is synthetic-eligible.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request):
        event_id = request.data.get("eventId") or request.data.get("event_id")
        try:
            event_id_int = int(event_id) if event_id is not None else 0
        except (TypeError, ValueError):
            return Response(
                {"detail": "eventId must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report = prepare_phase6o_sandbox_status_review(
            event_id_int, requested_by=request.user
        )
        http_status = (
            status.HTTP_201_CREATED
            if report.get("created")
            else status.HTTP_200_OK
        )
        return Response(report, status=http_status)


class RazorpaySandboxStatusReviewApproveView(APIView):
    """``POST /api/v1/saas/razorpay/sandbox-status-reviews/<id>/approve/``.

    Phase 6O — marks the review approved **for future Phase 6P only**.
    NEVER mutates ``Order`` / ``Payment`` / ``Shipment`` /
    ``DiscountOfferLog``. NEVER sends a customer notification. NEVER
    calls Razorpay.
    """

    permission_classes = [AdminSaasPermission]

    def post(self, request, pk: int):
        reason = (request.data.get("reason") or "").strip()
        report = approve_phase6o_sandbox_status_review(
            pk, reviewed_by=request.user, reason=reason
        )
        return Response(report)


class RazorpaySandboxStatusReviewRejectView(APIView):
    """``POST /api/v1/saas/razorpay/sandbox-status-reviews/<id>/reject/`` — Phase 6O."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, pk: int):
        reason = (request.data.get("reason") or "").strip()
        report = reject_phase6o_sandbox_status_review(
            pk, reviewed_by=request.user, reason=reason
        )
        return Response(report)


class RazorpaySandboxStatusReviewArchiveView(APIView):
    """``POST /api/v1/saas/razorpay/sandbox-status-reviews/<id>/archive/`` — Phase 6O."""

    permission_classes = [AdminSaasPermission]

    def post(self, request, pk: int):
        reason = (request.data.get("reason") or "").strip()
        report = archive_phase6o_sandbox_status_review(
            pk, archived_by=request.user, reason=reason
        )
        return Response(report)


class RazorpayPaymentOrderWorkflowGateReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/payment-order-workflow-gate-readiness/`` — Phase 6Q.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates anything; review state
    changes are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(
            inspect_phase6q_payment_order_workflow_gate_readiness()
        )


class RazorpayPaymentOrderWorkflowGatesListView(APIView):
    """``GET /api/v1/saas/razorpay/payment-order-workflow-gates/`` — Phase 6Q list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6q_payment_order_workflow_gates(limit=limit)
        return Response(
            {
                "phase": "6Q",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "shipmentMutationWasMade": False,
                "discountMutationWasMade": False,
                "customerNotificationSent": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayPaymentOrderWorkflowGateDetailView(APIView):
    """``GET /api/v1/saas/razorpay/payment-order-workflow-gates/<id>/`` — Phase 6Q."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentOrderWorkflowGate.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 6Q payment-order workflow gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6q_gate(row))


class RazorpayPaymentOrderWorkflowGatePreviewView(APIView):
    """``GET /api/v1/saas/razorpay/payment-order-workflow-gate-preview/?attempt_id=<ID>`` — Phase 6Q.

    Read-only preview; never creates rows.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            attempt_id = int(request.query_params.get("attempt_id") or 0)
        except (TypeError, ValueError):
            attempt_id = 0
        try:
            ledger_id = int(request.query_params.get("ledger_id") or 0)
        except (TypeError, ValueError):
            ledger_id = 0
        if attempt_id <= 0 and ledger_id <= 0:
            return Response(
                {
                    "detail": (
                        "attempt_id or ledger_id query param required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            preview_phase6q_payment_order_workflow_gate(
                source_attempt_id=attempt_id or None,
                ledger_id=ledger_id or None,
            )
        )


# ---------------------------------------------------------------------------
# Phase 6R — Payment → WhatsApp / Courier Dispatch Readiness (audit-only)
# ---------------------------------------------------------------------------


class RazorpayPaymentDispatchReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-readiness/`` — Phase 6R.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates anything; NEVER sends
    WhatsApp; NEVER calls Meta Cloud / Delhivery; review state changes
    are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase6r_payment_dispatch_readiness())


class RazorpayPaymentDispatchReadinessGatesListView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-readiness-gates/`` — Phase 6R list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6r_payment_dispatch_readiness_gates(
            limit=limit
        )
        return Response(
            {
                "phase": "6R",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "shipmentMutationWasMade": False,
                "shipmentCreated": False,
                "whatsAppMessageCreated": False,
                "whatsAppMessageQueued": False,
                "customerNotificationSent": False,
                "metaCloudCallAttempted": False,
                "delhiveryCallAttempted": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayPaymentDispatchReadinessGateDetailView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-readiness-gates/<id>/`` — Phase 6R."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentDispatchReadinessGate.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 6R payment dispatch readiness gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6r_readiness(row))


class RazorpayPaymentDispatchReadinessPreviewView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-readiness-preview/?gate_id=<ID>`` — Phase 6R.

    Read-only preview from an approved Phase 6Q workflow gate; never
    creates rows; never sends WhatsApp; never calls Meta Cloud /
    Delhivery.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            gate_id = int(request.query_params.get("gate_id") or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {"detail": "gate_id query param required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            preview_phase6r_payment_dispatch_readiness_gate(gate_id)
        )


# ---------------------------------------------------------------------------
# Phase 6S — Limited Internal Dispatch Pilot Plan (planning-only)
# ---------------------------------------------------------------------------


class RazorpayPaymentDispatchPilotPlanReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-pilot-plan-readiness/`` — Phase 6S.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER starts a pilot; NEVER sends
    WhatsApp; NEVER calls Meta Cloud / Delhivery / Razorpay; review
    state changes are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(
            inspect_phase6s_payment_dispatch_pilot_plan_readiness()
        )


class RazorpayPaymentDispatchPilotPlansListView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-pilot-plans/`` — Phase 6S list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6s_payment_dispatch_pilot_plans(limit=limit)
        return Response(
            {
                "phase": "6S",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "pilotExecutionAllowedInPhase6S": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "shipmentMutationWasMade": False,
                "shipmentCreated": False,
                "awbCreated": False,
                "whatsAppMessageCreated": False,
                "whatsAppMessageQueued": False,
                "customerNotificationSent": False,
                "metaCloudCallAttempted": False,
                "delhiveryCallAttempted": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayPaymentDispatchPilotPlanDetailView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-pilot-plans/<id>/`` — Phase 6S."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentDispatchPilotPlan.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 6S payment dispatch pilot plan not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6s_pilot_plan(row))


class RazorpayPaymentDispatchPilotPlanPreviewView(APIView):
    """``GET /api/v1/saas/razorpay/payment-dispatch-pilot-plan-preview/?readiness_id=<ID>`` — Phase 6S.

    Read-only preview from an approved Phase 6R readiness gate; never
    creates rows; never starts a pilot; never sends WhatsApp; never
    calls Meta Cloud / Delhivery / Razorpay.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            readiness_id = int(request.query_params.get("readiness_id") or 0)
        except (TypeError, ValueError):
            readiness_id = 0
        if readiness_id <= 0:
            return Response(
                {"detail": "readiness_id query param required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            preview_phase6s_payment_dispatch_pilot_plan(readiness_id)
        )


# ---------------------------------------------------------------------------
# Phase 6T - Final Phase 6 Audit + Lock / Decision Gate (read-only API)
# ---------------------------------------------------------------------------


class RazorpayPhase6FinalAuditLockReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/phase6-final-audit-lock-readiness/``.

    Phase 6T is final-audit-lock only. Auth + admin only; POST/PATCH/
    DELETE return 405. Review state changes stay CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase6t_final_audit_lock_readiness())


class RazorpayPhase6FinalAuditLocksListView(APIView):
    """``GET /api/v1/saas/razorpay/phase6-final-audit-locks/``."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6t_final_audit_locks(limit=limit)
        return Response(
            {
                "phase": "6T",
                "status": "final_audit_lock_only",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only_review",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "futureControlledPilotAllowedByPhase6T": False,
                "controlledPilotExecutionAllowedInPhase6T": False,
                "pilotExecutionAllowed": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "shipmentMutationWasMade": False,
                "shipmentCreated": False,
                "awbCreated": False,
                "whatsAppMessageCreated": False,
                "whatsAppMessageQueued": False,
                "customerNotificationSent": False,
                "metaCloudCallAttempted": False,
                "delhiveryCallAttempted": False,
                "razorpayCallAttempted": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayPhase6FinalAuditLockDetailView(APIView):
    """``GET /api/v1/saas/razorpay/phase6-final-audit-locks/<id>/``."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = RazorpayPhase6FinalAuditLock.objects.filter(pk=pk).first()
        if row is None:
            return Response(
                {"detail": "Phase 6T final audit lock not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6t_audit_lock(row))


class RazorpayPhase6FinalAuditLockPreviewView(APIView):
    """Read-only Phase 6T final audit-lock preview."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            plan_id = int(request.query_params.get("plan_id") or 0)
        except (TypeError, ValueError):
            plan_id = 0
        return Response(
            preview_phase6t_final_audit_lock(plan_id if plan_id > 0 else None)
        )


# ---------------------------------------------------------------------------
# Phase 7B - Controlled Pilot Execution Gate (gate-only, CLI-only review)
# ---------------------------------------------------------------------------


class RazorpayControlledPilotGateReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gate-readiness/`` - Phase 7B.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls a provider; NEVER sends
    WhatsApp; review state changes are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase7b_controlled_pilot_gate_readiness())


class RazorpayControlledPilotGatesListView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gates/`` - Phase 7B list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase7b_controlled_pilot_gates(limit=limit)
        return Response(
            {
                "phase": "7B",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only_review",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "controlledPilotExecutionAllowedInPhase7B": False,
                "liveExecutionAllowedInPhase7B": False,
                "providerCallAllowedInPhase7B": False,
                "businessMutationAllowedInPhase7B": False,
                "customerNotificationAllowedInPhase7B": False,
                "whatsAppSendAllowedInPhase7B": False,
                "whatsAppQueueAllowedInPhase7B": False,
                "courierBookingAllowedInPhase7B": False,
                "shipmentCreationAllowedInPhase7B": False,
                "awbCreationAllowedInPhase7B": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "shipmentMutationWasMade": False,
                "shipmentCreated": False,
                "awbCreated": False,
                "whatsAppMessageCreated": False,
                "whatsAppMessageQueued": False,
                "customerNotificationSent": False,
                "metaCloudCallAttempted": False,
                "delhiveryCallAttempted": False,
                "razorpayCallAttempted": False,
                "providerCallAttempted": False,
            }
        )


class RazorpayControlledPilotGateDetailView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gates/<id>/`` - Phase 7B."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayControlledPilotExecutionGate.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7B controlled pilot execution gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7b_gate(row))


class RazorpayControlledPilotGatePreviewView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gate-preview/?phase6t_lock_id=<ID>`` - Phase 7B.

    Read-only preview from a locked Phase 6T audit lock; never creates
    rows; never calls a provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            lock_id = int(request.query_params.get("phase6t_lock_id") or 0)
        except (TypeError, ValueError):
            lock_id = 0
        if lock_id <= 0:
            return Response(
                {"detail": "phase6t_lock_id query param required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_phase7b_controlled_pilot_gate(lock_id))


class RazorpayControlledPilotGateDryRunsView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gate-dry-runs/<gate_id>/`` - Phase 7B."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayControlledPilotExecutionGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {"detail": "Phase 7B controlled pilot gate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayControlledPilotGateDryRunRecord.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7B",
                "gateId": gate_id,
                "items": [
                    _serialize_phase7b_dry_run_record(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


class RazorpayControlledPilotGateRollbackDryRunsView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-gate-rollback-dry-runs/<gate_id>/`` - Phase 7B."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayControlledPilotExecutionGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {"detail": "Phase 7B controlled pilot gate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayControlledPilotGateRollbackDryRunRecord.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7B",
                "gateId": gate_id,
                "items": [
                    _serialize_phase7b_rollback_dry_run_record(r)
                    for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


class RazorpaySandboxPaidStatusMutationReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-paid-status-mutation-readiness/`` — Phase 6P.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates anything; NEVER calls
    Razorpay; execution is exclusively via CLI.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase6p_paid_status_mutation_readiness())


class RazorpaySandboxPaidStatusMutationAttemptsListView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-paid-status-mutation-attempts/`` — Phase 6P list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase6p_paid_status_mutation_attempts(limit=limit)
        return Response(
            {
                "phase": "6P",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "ledgerCounts": report["ledgerCounts"],
                "ledgerItems": report["ledgerItems"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "businessMutationWasMade": False,
                "realOrderMutationWasMade": False,
                "realPaymentMutationWasMade": False,
                "customerNotificationSent": False,
                "providerCallAttempted": False,
            }
        )


class RazorpaySandboxPaidStatusMutationAttemptDetailView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-paid-status-mutation-attempts/<id>/`` — Phase 6P."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpaySandboxPaidStatusMutationAttempt.objects.filter(pk=pk)
            .first()
        )
        if row is None:
            return Response(
                {"detail": "Phase 6P sandbox mutation attempt not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase6p_attempt(row))


class RazorpaySandboxPaidStatusMutationPreviewView(APIView):
    """``GET /api/v1/saas/razorpay/sandbox-paid-status-mutation-preview/?review_id=<ID>`` — Phase 6P.

    Read-only preview only. Never creates rows.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            review_id = int(request.query_params.get("review_id") or 0)
        except (TypeError, ValueError):
            review_id = 0
        if review_id <= 0:
            return Response(
                {"detail": "review_id query param must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_phase6p_paid_status_mutation(review_id))


class RazorpayBusinessMutationSandboxPlanView(APIView):
    """``GET /api/v1/saas/razorpay/business-mutation-sandbox-plan/`` — Phase 6N.

    Returns the canonical Phase 6N planning JSON. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls Razorpay; NEVER returns
    raw secrets or PII.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(get_razorpay_business_mutation_sandbox_plan())


class RazorpayBusinessMutationSandboxReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/business-mutation-sandbox-readiness/`` — Phase 6N.

    Returns the Phase 6N readiness composition (blockers / warnings /
    safeToStartPhase6O). Auth + admin only; POST/PATCH/DELETE return
    405. NEVER calls Razorpay; NEVER mutates anything.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(
            inspect_razorpay_business_mutation_sandbox_readiness()
        )


class RazorpayControlledPilotExecutionReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-execution-readiness/`` - Phase 7D.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls Razorpay; NEVER sends
    WhatsApp; NEVER mutates business tables; NEVER edits any
    ``.env*`` file. Review and execution state changes are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(
            inspect_phase7d_razorpay_test_execution_readiness()
        )


class RazorpayControlledPilotExecutionAttemptsListView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-execution-attempts/`` - Phase 7D list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase7d_attempts(limit=limit)
        return Response(
            {
                "phase": "7D",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "controlledPilotExecutionAllowedInPhase7D": False,
                "phase7DSendsOrQueuesWhatsApp": False,
                "phase7DCallsMetaCloud": False,
                "phase7DCallsDelhivery": False,
                "phase7DCreatesShipmentOrAwb": False,
                "phase7DCreatesPaymentLink": False,
                "phase7DCapturesPayment": False,
                "phase7DRefundsPayment": False,
                "phase7DSendsCustomerNotification": False,
                "phase7DMutatesBusinessRow": False,
            }
        )


class RazorpayControlledPilotExecutionAttemptDetailView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-execution-attempts/<id>/`` - Phase 7D."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayControlledPilotExecutionAttempt.objects.filter(pk=pk)
            .first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7D controlled pilot execution attempt "
                        "not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7d_attempt(row))


class RazorpayControlledPilotExecutionPreviewView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-execution-preview/?gate_id=<ID>`` - Phase 7D.

    Read-only preview from an approved Phase 7B gate; never creates
    rows; never calls Razorpay.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            gate_id = int(request.query_params.get("gate_id") or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {"detail": "gate_id query param required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            preview_phase7d_razorpay_test_execution_attempt(gate_id)
        )


class RazorpayControlledPilotExecutionRollbacksView(APIView):
    """``GET /api/v1/saas/razorpay/controlled-pilot-execution-rollbacks/<attempt_id>/`` - Phase 7D."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, attempt_id: int):
        attempt_exists = (
            RazorpayControlledPilotExecutionAttempt.objects.filter(
                pk=attempt_id
            ).exists()
        )
        if not attempt_exists:
            return Response(
                {
                    "detail": (
                        "Phase 7D controlled pilot execution attempt "
                        "not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayControlledPilotExecutionRollback.objects.filter(
                attempt_id=attempt_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7D",
                "attemptId": attempt_id,
                "items": [
                    _serialize_phase7d_rollback(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


class RazorpayWhatsAppInternalNotificationReadinessView(APIView):
    """``GET /api/v1/saas/razorpay/whatsapp-internal-notification-readiness/`` - Phase 7E.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER sends WhatsApp; NEVER queues;
    NEVER calls Meta Cloud / Delhivery / Vapi; NEVER mutates real
    business rows; NEVER edits any ``.env*`` file. Review and gate
    state changes are CLI-only.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase7e_readiness())


class RazorpayWhatsAppInternalNotificationGatesListView(APIView):
    """``GET /api/v1/saas/razorpay/whatsapp-internal-notification-gates/`` - Phase 7E list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase7e_gates(limit=limit)
        return Response(
            {
                "phase": "7E",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase7ESendsWhatsApp": False,
                "phase7EQueuesWhatsApp": False,
                "phase7ECallsMetaCloud": False,
                "phase7ECallsDelhivery": False,
                "phase7ECreatesShipmentOrAwb": False,
                "phase7ECreatesPaymentLink": False,
                "phase7ECapturesPayment": False,
                "phase7ERefundsPayment": False,
                "phase7ESendsCustomerNotification": False,
                "phase7EMutatesBusinessRow": False,
            }
        )


class RazorpayWhatsAppInternalNotificationGateDetailView(APIView):
    """``GET /api/v1/saas/razorpay/whatsapp-internal-notification-gates/<pk>/`` - Phase 7E."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayWhatsAppInternalNotificationGate.objects.filter(pk=pk)
            .first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7E WhatsApp internal notification gate "
                        "not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7e_gate(row))


class RazorpayWhatsAppInternalNotificationPreviewView(APIView):
    """``GET /api/v1/saas/razorpay/whatsapp-internal-notification-preview/?attempt_id=<ID>`` - Phase 7E.

    Read-only preview from a Phase 7D attempt; never creates rows;
    never sends WhatsApp.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            attempt_id = int(request.query_params.get("attempt_id") or 0)
        except (TypeError, ValueError):
            attempt_id = 0
        if attempt_id <= 0:
            return Response(
                {
                    "detail": (
                        "attempt_id query param must be a positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_phase7e_gate(attempt_id))


class RazorpayWhatsAppInternalNotificationDryRunsView(APIView):
    """``GET /api/v1/saas/razorpay/whatsapp-internal-notification-dry-runs/<gate_id>/`` - Phase 7E."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayWhatsAppInternalNotificationGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 7E WhatsApp internal notification gate "
                        "not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayWhatsAppInternalNotificationDryRunRecord.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7E",
                "gateId": gate_id,
                "items": [
                    _serialize_phase7e_dry_run_record(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


class RazorpayCourierReadinessReadinessView(APIView):
    """``GET /api/v1/saas/delhivery/courier-readiness/`` - Phase 7F.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls Delhivery; NEVER
    creates a Shipment / WorkflowStep / RescueAttempt / AWB /
    pickup / label; NEVER sends WhatsApp; NEVER mutates real
    business rows; NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase7f_readiness())


class RazorpayCourierReadinessGatesListView(APIView):
    """``GET /api/v1/saas/delhivery/courier-readiness-gates/`` - Phase 7F list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase7f_gates(limit=limit)
        return Response(
            {
                "phase": "7F",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase7FCallsDelhivery": False,
                "phase7FCreatesShipmentRow": False,
                "phase7FCreatesAwb": False,
                "phase7FBooksPickup": False,
                "phase7FGeneratesLabel": False,
                "phase7FSendsWhatsApp": False,
                "phase7FQueuesWhatsApp": False,
                "phase7FCallsMetaCloud": False,
                "phase7FCallsRazorpay": False,
                "phase7FSendsCustomerNotification": False,
                "phase7FMutatesBusinessRow": False,
            }
        )


class RazorpayCourierReadinessGateDetailView(APIView):
    """``GET /api/v1/saas/delhivery/courier-readiness-gates/<pk>/`` - Phase 7F."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayCourierReadinessGate.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7F courier readiness gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7f_gate(row))


class RazorpayCourierReadinessPreviewView(APIView):
    """``GET /api/v1/saas/delhivery/courier-readiness-preview/?phase7e_gate_id=<ID>`` - Phase 7F."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            phase7e_gate_id = int(
                request.query_params.get("phase7e_gate_id") or 0
            )
        except (TypeError, ValueError):
            phase7e_gate_id = 0
        if phase7e_gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase7e_gate_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(preview_phase7f_gate(phase7e_gate_id))


class RazorpayCourierReadinessDryRunsView(APIView):
    """``GET /api/v1/saas/delhivery/courier-readiness-dry-runs/<gate_id>/`` - Phase 7F."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayCourierReadinessGate.objects.filter(pk=gate_id)
            .exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 7F courier readiness gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayCourierReadinessDryRunRecord.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7F",
                "gateId": gate_id,
                "items": [
                    _serialize_phase7f_dry_run_record(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


class RazorpayCourierExecutionReadinessView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-readiness/`` - Phase 7G.

    Read-only readiness composition for the One-shot Delhivery
    TEST/MOCK courier execution gate. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls Delhivery; NEVER
    creates a Shipment / WorkflowStep / RescueAttempt / AWB / pickup
    / label; NEVER sends WhatsApp; NEVER mutates real business rows;
    NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(inspect_phase7g_courier_execution_readiness())


class RazorpayCourierExecutionAttemptsListView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-attempts/`` - Phase 7G list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = summarize_phase7g_attempts(limit=limit)
        return Response(
            {
                "phase": "7G",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase7GCallsDelhivery": False,
                "phase7GCreatesShipmentRow": False,
                "phase7GCreatesAwbRowOnAttemptOnly": True,
                "phase7GBooksCourierPickupSeparately": False,
                "phase7GGeneratesCourierLabel": False,
                "phase7GSendsWhatsApp": False,
                "phase7GQueuesWhatsApp": False,
                "phase7GCallsMetaCloud": False,
                "phase7GCallsRazorpay": False,
                "phase7GCallsVapi": False,
                "phase7GSendsCustomerNotification": False,
                "phase7GMutatesBusinessRow": False,
                "phase7GLiveCustomerCourierApproved": False,
            }
        )


class RazorpayCourierExecutionAttemptDetailView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-attempts/<pk>/`` - Phase 7G."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayCourierExecutionAttempt.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7G courier execution attempt not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7g_attempt(row))


class RazorpayCourierExecutionPreviewView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-preview/?gate_id=<ID>`` - Phase 7G."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            phase7f_gate_id = int(
                request.query_params.get("gate_id") or 0
            )
        except (TypeError, ValueError):
            phase7f_gate_id = 0
        if phase7f_gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "gate_id query param must be a positive "
                        "integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            preview_phase7g_courier_execution_attempt(phase7f_gate_id)
        )


class RazorpayCourierExecutionRollbacksView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-rollbacks/<attempt_id>/`` - Phase 7G."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, attempt_id: int):
        attempt_exists = (
            RazorpayCourierExecutionAttempt.objects.filter(
                pk=attempt_id
            ).exists()
        )
        if not attempt_exists:
            return Response(
                {
                    "detail": (
                        "Phase 7G courier execution attempt not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayCourierExecutionRollback.objects.filter(
                attempt_id=attempt_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "7G",
                "attemptId": attempt_id,
                "items": [
                    _serialize_phase7g_rollback(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
            }
        )


# ---------------------------------------------------------------------------
# Phase 7H - Courier Execution Evidence Lock (read-only)
# ---------------------------------------------------------------------------


from apps.payments.razorpay_courier_execution_evidence_lock import (  # noqa: E402
    inspect_phase7h_evidence_lock_readiness as _inspect_phase7h_readiness,
    preview_phase7h_evidence_lock as _preview_phase7h_lock,
    serialize_phase7h_evidence_lock as _serialize_phase7h_lock,
    summarize_phase7h_evidence_locks as _summarize_phase7h_locks,
)
from apps.payments.models import (  # noqa: E402
    RazorpayCourierExecutionEvidenceLock,
    RazorpayWhatsAppInternalSendAttempt,
)


class RazorpayCourierExecutionEvidenceLockReadinessView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-evidence-lock-readiness/`` - Phase 7H.

    Read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase7h_readiness())


class RazorpayCourierExecutionEvidenceLocksListView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-evidence-locks/`` - Phase 7H list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase7h_locks(limit=limit)
        return Response(
            {
                "phase": "7H",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "lock_only_cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase7HCallsDelhivery": False,
                "phase7HCreatesShipmentRow": False,
                "phase7HCreatesAwb": False,
                "phase7HSendsWhatsApp": False,
                "phase7HQueuesWhatsApp": False,
                "phase7HCallsMetaCloud": False,
                "phase7HCallsRazorpay": False,
                "phase7HSendsCustomerNotification": False,
                "phase7HMutatesBusinessRow": False,
                "phase7HLiveCustomerCourierApproved": False,
            }
        )


class RazorpayCourierExecutionEvidenceLockDetailView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-evidence-locks/<pk>/`` - Phase 7H."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayCourierExecutionEvidenceLock.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7H courier execution evidence lock "
                        "not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7h_lock(row))


class RazorpayCourierExecutionEvidenceLockPreviewView(APIView):
    """``GET /api/v1/saas/delhivery/courier-execution-evidence-lock-preview/?attempt_id=<ID>`` - Phase 7H."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            attempt_id = int(
                request.query_params.get("attempt_id") or 0
            )
        except (TypeError, ValueError):
            attempt_id = 0
        if attempt_id <= 0:
            return Response(
                {
                    "detail": (
                        "attempt_id query param must be a positive "
                        "integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_preview_phase7h_lock(attempt_id))


# ---------------------------------------------------------------------------
# Phase 7E-Live-A - Internal Allowed-list WhatsApp Send (read-only)
# ---------------------------------------------------------------------------


from apps.payments.razorpay_whatsapp_internal_send import (  # noqa: E402
    inspect_phase7e_live_internal_send_readiness as _inspect_phase7e_live_readiness,
    preview_phase7e_live_internal_send as _preview_phase7e_live_send,
    serialize_phase7e_live_internal_send_attempt as _serialize_phase7e_live_attempt,
    summarize_phase7e_live_internal_send_attempts as _summarize_phase7e_live_attempts,
)


class WhatsAppInternalSendReadinessView(APIView):
    """``GET /api/v1/saas/whatsapp/internal-send-readiness/`` - Phase 7E-Live-A.

    Read-only readiness. Auth + admin only; POST/PATCH/DELETE
    return 405. No API execute endpoint exists.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase7e_live_readiness())


class WhatsAppInternalSendAttemptsListView(APIView):
    """``GET /api/v1/saas/whatsapp/internal-send-attempts/`` - Phase 7E-Live-A."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase7e_live_attempts(limit=limit)
        return Response(
            {
                "phase": "7E-Live-A",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "recipientScope": "internal_staff_allow_list",
                "phase7ELiveSendsToRealCustomer": False,
                "phase7ELiveMutatesBusinessRow": False,
                "phase7ELiveCustomerNotification": False,
                "phase7ELiveSupportsFreeformMedicalText": False,
            }
        )


class WhatsAppInternalSendAttemptDetailView(APIView):
    """``GET /api/v1/saas/whatsapp/internal-send-attempts/<pk>/`` - Phase 7E-Live-A."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayWhatsAppInternalSendAttempt.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7E-Live-A internal WhatsApp send "
                        "attempt not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7e_live_attempt(row))


class WhatsAppInternalSendPreviewView(APIView):
    """``GET /api/v1/saas/whatsapp/internal-send-preview/?gate_id=<ID>`` - Phase 7E-Live-A."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            gate_id = int(request.query_params.get("gate_id") or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "gate_id query param must be a positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_preview_phase7e_live_send(gate_id))


# ---------------------------------------------------------------------------
# Phase 7I - Final Phase 7 Payment + WhatsApp + Courier Audit Lock
# ---------------------------------------------------------------------------


from apps.payments.phase7_final_audit_lock import (  # noqa: E402
    inspect_phase7i_final_audit_lock_readiness as _inspect_phase7i_readiness,
    preview_phase7i_final_audit_lock as _preview_phase7i_lock,
    serialize_phase7i_final_audit_lock as _serialize_phase7i_lock,
    summarize_phase7i_final_audit_locks as _summarize_phase7i_locks,
)
from apps.payments.models import (  # noqa: E402
    RazorpayPhase7FinalAuditLock,
)


class Phase7IFinalAuditLockReadinessView(APIView):
    """``GET /api/v1/saas/phase7/final-audit-lock-readiness/`` -
    Phase 7I read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase7i_readiness())


class Phase7IFinalAuditLocksListView(APIView):
    """``GET /api/v1/saas/phase7/final-audit-locks/`` - Phase 7I list."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase7i_locks(limit=limit)
        return Response(
            {
                "phase": "7I",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "lock_only_cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase7ICallsRazorpay": False,
                "phase7ICallsMetaCloud": False,
                "phase7ICallsDelhivery": False,
                "phase7ICallsVapi": False,
                "phase7ISendsWhatsApp": False,
                "phase7IQueuesWhatsApp": False,
                "phase7ICreatesShipmentRow": False,
                "phase7ICreatesAwb": False,
                "phase7ICreatesPaymentLink": False,
                "phase7ICapturesPayment": False,
                "phase7IRefundsPayment": False,
                "phase7ISendsCustomerNotification": False,
                "phase7IMutatesBusinessRow": False,
                "phase7ELiveBApproved": False,
                "phase7GLiveApproved": False,
            }
        )


class Phase7IFinalAuditLockDetailView(APIView):
    """``GET /api/v1/saas/phase7/final-audit-locks/<pk>/`` - Phase 7I."""

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPhase7FinalAuditLock.objects.filter(pk=pk).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 7I final audit lock not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase7i_lock(row))


class Phase7IFinalAuditLockPreviewView(APIView):
    """``GET /api/v1/saas/phase7/final-audit-lock-preview/?...`` - Phase 7I."""

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        def _coerce_positive(name: str) -> int:
            try:
                return int(request.query_params.get(name) or 0)
            except (TypeError, ValueError):
                return 0

        g_id = _coerce_positive("phase7g_attempt_id")
        h_id = _coerce_positive("phase7h_evidence_lock_id")
        e_id = _coerce_positive("phase7e_live_attempt_id") or None
        d_id = _coerce_positive("phase7d_attempt_id") or None
        if g_id <= 0 or h_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase7g_attempt_id and "
                        "phase7h_evidence_lock_id query params must "
                        "be positive integers."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            _preview_phase7i_lock(
                phase7g_attempt_id=g_id,
                phase7h_evidence_lock_id=h_id,
                phase7e_live_attempt_id=e_id,
                phase7d_attempt_id=d_id,
            )
        )


# ---------------------------------------------------------------------------
# Phase 8A - Payment -> Order Mutation Sandbox Gate
# ---------------------------------------------------------------------------


from apps.payments.phase8a_payment_order_mutation_sandbox import (  # noqa: E402
    inspect_phase8a_payment_order_mutation_sandbox_readiness as _inspect_phase8a_readiness,
    preview_phase8a_payment_order_mutation_sandbox as _preview_phase8a_gate,
    serialize_phase8a_dry_run as _serialize_phase8a_dry_run,
    serialize_phase8a_gate as _serialize_phase8a_gate,
    summarize_phase8a_gates as _summarize_phase8a_gates,
)
from apps.payments.models import (  # noqa: E402
    RazorpayPaymentOrderMutationDryRun,
    RazorpayPaymentOrderMutationSandboxGate,
)


class Phase8APaymentOrderMutationSandboxReadinessView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-sandbox-readiness/``.

    Phase 8A read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates real ``Order`` /
    ``Payment`` / ``Shipment`` / ``Customer`` / ``Lead`` rows; NEVER
    calls Razorpay / Meta Cloud / Delhivery / Vapi; NEVER sends a
    customer notification; NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase8a_readiness())


class Phase8APaymentOrderMutationSandboxGatesListView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-sandbox-gates/``.

    Phase 8A read-only list of sandbox gates.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase8a_gates(limit=limit)
        return Response(
            {
                "phase": "8A",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "sandbox_dry_run_only_cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase8ACallsRazorpay": False,
                "phase8ACallsMetaCloud": False,
                "phase8ACallsDelhivery": False,
                "phase8ACallsVapi": False,
                "phase8ASendsWhatsApp": False,
                "phase8AQueuesWhatsApp": False,
                "phase8ACreatesShipmentRow": False,
                "phase8ACreatesAwb": False,
                "phase8ACreatesPaymentLink": False,
                "phase8ACapturesPayment": False,
                "phase8ARefundsPayment": False,
                "phase8ASendsCustomerNotification": False,
                "phase8AMutatesBusinessRow": False,
                "phase8AMutatesRealOrder": False,
                "phase8AMutatesRealPayment": False,
                "phase8ARealCustomerAutomationApproved": False,
            }
        )


class Phase8APaymentOrderMutationSandboxGateDetailView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-sandbox-gates/<pk>/``.

    Phase 8A read-only gate detail.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentOrderMutationSandboxGate.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 8A payment order mutation sandbox "
                        "gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase8a_gate(row))


class Phase8APaymentOrderMutationSandboxPreviewView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-sandbox-preview/``.

    Phase 8A read-only preview composed from a Phase 7I final audit
    lock id. NEVER mutates the database; NEVER calls any provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        raw = request.query_params.get("phase7i_lock_id")
        try:
            lock_id = int(raw or 0)
        except (TypeError, ValueError):
            lock_id = 0
        if lock_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase7i_lock_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            _preview_phase8a_gate(phase7i_lock_id=lock_id)
        )


class Phase8APaymentOrderMutationSandboxDryRunsView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-sandbox-dry-runs/<gate_id>/``.

    Phase 8A read-only list of dry-run records for one sandbox gate.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayPaymentOrderMutationSandboxGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8A payment order mutation sandbox "
                        "gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayPaymentOrderMutationDryRun.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8A",
                "gateId": gate_id,
                "items": [
                    _serialize_phase8a_dry_run(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8AMutatesBusinessRow": False,
                "phase8ACallsRazorpay": False,
                "phase8ACallsMetaCloud": False,
                "phase8ACallsDelhivery": False,
                "phase8ASendsWhatsApp": False,
                "phase8ASendsCustomerNotification": False,
            }
        )


# ---------------------------------------------------------------------------
# Phase 8B - Payment -> Order Mutation Review Gate
# ---------------------------------------------------------------------------


from apps.payments.phase8b_payment_order_mutation_review import (  # noqa: E402
    inspect_phase8b_payment_order_mutation_review_readiness as _inspect_phase8b_readiness,
    preview_phase8b_payment_order_mutation_review_gate as _preview_phase8b_gate,
    serialize_phase8b_dry_run as _serialize_phase8b_dry_run,
    serialize_phase8b_gate as _serialize_phase8b_gate,
    summarize_phase8b_gates as _summarize_phase8b_gates,
)
from apps.payments.models import (  # noqa: E402
    RazorpayPaymentOrderMutationReviewDryRun,
    RazorpayPaymentOrderMutationReviewGate,
)


class Phase8BPaymentOrderMutationReviewReadinessView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-review-readiness/``.

    Phase 8B read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates real ``Order`` /
    ``Payment`` / ``Shipment`` / ``Customer`` / ``Lead`` rows;
    NEVER calls Razorpay / Meta Cloud / Delhivery / Vapi; NEVER
    sends a customer notification; NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase8b_readiness())


class Phase8BPaymentOrderMutationReviewGatesListView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-review-gates/``.

    Phase 8B read-only list of review gates.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase8b_gates(limit=limit)
        return Response(
            {
                "phase": "8B",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "review_dry_run_only_cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase8BCallsRazorpay": False,
                "phase8BCallsMetaCloud": False,
                "phase8BCallsDelhivery": False,
                "phase8BCallsVapi": False,
                "phase8BSendsWhatsApp": False,
                "phase8BQueuesWhatsApp": False,
                "phase8BCreatesShipmentRow": False,
                "phase8BCreatesAwb": False,
                "phase8BCreatesPaymentLink": False,
                "phase8BCapturesPayment": False,
                "phase8BRefundsPayment": False,
                "phase8BSendsCustomerNotification": False,
                "phase8BMutatesBusinessRow": False,
                "phase8BMutatesRealOrder": False,
                "phase8BMutatesRealPayment": False,
                "phase8BApprovesPhase8C": False,
                "phase8BApprovesRealCustomerAutomation": False,
            }
        )


class Phase8BPaymentOrderMutationReviewGateDetailView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-review-gates/<pk>/``.

    Phase 8B read-only gate detail.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentOrderMutationReviewGate.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 8B payment order mutation review "
                        "gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase8b_gate(row))


class Phase8BPaymentOrderMutationReviewPreviewView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-review-preview/``.

    Phase 8B read-only preview composed from a Phase 8A sandbox gate
    id. NEVER mutates the database; NEVER calls any provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        raw = request.query_params.get("phase8a_gate_id")
        try:
            gate_id = int(raw or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase8a_gate_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            _preview_phase8b_gate(phase8a_gate_id=gate_id)
        )


class Phase8BPaymentOrderMutationReviewDryRunsView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-mutation-review-dry-runs/<gate_id>/``.

    Phase 8B read-only list of dry-run records for one review gate.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayPaymentOrderMutationReviewGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8B payment order mutation review "
                        "gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayPaymentOrderMutationReviewDryRun.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8B",
                "gateId": gate_id,
                "items": [
                    _serialize_phase8b_dry_run(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8BMutatesBusinessRow": False,
                "phase8BCallsRazorpay": False,
                "phase8BCallsMetaCloud": False,
                "phase8BCallsDelhivery": False,
                "phase8BSendsWhatsApp": False,
                "phase8BSendsCustomerNotification": False,
            }
        )


# ---------------------------------------------------------------------------
# Phase 8C - Controlled Real Payment -> Order Mutation
# ---------------------------------------------------------------------------


from apps.payments.phase8c_payment_order_controlled_mutation import (  # noqa: E402
    inspect_phase8c_payment_order_controlled_mutation_readiness as _inspect_phase8c_readiness,
    preview_phase8c_payment_order_controlled_mutation as _preview_phase8c_gate,
    serialize_phase8c_attempt as _serialize_phase8c_attempt,
    serialize_phase8c_gate as _serialize_phase8c_gate,
    serialize_phase8c_rollback as _serialize_phase8c_rollback,
    summarize_phase8c_gates as _summarize_phase8c_gates,
)
from apps.payments.models import (  # noqa: E402
    RazorpayPaymentOrderControlledMutationAttempt,
    RazorpayPaymentOrderControlledMutationGate,
    RazorpayPaymentOrderControlledMutationRollback,
)


class Phase8CPaymentOrderControlledMutationReadinessView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-readiness/``.

    Phase 8C read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER calls Razorpay / Meta Cloud
    / Delhivery / Vapi; NEVER sends WhatsApp; NEVER sends a
    customer notification; NEVER mutates business rows; NEVER edits
    any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase8c_readiness())


class Phase8CPaymentOrderControlledMutationGatesListView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-gates/``.

    Phase 8C read-only list of controlled-mutation gates.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase8c_gates(limit=limit)
        return Response(
            {
                "phase": "8C",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": (
                    "cli_only_one_shot_controlled_mutation"
                ),
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase8CCallsRazorpay": False,
                "phase8CCallsMetaCloud": False,
                "phase8CCallsDelhivery": False,
                "phase8CCallsVapi": False,
                "phase8CSendsWhatsApp": False,
                "phase8CQueuesWhatsApp": False,
                "phase8CCreatesShipmentRow": False,
                "phase8CCreatesAwb": False,
                "phase8CCreatesPaymentLink": False,
                "phase8CCapturesPayment": False,
                "phase8CRefundsPayment": False,
                "phase8CSendsCustomerNotification": False,
                "phase8CMutatesCustomer": False,
                "phase8CMutatesLead": False,
                "phase8CMutatesShipment": False,
                "phase8CMutatesDiscountOfferLog": False,
                "phase8CApprovesRealCustomerAutomation": False,
            }
        )


class Phase8CPaymentOrderControlledMutationGateDetailView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-gates/<pk>/``.

    Phase 8C read-only gate detail.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentOrderControlledMutationGate.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 8C payment order controlled "
                        "mutation gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase8c_gate(row))


class Phase8CPaymentOrderControlledMutationPreviewView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-preview/``.

    Phase 8C read-only preview composed from a Phase 8B review gate
    id. NEVER mutates the database; NEVER calls any provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        raw = request.query_params.get("phase8b_gate_id")
        try:
            gate_id = int(raw or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase8b_gate_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_preview_phase8c_gate(phase8b_gate_id=gate_id))


class Phase8CPaymentOrderControlledMutationAttemptsView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-attempts/<gate_id>/``.

    Phase 8C read-only list of attempt rows for one gate.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayPaymentOrderControlledMutationGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8C payment order controlled "
                        "mutation gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayPaymentOrderControlledMutationAttempt.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8C",
                "gateId": gate_id,
                "items": [
                    _serialize_phase8c_attempt(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8CCallsRazorpay": False,
                "phase8CCallsMetaCloud": False,
                "phase8CCallsDelhivery": False,
                "phase8CSendsWhatsApp": False,
                "phase8CSendsCustomerNotification": False,
            }
        )


# ---------------------------------------------------------------------------
# Phase 8D - Controlled Mutation Evidence Lock
# ---------------------------------------------------------------------------


from apps.payments.phase8d_controlled_mutation_evidence_lock import (  # noqa: E402
    inspect_phase8d_controlled_mutation_evidence_lock_readiness as _inspect_phase8d_readiness,
    preview_phase8d_controlled_mutation_evidence_lock as _preview_phase8d_lock,
    serialize_phase8d_lock as _serialize_phase8d_lock,
    summarize_phase8d_locks as _summarize_phase8d_locks,
)
from apps.payments.models import (  # noqa: E402
    RazorpayPaymentOrderControlledMutationEvidenceLock,
)


class Phase8DControlledMutationEvidenceLockReadinessView(APIView):
    """``GET /api/v1/saas/phase8/controlled-mutation-evidence-lock-readiness/``.

    Phase 8D read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. Lock-only meta-audit; NEVER
    executes Phase 8C again; NEVER calls a provider; NEVER mutates
    business rows; NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase8d_readiness())


class Phase8DControlledMutationEvidenceLocksListView(APIView):
    """``GET /api/v1/saas/phase8/controlled-mutation-evidence-locks/``.

    Phase 8D read-only list of evidence locks.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase8d_locks(limit=limit)
        return Response(
            {
                "phase": "8D",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": "lock_only_cli_only",
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase8DExecutesPhase8CAgain": False,
                "phase8DRollsBackPhase8CAgain": False,
                "phase8DCallsRazorpay": False,
                "phase8DCallsMetaCloud": False,
                "phase8DCallsDelhivery": False,
                "phase8DSendsWhatsApp": False,
                "phase8DSendsCustomerNotification": False,
                "phase8DCreatesShipmentRow": False,
                "phase8DCreatesAwb": False,
                "phase8DCapturesPayment": False,
                "phase8DRefundsPayment": False,
                "phase8DMutatesOrder": False,
                "phase8DMutatesPayment": False,
                "phase8DMutatesCustomer": False,
                "phase8DMutatesLead": False,
            }
        )


class Phase8DControlledMutationEvidenceLockDetailView(APIView):
    """``GET /api/v1/saas/phase8/controlled-mutation-evidence-locks/<pk>/``.

    Phase 8D read-only lock detail.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayPaymentOrderControlledMutationEvidenceLock.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 8D controlled mutation evidence "
                        "lock not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase8d_lock(row))


class Phase8DControlledMutationEvidenceLockPreviewView(APIView):
    """``GET /api/v1/saas/phase8/controlled-mutation-evidence-lock-preview/``.

    Phase 8D read-only preview composed from a Phase 8C rolled_back
    gate id. NEVER mutates the database; NEVER calls any provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        raw = request.query_params.get("phase8c_gate_id")
        try:
            gate_id = int(raw or 0)
        except (TypeError, ValueError):
            gate_id = 0
        if gate_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase8c_gate_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            _preview_phase8d_lock(phase8c_gate_id=gate_id)
        )


class Phase8CPaymentOrderControlledMutationRollbacksView(APIView):
    """``GET /api/v1/saas/phase8/payment-order-controlled-mutation-rollbacks/<attempt_id>/``.

    Phase 8C read-only list of rollback rows for one attempt.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, attempt_id: int):
        attempt_exists = (
            RazorpayPaymentOrderControlledMutationAttempt.objects.filter(
                pk=attempt_id
            ).exists()
        )
        if not attempt_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8C payment order controlled "
                        "mutation attempt not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayPaymentOrderControlledMutationRollback.objects.filter(
                attempt_id=attempt_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8C",
                "attemptId": attempt_id,
                "items": [
                    _serialize_phase8c_rollback(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8CCallsRazorpay": False,
                "phase8CCallsMetaCloud": False,
                "phase8CCallsDelhivery": False,
                "phase8CSendsWhatsApp": False,
                "phase8CSendsCustomerNotification": False,
            }
        )


# ---------------------------------------------------------------------------
# Phase 8E - Real Customer Payment -> Order Mutation Pilot
# ---------------------------------------------------------------------------


from apps.payments.phase8e_real_customer_payment_order_pilot import (  # noqa: E402
    inspect_phase8e_real_customer_candidate_pool as _inspect_phase8e_pool,
    inspect_phase8e_real_customer_payment_order_pilot_readiness as _inspect_phase8e_readiness,
    preview_phase8e_real_customer_payment_order_pilot as _preview_phase8e_gate,
    serialize_phase8e_candidate as _serialize_phase8e_candidate,
    serialize_phase8e_dry_run as _serialize_phase8e_dry_run,
    serialize_phase8e_gate as _serialize_phase8e_gate,
    summarize_phase8e_gates as _summarize_phase8e_gates,
)
from apps.payments.models import (  # noqa: E402
    RazorpayRealCustomerPaymentOrderMutationCandidate,
    RazorpayRealCustomerPaymentOrderMutationPilotDryRun,
    RazorpayRealCustomerPaymentOrderMutationPilotGate,
)


class Phase8ERealCustomerPaymentOrderPilotReadinessView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-readiness/``.

    Phase 8E read-only readiness composition. Auth + admin only;
    POST/PATCH/DELETE return 405. NEVER mutates real ``Order`` /
    ``Payment`` / ``Customer`` / ``Lead`` / ``Shipment`` /
    ``DiscountOfferLog`` / ``WhatsAppMessage`` rows; NEVER calls
    Razorpay / Meta Cloud / Delhivery / Vapi; NEVER sends a
    customer notification; NEVER edits any ``.env*`` file.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request):
        return Response(_inspect_phase8e_readiness())


class Phase8ERealCustomerPaymentOrderPilotGatesListView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-gates/``.

    Phase 8E read-only list of pilot gates.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 25)
        except (TypeError, ValueError):
            limit = 25
        limit = max(1, min(limit, 200))
        report = _summarize_phase8e_gates(limit=limit)
        return Response(
            {
                "phase": "8E",
                "limit": limit,
                "counts": report["counts"],
                "items": report["items"],
                "executionPath": (
                    "review_dry_run_only_cli_only_no_execute"
                ),
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "apiEndpointCanApprove": False,
                "phase8ECallsRazorpay": False,
                "phase8ECallsMetaCloud": False,
                "phase8ECallsDelhivery": False,
                "phase8ECallsVapi": False,
                "phase8ESendsWhatsApp": False,
                "phase8EQueuesWhatsApp": False,
                "phase8ECreatesShipmentRow": False,
                "phase8ECreatesAwb": False,
                "phase8ECreatesPaymentLink": False,
                "phase8ECapturesPayment": False,
                "phase8ERefundsPayment": False,
                "phase8ESendsCustomerNotification": False,
                "phase8EMutatesOrder": False,
                "phase8EMutatesPayment": False,
                "phase8EMutatesCustomer": False,
                "phase8EMutatesLead": False,
                "phase8EApprovesRealCustomerAutomation": False,
            }
        )


class Phase8ERealCustomerPaymentOrderPilotGateDetailView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-gates/<pk>/``.

    Phase 8E read-only gate detail.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, pk: int):
        row = (
            RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
                pk=pk
            ).first()
        )
        if row is None:
            return Response(
                {
                    "detail": (
                        "Phase 8E real customer payment-order "
                        "pilot gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize_phase8e_gate(row))


class Phase8ERealCustomerPaymentOrderPilotPreviewView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-preview/``.

    Phase 8E read-only preview composed from a Phase 8D evidence
    lock id. NEVER mutates the database; NEVER calls any provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        raw = request.query_params.get("phase8d_lock_id")
        try:
            lock_id = int(raw or 0)
        except (TypeError, ValueError):
            lock_id = 0
        if lock_id <= 0:
            return Response(
                {
                    "detail": (
                        "phase8d_lock_id query param must be a "
                        "positive integer."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            _preview_phase8e_gate(phase8d_lock_id=lock_id)
        )


class Phase8ERealCustomerPaymentOrderPilotCandidatesView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-candidates/<gate_id>/``.

    Phase 8E read-only list of candidate rows for one pilot gate.
    Candidate serializer masks customer name / phone (last-4 only)
    and NEVER returns raw provider payload / full phone / email.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8E real customer payment-order "
                        "pilot gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayRealCustomerPaymentOrderMutationCandidate.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8E",
                "gateId": gate_id,
                "items": [
                    _serialize_phase8e_candidate(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8EMutatesOrder": False,
                "phase8EMutatesPayment": False,
                "phase8ESendsCustomerNotification": False,
            }
        )


class Phase8ERealCustomerPaymentOrderPilotDryRunsView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-dry-runs/<gate_id>/``.

    Phase 8E read-only list of dry-run records for one pilot gate.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, _request, gate_id: int):
        gate_exists = (
            RazorpayRealCustomerPaymentOrderMutationPilotGate.objects.filter(
                pk=gate_id
            ).exists()
        )
        if not gate_exists:
            return Response(
                {
                    "detail": (
                        "Phase 8E real customer payment-order "
                        "pilot gate not found."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        rows = (
            RazorpayRealCustomerPaymentOrderMutationPilotDryRun.objects.filter(
                gate_id=gate_id
            )
            .order_by("-created_at")[:200]
        )
        return Response(
            {
                "phase": "8E",
                "gateId": gate_id,
                "items": [
                    _serialize_phase8e_dry_run(r) for r in rows
                ],
                "frontendCanExecute": False,
                "apiEndpointCanExecute": False,
                "phase8EMutatesOrder": False,
                "phase8EMutatesPayment": False,
                "phase8ECallsRazorpay": False,
                "phase8ECallsMetaCloud": False,
                "phase8ECallsDelhivery": False,
                "phase8ESendsWhatsApp": False,
                "phase8ESendsCustomerNotification": False,
            }
        )


class Phase8ERealCustomerPaymentOrderPilotCandidatePoolView(APIView):
    """``GET /api/v1/saas/phase8/real-customer-payment-order-pilot-candidate-pool/``.

    Phase 8E-Hotfix-1 read-only candidate pool. Classifies every
    ``Order`` + ``Payment`` row pair currently in the system by
    Phase 8E eligibility reason (strict Pending/Pending,
    Partial/Pending review-only, or blocked-with-reason). Phones
    masked to last-4 only; raw provider payloads / customer names
    / addresses NEVER appear. Auth + admin only; POST/PATCH/DELETE
    return 405. NEVER mutates any business row; NEVER calls a
    provider.
    """

    permission_classes = [AdminSaasPermission]

    def get(self, request):
        limit_raw = request.query_params.get("limit") or "50"
        include_blocked = (
            request.query_params.get("include_blocked", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 50
        return Response(
            _inspect_phase8e_pool(
                limit=limit, include_blocked=include_blocked
            )
        )


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
    "ProviderExecutionAttemptsListView",
    "ProviderExecutionAttemptDetailView",
    "ProviderExecutionAttemptPrepareView",
    "ProviderExecutionAttemptRollbackView",
    "ProviderExecutionAttemptArchiveView",
    "RazorpayExecutionAuditReviewView",
    "RazorpayWebhookReadinessView",
    "RazorpayWebhookPlanView",
    "RazorpayWebhookHandlerReadinessView",
    "RazorpayWebhookEventsListView",
    "RazorpayWebhookEventDetailView",
    "RazorpayWebhookSimulateView",
    "RazorpayBusinessMutationSandboxPlanView",
    "RazorpayBusinessMutationSandboxReadinessView",
    "RazorpaySandboxStatusMappingReadinessView",
    "RazorpaySandboxStatusReviewsListView",
    "RazorpaySandboxStatusReviewDetailView",
    "RazorpaySandboxStatusReviewPrepareView",
    "RazorpaySandboxStatusReviewApproveView",
    "RazorpaySandboxStatusReviewRejectView",
    "RazorpaySandboxStatusReviewArchiveView",
    "RazorpaySandboxPaidStatusMutationReadinessView",
    "RazorpaySandboxPaidStatusMutationAttemptsListView",
    "RazorpaySandboxPaidStatusMutationAttemptDetailView",
    "RazorpaySandboxPaidStatusMutationPreviewView",
    "RazorpayPaymentOrderWorkflowGateReadinessView",
    "RazorpayPaymentOrderWorkflowGatesListView",
    "RazorpayPaymentOrderWorkflowGateDetailView",
    "RazorpayPaymentOrderWorkflowGatePreviewView",
    "RazorpayPaymentDispatchReadinessView",
    "RazorpayPaymentDispatchReadinessGatesListView",
    "RazorpayPaymentDispatchReadinessGateDetailView",
    "RazorpayPaymentDispatchReadinessPreviewView",
    "RazorpayPaymentDispatchPilotPlanReadinessView",
    "RazorpayPaymentDispatchPilotPlansListView",
    "RazorpayPaymentDispatchPilotPlanDetailView",
    "RazorpayPaymentDispatchPilotPlanPreviewView",
    "RazorpayPhase6FinalAuditLockReadinessView",
    "RazorpayPhase6FinalAuditLocksListView",
    "RazorpayPhase6FinalAuditLockDetailView",
    "RazorpayPhase6FinalAuditLockPreviewView",
    "RazorpayControlledPilotGateReadinessView",
    "RazorpayControlledPilotGatesListView",
    "RazorpayControlledPilotGateDetailView",
    "RazorpayControlledPilotGatePreviewView",
    "RazorpayControlledPilotGateDryRunsView",
    "RazorpayControlledPilotGateRollbackDryRunsView",
    "RazorpayControlledPilotExecutionReadinessView",
    "RazorpayControlledPilotExecutionAttemptsListView",
    "RazorpayControlledPilotExecutionAttemptDetailView",
    "RazorpayControlledPilotExecutionPreviewView",
    "RazorpayControlledPilotExecutionRollbacksView",
    "RazorpayWhatsAppInternalNotificationReadinessView",
    "RazorpayWhatsAppInternalNotificationGatesListView",
    "RazorpayWhatsAppInternalNotificationGateDetailView",
    "RazorpayWhatsAppInternalNotificationPreviewView",
    "RazorpayWhatsAppInternalNotificationDryRunsView",
    "RazorpayCourierReadinessReadinessView",
    "RazorpayCourierReadinessGatesListView",
    "RazorpayCourierReadinessGateDetailView",
    "RazorpayCourierReadinessPreviewView",
    "RazorpayCourierReadinessDryRunsView",
    "RazorpayCourierExecutionReadinessView",
    "RazorpayCourierExecutionAttemptsListView",
    "RazorpayCourierExecutionAttemptDetailView",
    "RazorpayCourierExecutionPreviewView",
    "RazorpayCourierExecutionRollbacksView",
    "RazorpayCourierExecutionEvidenceLockReadinessView",
    "RazorpayCourierExecutionEvidenceLocksListView",
    "RazorpayCourierExecutionEvidenceLockDetailView",
    "RazorpayCourierExecutionEvidenceLockPreviewView",
    "WhatsAppInternalSendReadinessView",
    "WhatsAppInternalSendAttemptsListView",
    "WhatsAppInternalSendAttemptDetailView",
    "WhatsAppInternalSendPreviewView",
    "Phase7IFinalAuditLockReadinessView",
    "Phase7IFinalAuditLocksListView",
    "Phase7IFinalAuditLockDetailView",
    "Phase7IFinalAuditLockPreviewView",
    "Phase8APaymentOrderMutationSandboxReadinessView",
    "Phase8APaymentOrderMutationSandboxGatesListView",
    "Phase8APaymentOrderMutationSandboxGateDetailView",
    "Phase8APaymentOrderMutationSandboxPreviewView",
    "Phase8APaymentOrderMutationSandboxDryRunsView",
    "Phase8BPaymentOrderMutationReviewReadinessView",
    "Phase8BPaymentOrderMutationReviewGatesListView",
    "Phase8BPaymentOrderMutationReviewGateDetailView",
    "Phase8BPaymentOrderMutationReviewPreviewView",
    "Phase8BPaymentOrderMutationReviewDryRunsView",
    "Phase8CPaymentOrderControlledMutationReadinessView",
    "Phase8CPaymentOrderControlledMutationGatesListView",
    "Phase8CPaymentOrderControlledMutationGateDetailView",
    "Phase8CPaymentOrderControlledMutationPreviewView",
    "Phase8CPaymentOrderControlledMutationAttemptsView",
    "Phase8CPaymentOrderControlledMutationRollbacksView",
    "Phase8DControlledMutationEvidenceLockReadinessView",
    "Phase8DControlledMutationEvidenceLocksListView",
    "Phase8DControlledMutationEvidenceLockDetailView",
    "Phase8DControlledMutationEvidenceLockPreviewView",
    "Phase8ERealCustomerPaymentOrderPilotReadinessView",
    "Phase8ERealCustomerPaymentOrderPilotGatesListView",
    "Phase8ERealCustomerPaymentOrderPilotGateDetailView",
    "Phase8ERealCustomerPaymentOrderPilotPreviewView",
    "Phase8ERealCustomerPaymentOrderPilotCandidatesView",
    "Phase8ERealCustomerPaymentOrderPilotDryRunsView",
    "Phase8ERealCustomerPaymentOrderPilotCandidatePoolView",
)
