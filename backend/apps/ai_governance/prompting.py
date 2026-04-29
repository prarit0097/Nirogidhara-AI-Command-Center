"""Prompt assembly with hard compliance guardrails — Phase 3A.

Every Phase 3 LLM call routes through ``build_messages`` so every prompt
carries:

1. The **system policy block** that lists the non-negotiable rules from
   Master Blueprint §26 (Approved Claim Vault only, CAIO never executes,
   etc.). The block is assembled from constants in this module — never
   from user input.
2. The **agent-specific role block** describing what this particular agent
   is supposed to do (e.g. CAIO audits, never executes).
3. The **Approved Claim Vault** entries relevant to the agent's payload.
   When the input mentions a product (or implies medical/product
   explanation), we MUST attach the matching ``apps.compliance.Claim`` rows.
   If no relevant approved claim exists for a medical/product payload we
   refuse to build the prompt (raise ``ClaimVaultMissing``) so the caller
   logs a ``failed`` AgentRun rather than dispatching a hallucinated answer.
4. The **input slice** the caller passed in — coerced through ``json.dumps``
   so the model never sees raw Python objects.

Phase 5+ will add prompt versioning + rollback. Today every call uses
``PROMPT_VERSION = "v1.0-phase3a"``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from apps.compliance.models import Claim


PROMPT_VERSION = "v1.0-phase3a"

# When an active PromptVersion is loaded for the agent, the runtime passes
# it to ``build_messages`` and we use its ``system_policy`` /
# ``role_prompt`` blocks instead of the hard-coded defaults below. The
# Approved Claim Vault block is **always** appended on top — a custom
# PromptVersion CANNOT skip it.


# ----- Constants -----

_SYSTEM_POLICY = """\
You are an internal AI agent for Nirogidhara Private Limited, an Ayurvedic
medicine D2C company. You operate under Master Blueprint v2.0. The
following rules are non-negotiable:

1. APPROVED CLAIM VAULT ONLY. You may discuss medicines, side effects,
   benefits, or product details ONLY using the approved-claim entries
   provided in the system block titled "Approved Claim Vault". Never
   invent medical claims. Never use any of these blocked phrases:
     - "Guaranteed cure"
     - "Permanent solution"
     - "No side effects for everyone"
     - "Works for all people universally"
     - "Doctor ki zarurat nahi"
     - Any "cures X disease" phrasing without explicit doctor approval
     - Emergency medical advice
   If a question requires content outside the vault, respond with:
   "Out of scope — refer to compliance team."

2. CAIO AGENT NEVER EXECUTES. Audit / monitor / suggest only. CAIO must
   never recommend writing to leads, orders, payments, shipments, or
   any business state.

3. CEO AI is the approval layer for medium-risk actions; high-risk
   actions require Prarit Sidana's explicit sign-off. You may suggest
   but never confirm such an action without the appropriate approver.

4. EVERY OUTPUT MUST BE STRUCTURED JSON. Wrap your reply in the JSON
   schema requested by the agent role block. No prose outside the JSON.

5. REWARD/PENALTY is based on delivered profitable orders, not orders
   punched. Optimise for net delivered profit.

6. You are running in Phase 3A: read-only / dry-run mode. Even if you
   recommend an action, the runtime will NOT execute it without further
   approval middleware. Do not pretend an action has been taken.
