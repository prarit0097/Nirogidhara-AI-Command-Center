"""Phase 3E — Advance payment policy (Master Blueprint §24 #4).

Locked decision: the standard advance payment for an Ayurvedic order is
**₹499**. The payment-link service defaults to this amount whenever an
``Advance`` payment link is requested without an explicit ``amount``
override. Callers can still pass a different amount — the policy only
sets the default, never overrides an explicit value.

The constant is used by:
- :mod:`apps.payments.services` for ``create_payment_link``
- :mod:`apps.payments.serializers` for input validation defaults
- Future approval-matrix middleware (Phase 4C) for fixed-advance routing

Documenting it as a frozen module-level constant makes audits trivial.
"""
from __future__ import annotations

# Locked at the blueprint / business level. Director sign-off required
# to change this default.
FIXED_ADVANCE_AMOUNT_INR: int = 499


def resolve_advance_amount(requested_amount: int | None) -> int:
    """Return the advance amount the gateway should be asked to collect.

    - ``None`` / 0 → :data:`FIXED_ADVANCE_AMOUNT_INR`
    - Any other positive integer → the value as-is (caller-supplied)

    The service layer is the only place that should *enforce* this; the
    helper is a thin convenience for that one call site.
    """
    if requested_amount is None:
        return FIXED_ADVANCE_AMOUNT_INR
    if int(requested_amount) <= 0:
        return FIXED_ADVANCE_AMOUNT_INR
    return int(requested_amount)
