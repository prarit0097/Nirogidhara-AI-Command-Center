"""Phase 6H live execution gate policy registry.

This module is pure policy data. It does not call provider APIs, does
not inspect raw secrets, and does not mutate business data. The live
gate service consumes this registry to decide whether a future external
side effect is blocked, needs approval, or is audit-ready only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .runtime_operations import get_runtime_operation_definition


POLICY_VERSION = "phase6h.v1"


@dataclass(frozen=True)
class LiveGateOperationPolicy:
    operation_type: str
    provider_type: str
    risk_level: str
    live_allowed_by_default: bool = False
    approval_required: bool = True
    caio_review_required: bool = False
    consent_required: bool = False
    claim_vault_required: bool = False
    webhook_required: bool = False
    idempotency_required: bool = True
    audit_required: bool = True
    kill_switch_can_block: bool = True
    allowed_in_phase_6h: bool = False
    next_phase_for_live_test: str = (
        "phase_6i_single_internal_live_gate_simulation"
    )
    template_approval_required: bool = False
    payment_approval_required: bool = False
    customer_intent_required: bool = False
    address_validation_required: bool = False
    provider_deferred: bool = False
    human_approval_required: bool = False
    required_env_keys: tuple[str, ...] = ()
    required_config_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operationType": self.operation_type,
            "providerType": self.provider_type,
            "riskLevel": self.risk_level,
            "liveAllowedByDefault": self.live_allowed_by_default,
            "approvalRequired": self.approval_required,
            "caioReviewRequired": self.caio_review_required,
            "consentRequired": self.consent_required,
            "claimVaultRequired": self.claim_vault_required,
            "webhookRequired": self.webhook_required,
            "idempotencyRequired": self.idempotency_required,
            "auditRequired": self.audit_required,
            "killSwitchCanBlock": self.kill_switch_can_block,
            "allowedInPhase6H": self.allowed_in_phase_6h,
            "nextPhaseForLiveTest": self.next_phase_for_live_test,
            "templateApprovalRequired": self.template_approval_required,
            "paymentApprovalRequired": self.payment_approval_required,
            "customerIntentRequired": self.customer_intent_required,
            "addressValidationRequired": self.address_validation_required,
            "providerDeferred": self.provider_deferred,
            "humanApprovalRequired": self.human_approval_required,
            "requiredEnvKeys": list(self.required_env_keys),
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


LIVE_GATE_OPERATIONS: tuple[LiveGateOperationPolicy, ...] = (
    LiveGateOperationPolicy(
        operation_type="whatsapp.send_text",
        provider_type="whatsapp_meta",
        risk_level="high",
        consent_required=True,
        claim_vault_required=True,
        caio_review_required=True,
        required_env_keys=_runtime_env_keys("whatsapp.send_text"),
        required_config_keys=_runtime_config_keys("whatsapp.send_text"),
        metadata={
            "rule": (
                "Product or health content must be Claim Vault grounded "
                "and pass CAIO safety before any future send."
            )
        },
    ),
    LiveGateOperationPolicy(
        operation_type="whatsapp.send_template",
        provider_type="whatsapp_meta",
        risk_level="high",
        consent_required=True,
        template_approval_required=True,
        required_env_keys=_runtime_env_keys("whatsapp.send_template"),
        required_config_keys=_runtime_config_keys("whatsapp.send_template"),
    ),
    LiveGateOperationPolicy(
        operation_type="razorpay.create_order",
        provider_type="razorpay",
        risk_level="medium",
        payment_approval_required=True,
        webhook_required=True,
        required_env_keys=_runtime_env_keys("razorpay.create_order"),
        required_config_keys=_runtime_config_keys("razorpay.create_order"),
    ),
    LiveGateOperationPolicy(
        operation_type="razorpay.create_payment_link",
        provider_type="razorpay",
        risk_level="high",
        payment_approval_required=True,
        customer_intent_required=True,
        webhook_required=True,
        required_env_keys=_runtime_env_keys("razorpay.create_payment_link"),
        required_config_keys=_runtime_config_keys(
            "razorpay.create_payment_link"
        ),
    ),
    LiveGateOperationPolicy(
        operation_type="payu.create_payment",
        provider_type="payu",
        risk_level="medium",
        payment_approval_required=True,
        provider_deferred=True,
        next_phase_for_live_test="deferred_until_payu_credentials_available",
        required_env_keys=_runtime_env_keys("payu.create_payment"),
    ),
    LiveGateOperationPolicy(
        operation_type="delhivery.create_shipment",
        provider_type="delhivery",
        risk_level="high",
        address_validation_required=True,
        webhook_required=True,
        provider_deferred=True,
        next_phase_for_live_test=(
            "deferred_until_delhivery_credentials_available"
        ),
        required_env_keys=_runtime_env_keys("delhivery.create_shipment"),
    ),
    LiveGateOperationPolicy(
        operation_type="vapi.place_call",
        provider_type="vapi",
        risk_level="critical",
        consent_required=True,
        webhook_required=True,
        next_phase_for_live_test=(
            "phase_6i_after_vapi_phone_id_and_webhook_secret"
        ),
        required_env_keys=_runtime_env_keys("vapi.place_call"),
    ),
    LiveGateOperationPolicy(
        operation_type="ai.customer_hinglish_chat",
        provider_type="openai",
        risk_level="critical",
        approval_required=True,
        caio_review_required=True,
        claim_vault_required=True,
        human_approval_required=True,
        required_env_keys=_runtime_env_keys("ai.customer_hinglish_chat"),
        required_config_keys=_runtime_config_keys("ai.customer_hinglish_chat"),
        metadata={
            "providerNote": "NVIDIA primary, OpenAI fallback; no live send."
        },
    ),
    LiveGateOperationPolicy(
        operation_type="ai.caio_compliance",
        provider_type="openai",
        risk_level="medium",
        caio_review_required=True,
        required_env_keys=_runtime_env_keys("ai.caio_compliance"),
        required_config_keys=_runtime_config_keys("ai.caio_compliance"),
        metadata={"providerNote": "NVIDIA primary; internal review output."},
    ),
    LiveGateOperationPolicy(
        operation_type="ai.ceo_planning",
        provider_type="openai",
        risk_level="medium",
        required_env_keys=_runtime_env_keys("ai.ceo_planning"),
        required_config_keys=_runtime_config_keys("ai.ceo_planning"),
    ),
    LiveGateOperationPolicy(
        operation_type="ai.reports_summary",
        provider_type="openai",
        risk_level="low",
        required_env_keys=_runtime_env_keys("ai.reports_summary"),
        required_config_keys=_runtime_config_keys("ai.reports_summary"),
    ),
    LiveGateOperationPolicy(
        operation_type="ai.critical_fallback",
        provider_type="openai",
        risk_level="high",
        required_env_keys=_runtime_env_keys("ai.critical_fallback"),
    ),
    LiveGateOperationPolicy(
        operation_type="ai.smoke_test",
        provider_type="nvidia",
        risk_level="low",
        next_phase_for_live_test="phase_6i_single_internal_live_gate_simulation",
        metadata={
            "providerNote": (
                "Phase 6I simulation only; no NVIDIA/OpenAI request is made."
            )
        },
    ),
)


_REGISTRY = {
    policy.operation_type: policy for policy in LIVE_GATE_OPERATIONS
}


def list_live_gate_policies() -> tuple[LiveGateOperationPolicy, ...]:
    return LIVE_GATE_OPERATIONS


def get_live_gate_policy(
    operation_type: str,
) -> Optional[LiveGateOperationPolicy]:
    return _REGISTRY.get(operation_type or "")


__all__ = (
    "POLICY_VERSION",
    "LiveGateOperationPolicy",
    "LIVE_GATE_OPERATIONS",
    "list_live_gate_policies",
    "get_live_gate_policy",
)
