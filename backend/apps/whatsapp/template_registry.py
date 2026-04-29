"""Phase 5A — WhatsApp template registry.

Templates are **mirrored from Meta**. Phase 5A does not allow ad-hoc
template creation through the frontend — admin / director must sync from
``GET /v20.0/{waba_id}/message_templates`` (or seed the catalog locally
via the ``sync_whatsapp_templates`` management command).

Locked rules:

- Only ``status=APPROVED`` AND ``is_active=True`` templates can be used
  for sends.
- Action key mapping turns the matrix action (e.g. ``whatsapp.payment_reminder``)
  into the template ``name`` Meta knows about. Operators can set the
  mapping via Django admin or the patch endpoint.
- Variable rendering is positional: ``{{1}}``, ``{{2}}``, ... Meta's
  components array shape is preserved verbatim in ``body_components`` so
  the send pipeline can hand it back without modification.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.utils import timezone

from apps._id import next_id
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import WhatsAppConnection, WhatsAppTemplate


# Default action_key → seeded template name map. Phase 5A reserves the
# first 7 lifecycle actions; admin/director can edit the mapping later
# via Django admin if Meta-approved template names differ.
DEFAULT_TEMPLATE_NAMES: dict[str, str] = {
    "whatsapp.payment_reminder": "nrg_payment_reminder",
    "whatsapp.confirmation_reminder": "nrg_confirmation_reminder",
    "whatsapp.delivery_reminder": "nrg_delivery_reminder",
    "whatsapp.rto_rescue": "nrg_rto_rescue",
    "whatsapp.usage_explanation": "nrg_usage_explanation",
    "whatsapp.reorder_reminder": "nrg_reorder_reminder",
    "whatsapp.support_complaint_ack": "nrg_support_complaint_ack",
    # Phase 5A-1 anticipated greeting template — registered now so Phase
    # 5C wiring doesn't have to invent a name.
    "whatsapp.greeting": "nrg_greeting_intro",
    # Phase 5E — rescue discount + Day 20 reorder templates.
    "whatsapp.confirmation_rescue_discount": "nrg_confirmation_rescue_discount",
    "whatsapp.delivery_rescue_discount": "nrg_delivery_rescue_discount",
    "whatsapp.rto_rescue_discount": "nrg_rto_rescue_discount",
    "whatsapp.reorder_day20_reminder": "nrg_reorder_day20_reminder",
}

# Templates whose body falls under the Approved Claim Vault gate.
# (Usage explanation is the canonical case — it carries product / medical
# context.)
DEFAULT_CLAIM_VAULT_REQUIRED: frozenset[str] = frozenset(
    {"whatsapp.usage_explanation"}
)


class TemplateRegistryError(Exception):
    """Raised when a template lookup / sync fails."""


# Phase 5C — locked Hindi greeting body, used when the canonical
# template has not been synced yet OR when ops want to seed a default
# greeting locally. The send pipeline ALWAYS prefers a Meta-approved
# template row; this string is a documented fallback for tests / dev.
GREETING_LOCKED_HINDI = (
    "Namaskar, Nirogidhara Ayurvedic Sanstha mein aapka swagat hai. "
    "Batayein, main aapki kya help kar sakta/sakti hoon?"
)


def language_to_template_tag(language: str) -> str:
    """Map the Phase 5C language vocabulary to template ``language`` codes.

    The template registry stores ``hi``, ``en``, ``en_US`` (whatever Meta
    approved). Hinglish typically reuses the ``hi`` template since Meta
    does not support a dedicated Hinglish locale — the LLM later replies
    in Hinglish freeform after the greeting.
    """
    norm = (language or "").lower().strip()
    if norm in {"hindi", "hi", "hin"}:
        return "hi"
    if norm in {"hinglish", "hin-eng", "hindlish"}:
        return "hi"
    if norm in {"english", "en", "eng"}:
        return "en"
    return "hi"


def get_template_for_action(
    *,
    action_key: str,
    language: str = "hi",
    connection: WhatsAppConnection | None = None,
) -> WhatsAppTemplate:
    """Return the active template row for an action / language."""
    qs = WhatsAppTemplate.objects.filter(
        action_key=action_key,
        is_active=True,
        status=WhatsAppTemplate.Status.APPROVED,
    )
    if connection is not None:
        qs = qs.filter(connection=connection)
    template = (
        qs.filter(language=language).first()
        or qs.first()
    )
    if template is None:
        raise TemplateRegistryError(
            f"No approved active template found for action '{action_key}' "
            f"(language={language})."
        )
    return template


def render_template_components(
    template: WhatsAppTemplate,
    variables: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build the Meta-style components array from the template + variables.

    Phase 5A keeps this simple: positional body parameters only. The
    template's ``body_components`` JSON is preserved verbatim and we add
    a single body block with the rendered variables.
    """
    if template.body_components:
        # Meta-shaped components were synced — assume they're parameter
        # placeholders mapped via positional ``{{1}}``, ``{{2}}``, ... We
        # honour ``variables_schema`` if present.
        ordered = _ordered_variable_values(template, variables)
    else:
        ordered = list(variables.values())

    if not ordered:
        return []

    parameters = [{"type": "text", "text": str(v)} for v in ordered]
    return [{"type": "body", "parameters": parameters}]


