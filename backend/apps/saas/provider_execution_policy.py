"""Phase 6K — Single Internal Razorpay Test-Mode Execution Gate policy.

Pure policy data. The execution service consumes this registry to
decide whether a future provider call may go out at all. Phase 6K's
ONLY allowed execution target is :data:`PHASE_6K_ALLOWED_OPERATION`
(``razorpay.create_order``) in test mode against a Razorpay TEST key
(``rzp_test_...``) with a synthetic ₹1.00 (100 paise) payload.

LOCKED rules in Phase 6K:

- ``allowedInPhase6K`` is ``True`` only for ``razorpay.create_order``.
- ``provider_environment`` must be ``test``.
- ``amount_paise`` is locked to 100; ``currency`` is locked to INR.
- ``real_money`` is ``False`` and ``real_customer_data_allowed`` is
  ``False``.
- ``approved_provider_test_plan_required`` is ``True`` (Phase 6J
  approval is a hard gate).
- ``idempotency_required`` is ``True``.
- ``explicit_cli_confirmation_required`` is ``True``.
- ``env_flag_required`` is ``True`` —
  ``PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED`` must be ``true``.
- ``api_execution_allowed`` is ``False`` — the actual provider call
  is CLI-only in Phase 6K.
- ``frontend_execution_allowed`` is ``False`` — the SaaS Admin Panel
  shows execution status only; never an "Execute" button.
- ``max_executions_per_approved_plan`` is ``1``.
- ``safe_response_summary_only`` is ``True``.
- ``business_mutation_allowed`` / ``payment_link_creation_allowed`` /
  ``capture_allowed`` / ``customer_notification_allowed`` are all
  ``False``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


POLICY_VERSION = "phase6k.v1"

# Phase 6K env flag — must be ``true`` (case-insensitive) before any
# Razorpay call may dispatch.
PHASE_6K_ENV_FLAG = "PHASE6K_RAZORPAY_TEST_EXECUTION_ENABLED"

# Phase 6K only allows ONE execution target.
PHASE_6K_ALLOWED_OPERATION = "razorpay.create_order"

# Razorpay test key prefix. Anything not starting with this is rejected.
RAZORPAY_TEST_KEY_PREFIX = "rzp_test"
RAZORPAY_LIVE_KEY_PREFIX = "rzp_live"


@dataclass(frozen=True)
class ProviderExecutionPolicy:
    """Static policy for one Phase 6K execution operation."""

    operation_type: str
    provider_type: str
    provider_environment: str = "test"
    allowed_in_phase_6k: bool = False
    amount_paise: int = 100
    currency: str = "INR"
    real_money: bool = False
    real_customer_data_allowed: bool = False
    synthetic_payload_required: bool = True
    approved_provider_test_plan_required: bool = True
    idempotency_required: bool = True
    explicit_cli_confirmation_required: bool = True
    env_flag_required: bool = True
    env_flag_name: str = PHASE_6K_ENV_FLAG
    api_execution_allowed: bool = False
    frontend_execution_allowed: bool = False
    max_executions_per_approved_plan: int = 1
    safe_response_summary_only: bool = True
    business_mutation_allowed: bool = False
    payment_link_creation_allowed: bool = False
    capture_allowed: bool = False
    customer_notification_allowed: bool = False
    required_env_keys: tuple[str, ...] = ()
    next_phase_after_success: str = (
        "phase_6l_razorpay_test_execution_audit_review_and_webhook_readiness"
    )
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operationType": self.operation_type,
            "providerType": self.provider_type,
            "providerEnvironment": self.provider_environment,
            "allowedInPhase6K": self.allowed_in_phase_6k,
            "amountPaise": self.amount_paise,
            "currency": self.currency,
            "realMoney": self.real_money,
            "realCustomerDataAllowed": self.real_customer_data_allowed,
            "syntheticPayloadRequired": self.synthetic_payload_required,
            "approvedProviderTestPlanRequired": (
                self.approved_provider_test_plan_required
            ),
            "idempotencyRequired": self.idempotency_required,
            "explicitCliConfirmationRequired": (
                self.explicit_cli_confirmation_required
            ),
            "envFlagRequired": self.env_flag_required,
            "envFlagName": self.env_flag_name,
            "apiExecutionAllowed": self.api_execution_allowed,
            "frontendExecutionAllowed": self.frontend_execution_allowed,
            "maxExecutionsPerApprovedPlan": (
                self.max_executions_per_approved_plan
            ),
            "safeResponseSummaryOnly": self.safe_response_summary_only,
            "businessMutationAllowed": self.business_mutation_allowed,
            "paymentLinkCreationAllowed": (
                self.payment_link_creation_allowed
            ),
            "captureAllowed": self.capture_allowed,
            "customerNotificationAllowed": (
                self.customer_notification_allowed
            ),
            "requiredEnvKeys": list(self.required_env_keys),
            "nextPhaseAfterSuccess": self.next_phase_after_success,
            "notes": self.notes,
            "policyVersion": POLICY_VERSION,
            "metadata": dict(self.metadata),
        }


PROVIDER_EXECUTION_POLICIES: tuple[ProviderExecutionPolicy, ...] = (
    ProviderExecutionPolicy(
        operation_type="razorpay.create_order",
        provider_type="razorpay",
        provider_environment="test",
        allowed_in_phase_6k=True,
        required_env_keys=(
            PHASE_6K_ENV_FLAG,
            "RAZORPAY_KEY_ID",
            "RAZORPAY_KEY_SECRET",
        ),
        notes=(
            "Razorpay test-mode create_order is the ONLY Phase 6K "
            "execution target. Synthetic ₹1.00 payload, no customer "
            "data, no payment link, no capture, no business mutation."
        ),
        metadata={
            "rule": (
                "Key id must start with 'rzp_test'. amount_paise must "
                "equal 100. Plan must be approved_for_future_execution. "
                "Only one successful execution per approved plan."
            )
        },
    ),
)


_REGISTRY: dict[str, ProviderExecutionPolicy] = {
    p.operation_type: p for p in PROVIDER_EXECUTION_POLICIES
}


def list_provider_execution_policies() -> tuple[ProviderExecutionPolicy, ...]:
    return PROVIDER_EXECUTION_POLICIES


def get_provider_execution_policy(
    operation_type: str,
) -> Optional[ProviderExecutionPolicy]:
    return _REGISTRY.get(operation_type or "")


def is_phase_6k_allowed_operation(operation_type: str) -> bool:
    return (operation_type or "") == PHASE_6K_ALLOWED_OPERATION


__all__ = (
    "POLICY_VERSION",
    "PHASE_6K_ENV_FLAG",
    "PHASE_6K_ALLOWED_OPERATION",
    "RAZORPAY_TEST_KEY_PREFIX",
    "RAZORPAY_LIVE_KEY_PREFIX",
    "ProviderExecutionPolicy",
    "PROVIDER_EXECUTION_POLICIES",
    "list_provider_execution_policies",
    "get_provider_execution_policy",
    "is_phase_6k_allowed_operation",
)
