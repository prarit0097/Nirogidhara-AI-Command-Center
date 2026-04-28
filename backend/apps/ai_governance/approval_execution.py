"""Phase 4D — Approved Action Execution Layer.

Turns a director / admin-approved :class:`ApprovalRequest` into the
underlying business write — but only over a **strict allow-listed
registry** of tested service-layer handlers. Every other action is
intentionally unmapped and responds with HTTP 400 +
``ai.approval.execution_skipped`` audit.

LOCKED Phase 4D decisions (Prarit, Apr 2026):
1. Initial executable registry contains ONLY:
   - ``payment.link.advance_499``
   - ``payment.link.custom_amount``
   - ``ai.prompt_version.activate``
2. Discount, sandbox-disable, ad-budget, refund, WhatsApp, and all
   medical / legal escalation actions stay **unmapped** in this first
   4D pass and intentionally fail closed.
3. CAIO can never trigger execution — refused at engine, bridge, AND
   here at the execution layer (defense in depth).
4. Claim Vault stays mandatory — no medical / claim-bound action may
   execute without an Approved Claim Vault grounding. The 3 in-scope
   handlers do not generate medical text, so they don't trigger Claim
   Vault enforcement, but the guardrail stays in place for future
   handlers.
5. ``approve_request`` does not silently execute — execution is always
   an explicit operator action through this module.
6. Idempotent re-execute: a successful execution is recorded once;
   re-running the endpoint returns the prior result without invoking
   the handler again.
7. Director-only override on ``director_override`` actions even at the
   execute endpoint.

Compliance hard stops (Master Blueprint §26):
- CAIO never executes business actions (§26 #5).
- The Approved Claim Vault is the only source of medical / product
  text — handlers must not synthesize their own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.orders.models import Order

from .models import ApprovalExecutionLog, ApprovalRequest

try:  # pragma: no cover - typing only
    from apps.accounts.models import User
except ImportError:  # pragma: no cover
    User = Any  # type: ignore[misc, assignment]


CAIO_AGENT_TOKEN: str = "caio"


# ---------------------------------------------------------------------------
# Result wrapper.
# ---------------------------------------------------------------------------


@dataclass
class ExecutionOutcome:
    """Structured result the view + frontend consume.

    ``http_status`` lets the view pick the right HTTP code without
    re-deriving it from the status string.
    """

    approval_request_id: str
    action: str
    status: str  # ApprovalExecutionLog.Status value
    http_status: int
    result: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    message: str = ""
    already_executed: bool = False
    log: ApprovalExecutionLog | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "approvalRequestId": self.approval_request_id,
            "action": self.action,
            "executionStatus": self.status,
            "executedAt": (
                self.log.executed_at.isoformat() if self.log else None
            ),
            "executedBy": (
                getattr(self.log.executed_by, "username", "")
                if self.log and self.log.executed_by
                else ""
            ),
            "result": dict(self.result or {}),
            "errorMessage": self.error_message,
            "message": self.message,
            "alreadyExecuted": self.already_executed,
        }
        return out


class ExecutionRefused(Exception):
    """Raised by pre-checks when execution must not proceed.

    Carries the ``http_status`` and a ``reason`` so the view returns
    the correct status code without re-deriving it.
    """

    def __init__(self, *, reason: str, http_status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Handler registry.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HandlerSpec:
    """One row in the allow-listed handler registry."""

    action: str
    handler: Callable[
        [ApprovalRequest, "User", Mapping[str, Any]], Mapping[str, Any]
    ]
    description: str


def _handler_payment_link_advance_499(
    approval: ApprovalRequest,
    user: "User",
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Generate the standard ₹499 advance payment link.

    Always resolves the amount to :data:`apps.payments.policies.FIXED_ADVANCE_AMOUNT_INR`
    regardless of what was supplied — defense against payload tampering.
    """
    from apps.payments import services as payments_services
    from apps.payments.models import Payment
    from apps.payments.policies import FIXED_ADVANCE_AMOUNT_INR
    from apps.payments.serializers import PaymentSerializer

    order_id = (payload.get("orderId") or "").strip()
    if not order_id:
        raise ExecutionRefused(
            reason="payment.link.advance_499 requires orderId in proposed_payload."
        )
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist as exc:  # noqa: BLE001
        raise ExecutionRefused(
            reason=f"Order {order_id} not found.", http_status=404
        ) from exc

    payment, payment_url = payments_services.create_payment_link(
        order=order,
        amount=FIXED_ADVANCE_AMOUNT_INR,
        by_user=user,
        gateway=payload.get("gateway") or Payment.Gateway.RAZORPAY,
        type=Payment.Type.ADVANCE,
        customer_name=payload.get("customerName") or "",
        customer_phone=payload.get("customerPhone") or "",
        customer_email=payload.get("customerEmail") or "",
    )
    return {
        "paymentId": payment.id,
        "gateway": payment.gateway.lower(),
        "status": payment.status.lower(),
        "paymentUrl": payment_url,
        "gatewayReferenceId": payment.gateway_reference_id,
        "amount": payment.amount,
        "payment": PaymentSerializer(payment).data,
    }


