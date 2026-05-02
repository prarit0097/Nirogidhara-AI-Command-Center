"""Phase 6J — Single Internal Provider Test Plan policy registry.

Pure policy data. The policy registry tells the
:mod:`apps.saas.provider_test_plan` service what the rules of a
provider test plan are — what env keys must be present, what max
test amount is allowed, whether real money / real customer data is
allowed, and whether the operation can run live in this phase.

LOCKED rules in Phase 6J:

- ``providerCallAllowedInPhase6J`` is ``False`` for every operation.
- ``externalProviderCallAllowedInPhase6J`` is ``False`` for every
  operation.
- ``realMoney`` is ``False`` for every operation.
- ``realCustomerDataAllowed`` is ``False`` for every operation.
- ``approvalRequired`` is ``True``.
- ``liveGateRequired`` is ``True``.
- ``killSwitchMustRemainEnabled`` is ``True``.
- ``idempotencyRequired`` is ``True``.
- ``rollbackRequired`` is ``True``.
- ``auditRequired`` is ``True``.
- ``nextPhaseForExecution`` points at Phase 6K.

The policy module never reads provider credentials or contacts a
provider API. The Phase 6J rule is: planning only, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .runtime_operations import get_runtime_operation_definition


POLICY_VERSION = "phase6j.v1"


# Phase 6J implementation target — only this operation has a working
# `prepare → validate → approve → archive` pipeline. The other
# entries below sit in the registry as placeholders so the test plan
# service can refuse them with a typed nextAction.
PHASE_6J_IMPLEMENTATION_TARGETS: tuple[str, ...] = (
    "razorpay.create_order",
)


@dataclass(frozen=True)
class ProviderTestPlanPolicy:
    """Static policy for one provider test plan operation."""

    operation_type: str
    provider_type: str
    provider_environment: str = "test"
    real_money: bool = False
    real_customer_data_allowed: bool = False
    external_provider_call_allowed_in_phase_6j: bool = False
    provider_call_allowed: bool = False
    approval_required: bool = True
    live_gate_required: bool = True
    kill_switch_must_remain_enabled: bool = True
    idempotency_required: bool = True
    webhook_required_for_future_execution: bool = False
    synthetic_payload_required: bool = True
    safe_amount_only: bool = True
    max_test_amount_paise: int = 100
    currency: str = "INR"
    next_phase_for_execution: str = (
        "phase_6k_single_internal_razorpay_test_mode_execution_gate"
    )
    rollback_required: bool = True
    audit_required: bool = True
    implementation_target_in_phase_6j: bool = False
    notes: str = ""
    required_env_keys: tuple[str, ...] = ()
    optional_env_keys: tuple[str, ...] = ()
    required_config_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operationType": self.operation_type,
            "providerType": self.provider_type,
            "providerEnvironment": self.provider_environment,
            "realMoney": self.real_money,
            "realCustomerDataAllowed": self.real_customer_data_allowed,
            "externalProviderCallAllowedInPhase6J": (
                self.external_provider_call_allowed_in_phase_6j
            ),
            "providerCallAllowed": self.provider_call_allowed,
            "approvalRequired": self.approval_required,
            "liveGateRequired": self.live_gate_required,
            "killSwitchMustRemainEnabled": (
                self.kill_switch_must_remain_enabled
            ),
            "idempotencyRequired": self.idempotency_required,
            "webhookRequiredForFutureExecution": (
                self.webhook_required_for_future_execution
            ),
            "syntheticPayloadRequired": self.synthetic_payload_required,
            "safeAmountOnly": self.safe_amount_only,
            "maxTestAmountPaise": self.max_test_amount_paise,
            "currency": self.currency,
            "nextPhaseForExecution": self.next_phase_for_execution,
            "rollbackRequired": self.rollback_required,
            "auditRequired": self.audit_required,
            "implementationTargetInPhase6J": (
                self.implementation_target_in_phase_6j
            ),
            "notes": self.notes,
            "requiredEnvKeys": list(self.required_env_keys),
            "optionalEnvKeys": list(self.optional_env_keys),
            "requiredConfigKeys": list(self.required_config_keys),
            "policyVersion": POLICY_VERSION,
            "metadata": dict(self.metadata),
        }


def _runtime_env_keys(operation_type: str) -> tuple[str, ...]:
    definition = get_runtime_operation_definition(operation_type)
    return definition.required_env_keys if definition is not None else ()


def _runtime_config_keys(operation_type: str) -> tuple[str, ...]:
    definition = get_runtime_operation_definition(operation_type)
    return definition.required_config_keys if definition is not None else ()


PROVIDER_TEST_PLAN_POLICIES: tuple[ProviderTestPlanPolicy, ...] = (
    # --- Phase 6J implementation target -------------------------------
    ProviderTestPlanPolicy(
        operation_type="razorpay.create_order",
        provider_type="razorpay",
        provider_environment="test",
        webhook_required_for_future_execution=True,
        max_test_amount_paise=100,
        currency="INR",
        implementation_target_in_phase_6j=True,
        notes=(
            "Razorpay test-mode create_order is the Phase 6J target. "
            "Phase 6J only prepares + validates the plan; no Razorpay "
            "API call is made."
        ),
        required_env_keys=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"),
        optional_env_keys=("RAZORPAY_WEBHOOK_SECRET",),
        required_config_keys=_runtime_config_keys("razorpay.create_order"),
        metadata={
            "rule": (
                "amount_paise must be <= max_test_amount_paise; payload "
                "carries no real customer PII; idempotency key is "
                "mandatory."
            )
        },
    ),
    # --- Other providers in the registry (placeholder, refused) -------
    ProviderTestPlanPolicy(
        operation_type="razorpay.create_payment_link",
        provider_type="razorpay",
        provider_environment="test",
        webhook_required_for_future_execution=True,
        max_test_amount_paise=100,
        currency="INR",
        notes="Available in a later phase.",
        required_env_keys=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"),
        optional_env_keys=("RAZORPAY_WEBHOOK_SECRET",),
        required_config_keys=_runtime_config_keys(
            "razorpay.create_payment_link"
        ),
    ),
    ProviderTestPlanPolicy(
        operation_type="whatsapp.send_text",
        provider_type="whatsapp_meta",
        provider_environment="test",
        max_test_amount_paise=0,
        currency="",
        notes=(
            "WhatsApp send_text plan stays parked behind consent + "
            "Claim Vault + CAIO until a later phase."
        ),
        required_env_keys=_runtime_env_keys("whatsapp.send_text"),
    ),
    ProviderTestPlanPolicy(
        operation_type="ai.smoke_test",
        provider_type="openai",
        provider_environment="test",
        max_test_amount_paise=0,
        currency="",
        notes=(
            "AI smoke test routes through the existing Phase 6G "
            "smoke_test_ai_provider_routes operator command, not the "
            "Phase 6J planner."
        ),
        required_env_keys=("NVIDIA_API_KEY",),
    ),
    ProviderTestPlanPolicy(
        operation_type="vapi.place_call",
        provider_type="vapi",
        provider_environment="test",
        max_test_amount_paise=0,
        currency="",
        webhook_required_for_future_execution=True,
        notes=(
            "Vapi awaits phone_number_id and webhook_secret env vars "
            "before any test plan can mature past placeholder."
        ),
        required_env_keys=_runtime_env_keys("vapi.place_call"),
    ),
    ProviderTestPlanPolicy(
        operation_type="delhivery.create_shipment",
        provider_type="delhivery",
        provider_environment="test",
        max_test_amount_paise=0,
        currency="",
        webhook_required_for_future_execution=True,
        notes="Deferred — Delhivery credentials not provisioned.",
        required_env_keys=_runtime_env_keys("delhivery.create_shipment"),
    ),
    ProviderTestPlanPolicy(
        operation_type="payu.create_payment",
        provider_type="payu",
        provider_environment="test",
        max_test_amount_paise=0,
        currency="",
        webhook_required_for_future_execution=True,
        notes="Deferred — PayU credentials not provisioned.",
        required_env_keys=_runtime_env_keys("payu.create_payment"),
    ),
)


_REGISTRY: dict[str, ProviderTestPlanPolicy] = {
    policy.operation_type: policy
    for policy in PROVIDER_TEST_PLAN_POLICIES
}


def list_provider_test_plan_policies() -> tuple[ProviderTestPlanPolicy, ...]:
    return PROVIDER_TEST_PLAN_POLICIES


def get_provider_test_plan_policy(
    operation_type: str,
) -> Optional[ProviderTestPlanPolicy]:
    return _REGISTRY.get(operation_type or "")


def is_phase_6j_implementation_target(operation_type: str) -> bool:
    return (operation_type or "") in PHASE_6J_IMPLEMENTATION_TARGETS


__all__ = (
    "POLICY_VERSION",
    "PHASE_6J_IMPLEMENTATION_TARGETS",
    "ProviderTestPlanPolicy",
    "PROVIDER_TEST_PLAN_POLICIES",
    "list_provider_test_plan_policies",
    "get_provider_test_plan_policy",
    "is_phase_6j_implementation_target",
)