def validate_template_variables(
    template: WhatsAppTemplate,
    variables: Mapping[str, Any],
) -> None:
    """Raise :class:`TemplateRegistryError` when required variables are missing."""
    schema = template.variables_schema or {}
    required = schema.get("required") or []
    if isinstance(required, list):
        missing = [key for key in required if not variables.get(key)]
        if missing:
            raise TemplateRegistryError(
                f"Template '{template.name}' missing required variables: {missing}"
            )


def upsert_template(
    *,
    connection: WhatsAppConnection,
    name: str,
    language: str,
    category: str = WhatsAppTemplate.Category.UTILITY,
    status: str = WhatsAppTemplate.Status.APPROVED,
    body_components: Iterable[Mapping[str, Any]] | None = None,
    variables_schema: Mapping[str, Any] | None = None,
    action_key: str = "",
    claim_vault_required: bool | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[WhatsAppTemplate, bool]:
    """Insert or update a template row from a sync payload.

    Returns ``(row, created)`` so callers can audit on first sync.
    """
    if claim_vault_required is None:
        claim_vault_required = action_key in DEFAULT_CLAIM_VAULT_REQUIRED

    defaults: dict[str, Any] = {
        "category": category,
        "status": status,
        "body_components": list(body_components or []),
        "variables_schema": dict(variables_schema or {}),
        "action_key": action_key
        or _action_key_for_name(name),
        "claim_vault_required": claim_vault_required,
        "is_active": status == WhatsAppTemplate.Status.APPROVED,
        "last_synced_at": timezone.now(),
        "metadata": dict(metadata or {}),
    }

    existing = WhatsAppTemplate.objects.filter(
        connection=connection, name=name, language=language
    ).first()
    created = existing is None
    if existing is None:
        template = WhatsAppTemplate.objects.create(
            id=next_id("WAT", WhatsAppTemplate, base=10001),
            connection=connection,
            name=name,
            language=language,
            **defaults,
        )
    else:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save()
        template = existing

    write_event(
        kind="whatsapp.template.synced",
        text=(
            f"WhatsApp template synced: {template.name}/{template.language} "
            f"({template.status})"
        ),
        tone=AuditEvent.Tone.INFO,
        payload={
            "template_id": template.id,
            "name": template.name,
            "language": template.language,
            "status": template.status,
            "action_key": template.action_key,
            "claim_vault_required": template.claim_vault_required,
            "created": created,
        },
    )
    return template, created


def sync_templates_from_provider(
    *,
    connection: WhatsAppConnection,
    payload: Mapping[str, Any] | None = None,
    actor: str = "",
) -> dict[str, Any]:
    """Run a full sync from a provider payload.

    Phase 5A does not yet make a live ``GET /message_templates`` call —
    operators can pass the JSON manually. The shape follows Meta's:
    ``{"data": [{"name": ..., "language": ..., "category": ...,
    "status": ..., "components": [...]}]}``.

    For mock mode (no payload supplied) the sync seeds the seven
    canonical lifecycle templates so tests / dev have working rows.
    """
    payload = dict(payload or {})
    items: list[Mapping[str, Any]]
    if not payload:
        items = list(_seed_default_templates())
    else:
        items = list(payload.get("data") or [])

    created_count = 0
    updated_count = 0
    for entry in items:
        name = str(entry.get("name") or "")
        language = str(entry.get("language") or "hi")
        if not name:
            continue
        action_key = str(entry.get("action_key") or "") or _action_key_for_name(name)
        _, created = upsert_template(
            connection=connection,
            name=name,
            language=language,
            category=str(entry.get("category") or WhatsAppTemplate.Category.UTILITY),
            status=str(entry.get("status") or WhatsAppTemplate.Status.APPROVED),
            body_components=entry.get("components") or [],
            variables_schema=entry.get("variables_schema") or {},
            action_key=action_key,
            claim_vault_required=entry.get("claim_vault_required"),
            metadata=entry.get("metadata") or {},
        )
        created_count += int(created)
        updated_count += int(not created)

    return {
        "connectionId": connection.id,
        "createdCount": created_count,
        "updatedCount": updated_count,
        "totalProcessed": len(items),
        "actor": actor,
    }


def _action_key_for_name(name: str) -> str:
    """Reverse the default mapping when admin sync sends only ``name``."""
    for action_key, mapped_name in DEFAULT_TEMPLATE_NAMES.items():
        if mapped_name == name:
            return action_key
    return ""


def _ordered_variable_values(
    template: WhatsAppTemplate,
    variables: Mapping[str, Any],
) -> list[Any]:
    """Return values in the schema-declared order (or insertion order)."""
    schema = template.variables_schema or {}
    order = schema.get("order") if isinstance(schema, dict) else None
    if isinstance(order, list):
        return [variables.get(key, "") for key in order]
    return list(variables.values())


def _seed_default_templates() -> list[Mapping[str, Any]]:
    """Generate canonical seed entries for mock-mode sync.

    Greeting templates seed both Hindi (locked Phase 5A-1 string) AND
    English so the Phase 5C language detector has a row for either path.
    Hinglish reuses the Hindi row by convention (Meta does not approve
    a separate Hinglish locale).
    """
    seeds: list[Mapping[str, Any]] = []
    for action_key, name in DEFAULT_TEMPLATE_NAMES.items():
        category = (
            WhatsAppTemplate.Category.MARKETING
            if action_key == "whatsapp.reorder_reminder"
            else WhatsAppTemplate.Category.UTILITY
        )
        if action_key == "whatsapp.greeting":
            # Locked Hindi greeting per Phase 5A-1 §U.
            seeds.append(
                {
                    "name": name,
                    "language": "hi",
                    "category": WhatsAppTemplate.Category.UTILITY,
                    "status": WhatsAppTemplate.Status.APPROVED,
                    "components": [
                        {"type": "BODY", "text": GREETING_LOCKED_HINDI},
                    ],
                    "variables_schema": {"required": [], "order": []},
                    "action_key": action_key,
                    "claim_vault_required": False,
                    "metadata": {"seeded": True, "locked_text": True},
                }
            )
            # English fallback for English-only customers; the Hinglish
            # path uses the Hindi row above.
            seeds.append(
                {
                    "name": name,
                    "language": "en",
                    "category": WhatsAppTemplate.Category.UTILITY,
                    "status": WhatsAppTemplate.Status.APPROVED,
                    "components": [
                        {
                            "type": "BODY",
                            "text": (
                                "Welcome to Nirogidhara Ayurvedic Sanstha. "
                                "Please tell us how we can help you today."
                            ),
                        },
                    ],
                    "variables_schema": {"required": [], "order": []},
                    "action_key": action_key,
                    "claim_vault_required": False,
                    "metadata": {"seeded": True, "locked_text": True},
                }
            )
            continue
        seeds.append(
            {
                "name": name,
                "language": "hi",
                "category": category,
                "status": WhatsAppTemplate.Status.APPROVED,
                "components": [
                    {"type": "BODY", "text": "{{1}} {{2}}"},
                ],
                "variables_schema": {
                    "required": ["customer_name"],
                    "order": ["customer_name", "context"],
                },
                "action_key": action_key,
                "claim_vault_required": action_key in DEFAULT_CLAIM_VAULT_REQUIRED,
                "metadata": {"seeded": True},
            }
        )
    return seeds


__all__ = (
    "DEFAULT_CLAIM_VAULT_REQUIRED",
    "DEFAULT_TEMPLATE_NAMES",
    "GREETING_LOCKED_HINDI",
    "TemplateRegistryError",
    "language_to_template_tag",
    "get_template_for_action",
    "render_template_components",
    "sync_templates_from_provider",
    "upsert_template",
    "validate_template_variables",
)
