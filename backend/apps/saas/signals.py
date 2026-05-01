"""Phase 6D — pre_save signal handlers that auto-assign org/branch.

Connects a single :func:`auto_assign_org_branch` receiver to every
business-state model that has an ``organization`` FK. The handler runs
ONLY on create (``instance._state.adding=True``) and ONLY when the
relevant FK is ``None``; it never overwrites an explicit assignment.

LOCKED rules:

- Skips bulk ``QuerySet.update()`` (Django doesn't fire pre_save on
  those — bulk updates remain the canonical way to backfill or
  re-scope existing rows).
- Inheritance order (parent → fallback): ``conversation`` → ``message``
  → ``order`` → ``shipment`` → ``payment`` → ``call`` → ``customer``
  → ``lead`` → seeded default org / branch.
- ``audit.AuditEvent`` is NOT registered here — the Phase 6C upgrade
  to :func:`apps.audit.signals.write_event` already auto-attaches org
  context with full request/user awareness.
- ``apps.saas.*`` models are NOT registered (they own the SaaS shape).
- System / webhook / child-of-message models without an ``organization``
  field are NOT registered.
"""
from __future__ import annotations

from django.db.models.signals import pre_save
from django.dispatch import receiver

from .write_context import assign_org_branch_from_first_parent


# (app_label, model_name) tuples for the models we connect. Kept as a
# constant so :mod:`apps.saas.write_readiness` can introspect what's
# covered without re-walking the registry.
ORG_AUTO_ASSIGN_MODELS: tuple[tuple[str, str], ...] = (
    ("crm", "Lead"),
    ("crm", "Customer"),
    ("orders", "Order"),
    ("orders", "DiscountOfferLog"),
    ("payments", "Payment"),
    ("shipments", "Shipment"),
    ("calls", "Call"),
    ("whatsapp", "WhatsAppConsent"),
    ("whatsapp", "WhatsAppConversation"),
    ("whatsapp", "WhatsAppMessage"),
    ("whatsapp", "WhatsAppLifecycleEvent"),
    ("whatsapp", "WhatsAppHandoffToCall"),
    ("whatsapp", "WhatsAppPilotCohortMember"),
)


def auto_assign_org_branch(sender, instance, **kwargs):
    """Pre-save receiver — auto-assign org / branch on create only.

    The handler is intentionally additive:

    - Only runs when ``instance._state.adding`` is ``True``.
    - Only fills FKs that are currently ``None``.
    - Falls back to the seeded default org / branch when no parent
      resolves and no other context is available.
    - Silent on any unexpected error so a save can never crash because
      of an org auto-assign.
    """
    state = getattr(instance, "_state", None)
    if state is None or not getattr(state, "adding", False):
        return
    try:
        # Walk parent FKs first (customer, conversation, etc.), then
        # fall back to the seeded default org / branch.
        from .write_context import apply_org_branch

        assign_org_branch_from_first_parent(instance)
        # If parent inheritance didn't fill the org slot, fall back to
        # the seeded default org. ``apply_org_branch`` is the canonical
        # default-fallback path — it leaves explicit assignments alone.
        apply_org_branch(instance)
    except Exception:  # noqa: BLE001 - never crash a save
        return


def _connect_signal_handlers() -> None:
    """Idempotent connector — wires the receiver to every model in
    :data:`ORG_AUTO_ASSIGN_MODELS`. Called from
    :class:`apps.saas.apps.SaasConfig.ready`."""
    from django.apps import apps

    for app_label, model_name in ORG_AUTO_ASSIGN_MODELS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        pre_save.connect(
            auto_assign_org_branch,
            sender=model,
            dispatch_uid=(
                f"saas.auto_assign_org_branch.{app_label}.{model_name}"
            ),
        )


__all__ = (
    "ORG_AUTO_ASSIGN_MODELS",
    "auto_assign_org_branch",
    "_connect_signal_handlers",
)
