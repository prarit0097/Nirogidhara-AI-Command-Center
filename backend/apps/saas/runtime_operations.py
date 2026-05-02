"""Phase 6G — Operation taxonomy for controlled runtime routing dry-run.

Single source of truth for the operations the runtime dry-run engine
can preview. No external calls; no business-data mutation; no live
provider activation in this phase.

LOCKED rules:

- Every operation declares ``dryRunAllowed=True`` and
  ``liveAllowedInPhase6G=False``.
- ``providerType`` maps to the existing
  :class:`apps.saas.models.OrganizationIntegrationSetting.ProviderType`
  enum so the Phase 6F readiness selectors can resolve config.
- ``required_env_keys`` lists env-var names the live runtime would
  consult; the dry-run only checks PRESENCE (boolean) — never reads
  the value.
- ``required_secret_refs`` is the set of friendly secret-ref keys
  expected on a per-org ``OrganizationIntegrationSetting``; the
  Phase 6F masker handles the actual rendering.
- ``side_effect_risk`` ∈ {"none", "low", "medium", "high"} — Phase 6G
  blocks every ``high`` operation from running live.
- ``next_phase_for_live_execution`` documents WHEN the operation can
  earn live status. Phase 6H is the earliest open slot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class RuntimeOperationDefinition:
    """Static metadata for a runtime-eligible operation."""

    operation_type: str
    provider_type: str
    side_effect_risk: str = "high"
    dry_run_allowed: bool = True
    live_allowed_in_phase_6g: bool = False
    required_org: bool = True
    required_secret_refs: tuple[str, ...] = ()
    required_env_keys: tuple[str, ...] = ()
    required_config_keys: tuple[str, ...] = ()
    readiness_notes: str = ""
    next_phase_for_live_execution: str = (
        "phase_6h_controlled_live_execution_audit"
    )

    def to_dict(self) -> dict:
        return {
            "operationType": self.operation_type,
            "providerType": self.provider_type,
            "sideEffectRisk": self.side_effect_risk,
            "dryRunAllowed": self.dry_run_allowed,
            "liveAllowedInPhase6G": self.live_allowed_in_phase_6g,
            "requiredOrg": self.required_org,
            "requiredSecretRefs": list(self.required_secret_refs),
            "requiredEnvKeys": list(self.required_env_keys),
            "requiredConfigKeys": list(self.required_config_keys),
            "readinessNotes": self.readiness_notes,
            "nextPhaseForLiveExecution": self.next_phase_for_live_execution,
        }


# Provider type aliases that match the
# ``OrganizationIntegrationSetting.ProviderType`` enum values.
_PROVIDER_WHATSAPP = "whatsapp_meta"
_PROVIDER_RAZORPAY = "razorpay"
_PROVIDER_PAYU = "payu"
_PROVIDER_DELHIVERY = "delhivery"
_PROVIDER_VAPI = "vapi"
_PROVIDER_OPENAI = "openai"


# Phase 6G operation registry. Order is the canonical render order in
# the SaaS Admin "Controlled Runtime Routing Dry Run" table.
RUNTIME_OPERATIONS: tuple[RuntimeOperationDefinition, ...] = (
    # WhatsApp ----------------------------------------------------------
    RuntimeOperationDefinition(
        operation_type="whatsapp.send_text",
        provider_type=_PROVIDER_WHATSAPP,
        side_effect_risk="high",
        required_secret_refs=(
            "access_token",
            "app_secret",
            "verify_token",
        ),
        required_env_keys=(
            "META_WA_ACCESS_TOKEN",
            "META_WA_PHONE_NUMBER_ID",
            "META_WA_BUSINESS_ACCOUNT_ID",
            "META_WA_VERIFY_TOKEN",
            "META_WA_APP_SECRET",
        ),
        required_config_keys=(
            "phone_number_id_env_var",
            "business_account_id_env_var",
        ),
        readiness_notes=(
            "Limited test mode + allow-list final-send guard remain "
            "in force for any future live phase. Customer-facing "
            "drafts must pass the Claim Vault + safety stack."
        ),
        next_phase_for_live_execution=(
            "phase_6h_controlled_live_execution_audit"
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="whatsapp.send_template",
        provider_type=_PROVIDER_WHATSAPP,
        side_effect_risk="high",
        required_secret_refs=(
            "access_token",
            "app_secret",
            "verify_token",
        ),
        required_env_keys=(
            "META_WA_ACCESS_TOKEN",
            "META_WA_PHONE_NUMBER_ID",
            "META_WA_BUSINESS_ACCOUNT_ID",
            "META_WA_VERIFY_TOKEN",
            "META_WA_APP_SECRET",
        ),
        required_config_keys=(
            "phone_number_id_env_var",
        ),
        readiness_notes=(
            "Approved Meta template + consent + Claim Vault still "
            "enforced before any live send."
        ),
    ),
    # Razorpay ----------------------------------------------------------
    RuntimeOperationDefinition(
        operation_type="razorpay.create_order",
        provider_type=_PROVIDER_RAZORPAY,
        side_effect_risk="high",
        required_secret_refs=("key_secret",),
        required_env_keys=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"),
        required_config_keys=("key_id_env_var",),
        readiness_notes=(
            "Razorpay test-mode credentials are present in env. "
            "Phase 6G only previews the request shape — no order "
            "is created."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="razorpay.create_payment_link",
        provider_type=_PROVIDER_RAZORPAY,
        side_effect_risk="high",
        required_secret_refs=("key_secret",),
        required_env_keys=("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"),
        required_config_keys=("key_id_env_var",),
        readiness_notes=(
            "₹499 advance payment link generation lives here in Phase "
            "6H+. Phase 6G previews request shape only."
        ),
    ),
    # PayU --------------------------------------------------------------
    RuntimeOperationDefinition(
        operation_type="payu.create_payment",
        provider_type=_PROVIDER_PAYU,
        side_effect_risk="high",
        required_secret_refs=("merchant_key", "salt"),
        required_env_keys=("PAYU_KEY", "PAYU_SECRET"),
        required_config_keys=(),
        readiness_notes=(
            "Deferred. PayU is not part of the active rollout — "
            "this row is preview-only and will surface a "
            "deferred-provider warning until env values are added."
        ),
        next_phase_for_live_execution=(
            "deferred_until_payu_credentials_available"
        ),
    ),
    # Delhivery ---------------------------------------------------------
    RuntimeOperationDefinition(
        operation_type="delhivery.create_shipment",
        provider_type=_PROVIDER_DELHIVERY,
        side_effect_risk="high",
        required_secret_refs=("api_token",),
        required_env_keys=("DELHIVERY_API_TOKEN",),
        required_config_keys=(),
        readiness_notes=(
            "Deferred. Delhivery integration will be wired after "
            "credentials are provisioned."
        ),
        next_phase_for_live_execution=(
            "deferred_until_delhivery_credentials_available"
        ),
    ),
    # Vapi --------------------------------------------------------------
    RuntimeOperationDefinition(
        operation_type="vapi.place_call",
        provider_type=_PROVIDER_VAPI,
        side_effect_risk="high",
        required_secret_refs=("api_key",),
        required_env_keys=(
            "VAPI_API_KEY",
            "VAPI_PHONE_NUMBER_ID",
            "VAPI_WEBHOOK_SECRET",
        ),
        required_config_keys=(),
        readiness_notes=(
            "Vapi credentials are partially configured (api_key "
            "present); phone_number_id and webhook_secret env vars "
            "are still missing. Live call placement remains "
            "blocked behind WHATSAPP_CALL_HANDOFF_ENABLED + Vapi "
            "credentials."
        ),
        next_phase_for_live_execution=(
            "phase_6h_after_vapi_phone_id_and_webhook_secret_added"
        ),
    ),
    # OpenAI agent completion ------------------------------------------
    RuntimeOperationDefinition(
        operation_type="openai.agent_completion",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="low",
        required_secret_refs=("api_key",),
        required_env_keys=("OPENAI_API_KEY",),
        required_config_keys=(),
        readiness_notes=(
            "Phase 6G previews routing only; the AI provider router "
            "module owns the actual NVIDIA/OpenAI/Anthropic "
            "selection. No customer-facing reply is dispatched."
        ),
    ),
    # AI tasks (managed by ai_runtime_preview) -------------------------
    RuntimeOperationDefinition(
        operation_type="ai.reports_summary",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="none",
        required_secret_refs=("api_key",),
        required_env_keys=(
            "NVIDIA_API_KEY",
            "NVIDIA_API_BASE_URL",
            "AI_MAX_TOKENS_REPORTS",
        ),
        required_config_keys=("NVIDIA_MODEL_REPORTS_SUMMARIES",),
        readiness_notes=(
            "NVIDIA MiniMax-M2.7 is the primary model. Reports are "
            "internal — no customer messaging side effect."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="ai.ceo_planning",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="none",
        required_secret_refs=("api_key",),
        required_env_keys=(
            "NVIDIA_API_KEY",
            "NVIDIA_API_BASE_URL",
            "AI_MAX_TOKENS_CEO",
        ),
        required_config_keys=("NVIDIA_MODEL_CEO_PLANNING",),
        readiness_notes=(
            "NVIDIA Kimi-K2.6 powers CEO briefings. Output is "
            "consumed internally by the governance UI."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="ai.caio_compliance",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="none",
        required_secret_refs=("api_key",),
        required_env_keys=(
            "NVIDIA_API_KEY",
            "NVIDIA_API_BASE_URL",
            "AI_MAX_TOKENS_COMPLIANCE",
        ),
        required_config_keys=("NVIDIA_MODEL_CAIO_COMPLIANCE",),
        readiness_notes=(
            "NVIDIA Mistral Medium 3.5. Compliance reasoning + "
            "human-review fallback for low-confidence findings."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="ai.customer_hinglish_chat",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="medium",
        required_secret_refs=("api_key",),
        required_env_keys=(
            "NVIDIA_API_KEY",
            "NVIDIA_API_BASE_URL",
            "AI_MAX_TOKENS_CUSTOMER_CHAT",
        ),
        required_config_keys=("NVIDIA_MODEL_HINGLISH_CHAT",),
        readiness_notes=(
            "NVIDIA Gemma-4-31B-IT. Customer-facing drafts must "
            "still pass through the Claim Vault, blocked phrase "
            "filter, safety stack, and approval matrix before any "
            "live send."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="ai.critical_fallback",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="low",
        required_secret_refs=("api_key",),
        required_env_keys=("OPENAI_API_KEY",),
        required_config_keys=(),
        readiness_notes=(
            "Critical-path fallback when NVIDIA is unavailable. "
            "OpenAI primary fallback; Anthropic Claude is the "
            "secondary fallback when configured."
        ),
    ),
    RuntimeOperationDefinition(
        operation_type="ai.smoke_test",
        provider_type=_PROVIDER_OPENAI,
        side_effect_risk="none",
        required_secret_refs=("api_key",),
        required_env_keys=("NVIDIA_API_KEY", "AI_MAX_TOKENS_SMOKE"),
        required_config_keys=("NVIDIA_MODEL_HINGLISH_CHAT",),
        readiness_notes=(
            "Tiny non-customer prompt (e.g. 'Reply only OK') used "
            "manually by the operator to verify provider reachability."
        ),
    ),
)


_REGISTRY: dict[str, RuntimeOperationDefinition] = {
    op.operation_type: op for op in RUNTIME_OPERATIONS
}


def list_runtime_operations() -> tuple[RuntimeOperationDefinition, ...]:
    return RUNTIME_OPERATIONS


def get_runtime_operation_definition(
    operation_type: str,
) -> Optional[RuntimeOperationDefinition]:
    return _REGISTRY.get(operation_type or "")


def filter_operations(
    *,
    provider_types: Optional[Iterable[str]] = None,
) -> list[RuntimeOperationDefinition]:
    """Convenience filter — returns operations whose provider_type is
    in the requested set. ``None`` returns every operation."""
    if provider_types is None:
        return list(RUNTIME_OPERATIONS)
    wanted = {pt for pt in provider_types if pt}
    return [
        op for op in RUNTIME_OPERATIONS if op.provider_type in wanted
    ]


__all__ = (
    "RuntimeOperationDefinition",
    "RUNTIME_OPERATIONS",
    "list_runtime_operations",
    "get_runtime_operation_definition",
    "filter_operations",
)