"""

_AGENT_ROLES: dict[str, str] = {
    "ceo": (
        "Role: CEO AI. Generate the daily executive briefing — headline KPI "
        "movement, recommended actions (each with reason, impact, and required "
        "approver), and alerts that need Prarit's attention."
    ),
    "caio": (
        "Role: CAIO (Chief AI Officer) — audit, monitor, suggest. You "
        "MUST NOT recommend writing to leads, orders, payments, shipments, "
        "calls, or any business state. Output flagged risks only."
    ),
    "ads": (
        "Role: Ads Agent. Surface ad-spend efficiency, ROAS issues, and "
        "creative recommendations. Suggestions only — execution requires "
        "CEO AI / Prarit approval."
    ),
    "rto": (
        "Role: RTO Prevention Agent. Identify at-risk orders and recommend "
        "rescue actions (channel, message). Never auto-cancel; suggest only."
    ),
    "sales_growth": (
        "Role: Sales Growth Agent. Suggest discount, advance, and conversion "
        "experiments. Discount over 20% requires CEO AI; over 30% requires "
        "Prarit. Suggestions only."
    ),
    "marketing": (
        "Role: Marketing Agent. Suggest funnel + creative orchestration "
        "ideas. Suggestions only — never auto-launch."
    ),
    "cfo": (
        "Role: CFO AI. Net delivered profit + cash-flow analysis. Reporting "
        "only — never modifies financial state."
    ),
    "compliance": (
        "Role: Compliance & Medical Safety. Enforce Approved Claim Vault. "
        "Flag risky claim drafts, never approve them — that requires the "
        "Doctor + Compliance human reviewers."
    ),
}


# Heuristic: agents whose typical inputs trigger medical/product reasoning.
# When these agents run with a non-empty payload that implies product talk
# (mentions product, claim, medicine, customer-facing message, etc.) we
# require at least one matching Claim Vault entry.
_AGENTS_NEEDING_VAULT: frozenset[str] = frozenset(
    {"compliance", "ceo", "caio", "marketing", "sales_growth"}
)

_PRODUCT_TRIGGERS: tuple[str, ...] = (
    "product",
    "claim",
    "medicine",
    "ayurved",
    "treatment",
    "side effect",
    "ingredient",
    "dosage",
    "customer message",
    "script",
    "ad copy",
    "creative",
)


class ClaimVaultMissing(Exception):
    """Raised when a medical/product prompt has no approved claims to ground it."""


@dataclass(frozen=True)
class PromptBundle:
    """The structured output ``build_messages`` returns."""

    messages: list[dict[str, str]]
    prompt_version: str
    claims_used: list[str]  # product names whose claim entries were attached


# ----- Public API -----


def needs_claim_vault(agent: str, input_payload: dict[str, Any]) -> bool:
    """Return True when this run touches medical/product content.

    For agents that always need the vault (compliance, ceo summaries,
    marketing copy etc.), even an empty payload triggers a check — the
    agent's role itself implies medical/product reasoning.
    """
    if agent in _AGENTS_NEEDING_VAULT:
        return True
    text = json.dumps(input_payload or {}, ensure_ascii=False).lower()
    return any(trigger in text for trigger in _PRODUCT_TRIGGERS)


def _relevant_claims(input_payload: dict[str, Any]) -> list[Claim]:
    """Pick the Claim rows whose product appears in the input payload.

    When the payload is empty (or doesn't mention a product) we fall back
    to the full vault — the model still has the ground-truth list to lean
    on rather than hallucinating.
    """
    text = json.dumps(input_payload or {}, ensure_ascii=False).lower()
    explicit: list[Claim] = []
    for claim in Claim.objects.all():
        if claim.product.lower() in text:
            explicit.append(claim)
    if explicit:
        return explicit
    return list(Claim.objects.all())


def _format_claim(claim: Claim) -> str:
    approved = "; ".join(claim.approved or []) or "(none on file)"
    disallowed = "; ".join(claim.disallowed or []) or "(none on file)"
    return (
        f"- Product: {claim.product} (version {claim.version}, doctor: "
        f"{claim.doctor}, compliance: {claim.compliance})\n"
        f"  APPROVED phrases: {approved}\n"
        f"  DISALLOWED phrases: {disallowed}"
    )


def build_messages(
    *,
    agent: str,
    input_payload: dict[str, Any],
    prompt_version: Any | None = None,
) -> PromptBundle:
    """Assemble the message list for an agent dispatch.

    Phase 3D: when ``prompt_version`` is supplied (an active PromptVersion
    row from ``apps.ai_governance.models``), its ``system_policy`` and
    ``role_prompt`` blocks override the hard-coded defaults in this
    module. The Claim Vault block is **always** appended on top — a
    PromptVersion CANNOT skip it. The reported ``prompt_version`` string
    becomes ``"<agent>:<version>"`` for forward-compat audit trails.

    Raises:
        ValueError: when ``agent`` is not in the supported set.
        ClaimVaultMissing: when the run requires Claim Vault grounding but
            the vault is empty.
    """
    if agent not in _AGENT_ROLES:
        raise ValueError(f"Unknown agent: {agent!r}")

    claims_used: list[str] = []
    needs_vault = needs_claim_vault(agent, input_payload)
    if needs_vault:
        claims = _relevant_claims(input_payload)
        if not claims:
            raise ClaimVaultMissing(
                f"No approved claims available for agent {agent!r} — "
                "refusing to build a medical/product prompt."
            )
        claims_used = [c.product for c in claims]
        claim_block = "Approved Claim Vault (ground-truth — speak ONLY from these):\n" + "\n".join(
            _format_claim(c) for c in claims
        )
    else:
        claim_block = (
            "Approved Claim Vault: not required for this agent run. "
            "Do NOT introduce medical/product claims."
        )

    # Phase 3D — when an active PromptVersion is supplied, its blocks
    # override the hard-coded defaults. The Claim Vault block is always
    # appended on top regardless.
    system_policy_block = _SYSTEM_POLICY.strip()
    role_block = _AGENT_ROLES[agent]
    reported_version = PROMPT_VERSION
    if prompt_version is not None:
        custom_system = (getattr(prompt_version, "system_policy", "") or "").strip()
        custom_role = (getattr(prompt_version, "role_prompt", "") or "").strip()
        if custom_system:
            system_policy_block = custom_system
        if custom_role:
            role_block = custom_role
        version_label = (
            f"{getattr(prompt_version, 'agent', agent)}:"
            f"{getattr(prompt_version, 'version', '')}"
        ).strip(":")
        if version_label:
            reported_version = version_label

    user_block = (
        "Input payload (JSON):\n"
        + json.dumps(input_payload or {}, ensure_ascii=False, indent=2)
        + "\n\nReturn a single JSON object with keys: "
        '{"summary": str, "recommendations": list, "alerts": list}.'
    )

    messages = [
        {"role": "system", "content": system_policy_block},
        {"role": "system", "content": role_block},
        {"role": "system", "content": claim_block},
        {"role": "user", "content": user_block},
    ]
    return PromptBundle(
        messages=messages,
        prompt_version=reported_version,
        claims_used=claims_used,
    )


__all__ = (
    "PROMPT_VERSION",
    "PromptBundle",
    "ClaimVaultMissing",
    "needs_claim_vault",
    "build_messages",
)