def _handler_payment_link_custom_amount(
    approval: ApprovalRequest,
    user: "User",
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Generate a non-standard payment link. Requires ``amount > 0``."""
    from apps.payments import services as payments_services
    from apps.payments.models import Payment
    from apps.payments.serializers import PaymentSerializer

    order_id = (payload.get("orderId") or "").strip()
    if not order_id:
        raise ExecutionRefused(
            reason="payment.link.custom_amount requires orderId in proposed_payload."
        )
    raw_amount = payload.get("amount")
    try:
        amount = int(raw_amount) if raw_amount is not None else 0
    except (TypeError, ValueError) as exc:
        raise ExecutionRefused(
            reason="payment.link.custom_amount requires a numeric amount."
        ) from exc
    if amount <= 0:
        raise ExecutionRefused(
            reason="payment.link.custom_amount requires a positive amount."
        )
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist as exc:  # noqa: BLE001
        raise ExecutionRefused(
            reason=f"Order {order_id} not found.", http_status=404
        ) from exc

    payment, payment_url = payments_services.create_payment_link(
        order=order,
        amount=amount,
        by_user=user,
        gateway=payload.get("gateway") or Payment.Gateway.RAZORPAY,
        type=payload.get("type") or Payment.Type.ADVANCE,
        customer_name=payload.get("customerName") or "",
        customer_phone=payload.get("customerPhone") or "",
        customer_email=payload.get("customerEmail") or "",
    )
    return {
        "paymentId": payment.id,
        "gateway": payment.gateway.lower(),
        "status": payment.status.lower(),
        "paymentUrl": payment_url,
        "gatewayReferenceId": payment.gateway_reference_id,
        "amount": payment.amount,
        "payment": PaymentSerializer(payment).data,
    }


def _handler_prompt_version_activate(
    approval: ApprovalRequest,
    user: "User",
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Activate a PromptVersion through the existing service helper.

    Idempotent: if the supplied version is already active, returns
    success with ``alreadyActive=True`` instead of re-activating.
    """
    from apps.ai_governance import prompt_versions as pv_services
    from apps.ai_governance.models import PromptVersion

    pv_id = (
        payload.get("promptVersionId")
        or payload.get("prompt_version_id")
        or payload.get("id")
        or approval.target_object_id
        or ""
    )
    pv_id = str(pv_id).strip()
    if not pv_id:
        raise ExecutionRefused(
            reason=(
                "ai.prompt_version.activate requires promptVersionId in "
                "proposed_payload (or target_object_id on the approval)."
            )
        )
    try:
        pv = PromptVersion.objects.get(pk=pv_id)
    except PromptVersion.DoesNotExist as exc:  # noqa: BLE001
        raise ExecutionRefused(
            reason=f"PromptVersion {pv_id} not found.", http_status=404
        ) from exc

    if pv.is_active:
        return {
            "promptVersionId": pv.id,
            "agent": pv.agent,
            "version": pv.version,
            "alreadyActive": True,
            "message": "PromptVersion already active.",
        }

    activated = pv_services.activate_prompt_version(
        prompt_version_id=pv.id, by_user=user
    )
    return {
        "promptVersionId": activated.id,
        "agent": activated.agent,
        "version": activated.version,
        "alreadyActive": False,
        "activatedAt": (
            activated.activated_at.isoformat() if activated.activated_at else None
        ),
    }


_REGISTRY: dict[str, _HandlerSpec] = {
    "payment.link.advance_499": _HandlerSpec(
        action="payment.link.advance_499",
        handler=_handler_payment_link_advance_499,
        description="Generate the standard ₹499 advance payment link.",
    ),
    "payment.link.custom_amount": _HandlerSpec(
        action="payment.link.custom_amount",
        handler=_handler_payment_link_custom_amount,
        description="Generate a non-standard amount payment link after admin approval.",
    ),
    "ai.prompt_version.activate": _HandlerSpec(
        action="ai.prompt_version.activate",
        handler=_handler_prompt_version_activate,
        description="Activate a versioned prompt through the existing service helper.",
    ),
}


def get_execution_handler(action: str) -> _HandlerSpec | None:
    """Look up a handler in the allow-listed registry."""
    return _REGISTRY.get((action or "").strip())


# ---------------------------------------------------------------------------
# Pre-check + dispatch.
# ---------------------------------------------------------------------------


_ALLOWED_PRE_STATUSES: frozenset[str] = frozenset(
    {ApprovalRequest.Status.APPROVED, ApprovalRequest.Status.AUTO_APPROVED}
)


def build_execution_context(
    approval_request: ApprovalRequest,
    user: "User",
    payload_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge the approval's stored ``proposed_payload`` with caller overrides.

    Caller overrides win. The result is what handlers receive as
    ``payload``.
    """
    base = dict(approval_request.proposed_payload or {})
    if payload_override:
        base.update(dict(payload_override))
    return base


def _check_caio_block(approval: ApprovalRequest, payload: Mapping[str, Any]) -> None:
    if (approval.requested_by_agent or "").lower() == CAIO_AGENT_TOKEN:
        raise ExecutionRefused(
            reason="CAIO never executes business actions.",
            http_status=403,
        )
    actor_agent = (
        (payload.get("actorAgent") or "")
        if isinstance(payload, Mapping)
        else ""
    )
    if str(actor_agent).lower() == CAIO_AGENT_TOKEN:
        raise ExecutionRefused(
            reason="CAIO actor cannot trigger execution.",
            http_status=403,
        )
    metadata = approval.metadata or {}
    if str(metadata.get("actor_agent") or "").lower() == CAIO_AGENT_TOKEN:
        raise ExecutionRefused(
            reason="CAIO-originated approvals cannot be executed.",
            http_status=403,
        )


def _check_status_allows_execution(approval: ApprovalRequest) -> None:
    if approval.status in _ALLOWED_PRE_STATUSES:
        return
    raise ExecutionRefused(
        reason=(
            f"ApprovalRequest {approval.id} cannot be executed in status "
            f"'{approval.status}'. Required: 'approved' or 'auto_approved'."
        ),
        http_status=409,
    )


def _check_role(
    approval: ApprovalRequest, user: "User"
) -> None:
    role = (getattr(user, "role", "") or "").lower()
    if getattr(user, "is_superuser", False):
        return
    if role not in {"admin", "director"}:
        raise ExecutionRefused(
            reason="Only admin or director can execute an approved action.",
            http_status=403,
        )
    mode = (approval.policy_snapshot or {}).get("mode") or approval.mode
    if mode == ApprovalRequest.Mode.DIRECTOR_OVERRIDE and role != "director":
        raise ExecutionRefused(
            reason=(
                "Only the director can execute a director_override action."
            ),
            http_status=403,
        )


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


@transaction.atomic
def execute_approval_request(
    *,
    approval_request: ApprovalRequest,
    user: "User",
    payload_override: Mapping[str, Any] | None = None,
) -> ExecutionOutcome:
    """Run the allow-listed handler for an approved request.

    All pre-checks happen first; any failure is recorded as a
    ``failed`` / ``skipped`` :class:`ApprovalExecutionLog` row + audit
    event before the corresponding HTTP response is returned. CAIO is
    refused outright.
    """
    # Idempotency: if already executed, return prior result without
    # any handler call. We check this BEFORE the role / status / CAIO
    # gate so re-runs from any allowed caller are cheap and safe.
    prior = approval_request.execution_logs.filter(
        status=ApprovalExecutionLog.Status.EXECUTED
    ).first()
    if prior is not None:
        return ExecutionOutcome(
            approval_request_id=approval_request.id,
            action=approval_request.action,
            status=ApprovalExecutionLog.Status.EXECUTED,
            http_status=200,
            result=dict(prior.result or {}),
            message="Approval already executed; returning prior result.",
            already_executed=True,
            log=prior,
        )

    payload = build_execution_context(
        approval_request=approval_request,
        user=user,
        payload_override=payload_override,
    )

    try:
        _check_caio_block(approval_request, payload)
        _check_role(approval_request, user)
        _check_status_allows_execution(approval_request)
    except ExecutionRefused as exc:
        return mark_execution_failed(
            approval_request=approval_request,
            user=user,
            error=exc.reason,
            http_status=exc.http_status,
            metadata={"phase": "pre_check"},
        )

    handler_spec = get_execution_handler(approval_request.action)
    if handler_spec is None:
        return mark_execution_skipped(
            approval_request=approval_request,
            user=user,
            reason=(
                f"Action '{approval_request.action}' is not in the "
                f"Phase 4D execution registry. Approved but not executed."
            ),
            metadata={"phase": "registry_lookup"},
        )

    try:
        result = handler_spec.handler(approval_request, user, payload)
    except ExecutionRefused as exc:
        return mark_execution_failed(
            approval_request=approval_request,
            user=user,
            error=exc.reason,
            http_status=exc.http_status,
            metadata={"phase": "handler"},
        )
    except Exception as exc:  # noqa: BLE001 — record any handler exception
        return mark_execution_failed(
            approval_request=approval_request,
            user=user,
            error=str(exc),
            http_status=500,
            metadata={"phase": "handler", "exception_type": type(exc).__name__},
        )

    return mark_execution_success(
        approval_request=approval_request,
        user=user,
        result=dict(result or {}),
        metadata={"phase": "handler"},
    )


@transaction.atomic
def mark_execution_success(
    *,
    approval_request: ApprovalRequest,
    user: "User",
    result: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionOutcome:
    log = ApprovalExecutionLog.objects.create(
        approval_request=approval_request,
        action=approval_request.action,
        status=ApprovalExecutionLog.Status.EXECUTED,
        executed_by=user if getattr(user, "is_authenticated", False) else None,
        executed_at=timezone.now(),
        result=dict(result or {}),
        metadata=dict(metadata or {}),
    )
    write_event(
        kind="ai.approval.executed",
        text=(
            f"Approval {approval_request.id} executed · {approval_request.action}"
            f" by {getattr(user, 'username', '') or 'system'}"
        ),
        tone=AuditEvent.Tone.SUCCESS,
        payload={
            "approval_id": approval_request.id,
            "action": approval_request.action,
            "executed_by": getattr(user, "username", "") or "",
        },
    )
    return ExecutionOutcome(
        approval_request_id=approval_request.id,
        action=approval_request.action,
        status=log.status,
        http_status=200,
        result=dict(log.result or {}),
        message="Executed.",
        log=log,
    )


@transaction.atomic
def mark_execution_failed(
    *,
    approval_request: ApprovalRequest,
    user: "User",
    error: str,
    http_status: int = 400,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionOutcome:
    log = ApprovalExecutionLog.objects.create(
        approval_request=approval_request,
        action=approval_request.action,
        status=ApprovalExecutionLog.Status.FAILED,
        executed_by=user if getattr(user, "is_authenticated", False) else None,
        executed_at=timezone.now(),
        result={},
        error_message=error,
        metadata=dict(metadata or {}),
    )
    write_event(
        kind="ai.approval.execution_failed",
        text=(
            f"Approval {approval_request.id} execution FAILED · "
            f"{approval_request.action} · {error[:160]}"
        ),
        tone=AuditEvent.Tone.DANGER,
        payload={
            "approval_id": approval_request.id,
            "action": approval_request.action,
            "error": error,
            "executed_by": getattr(user, "username", "") or "",
        },
    )
    return ExecutionOutcome(
        approval_request_id=approval_request.id,
        action=approval_request.action,
        status=log.status,
        http_status=http_status,
        error_message=error,
        message=error,
        log=log,
    )


@transaction.atomic
def mark_execution_skipped(
    *,
    approval_request: ApprovalRequest,
    user: "User",
    reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionOutcome:
    log = ApprovalExecutionLog.objects.create(
        approval_request=approval_request,
        action=approval_request.action,
        status=ApprovalExecutionLog.Status.SKIPPED,
        executed_by=user if getattr(user, "is_authenticated", False) else None,
        executed_at=timezone.now(),
        result={},
        error_message=reason,
        metadata=dict(metadata or {}),
    )
    write_event(
        kind="ai.approval.execution_skipped",
        text=(
            f"Approval {approval_request.id} execution SKIPPED · "
            f"{approval_request.action} · {reason[:160]}"
        ),
        tone=AuditEvent.Tone.WARNING,
        payload={
            "approval_id": approval_request.id,
            "action": approval_request.action,
            "reason": reason,
            "executed_by": getattr(user, "username", "") or "",
        },
    )
    return ExecutionOutcome(
        approval_request_id=approval_request.id,
        action=approval_request.action,
        status=log.status,
        http_status=400,
        error_message=reason,
        message=reason,
        log=log,
    )


__all__ = (
    "ExecutionOutcome",
    "ExecutionRefused",
    "build_execution_context",
    "execute_approval_request",
    "get_execution_handler",
    "mark_execution_failed",
    "mark_execution_skipped",
    "mark_execution_success",
)
