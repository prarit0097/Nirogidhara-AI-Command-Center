"""Phase 5A — WhatsApp provider interface.

Three providers ship in Phase 5A:

- ``mock``        — deterministic, no network. Default for tests / dev.
- ``meta_cloud``  — production target.
- ``baileys_dev`` — explicit dev-only stub. Refuses to load when
                    ``DJANGO_DEBUG=False`` AND
                    ``WHATSAPP_DEV_PROVIDER_ENABLED!=true``.

Each provider returns deterministic dataclasses so the service layer can
treat all three uniformly. Failures raise :class:`ProviderError`; the
service translates that into a ``WhatsAppMessage.status=failed`` row +
``whatsapp.message.failed`` audit, **never** a five-hundred from the
view.

LOCKED rule: providers are pure I/O. They never read the DB. They never
write the DB. They never log secrets. The service layer owns all of
those concerns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class ProviderError(Exception):
    """Raised when a provider call fails for any reason."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderSendResult:
    """Outcome of a single send attempt."""

    provider: str
    provider_message_id: str
    status: str  # "queued" | "sent"
    request_payload: Mapping[str, Any] = field(default_factory=dict)
    response_status: int = 0
    response_payload: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    error_code: str = ""

    def is_success(self) -> bool:
        return bool(self.provider_message_id) and self.status in {"queued", "sent"}


@dataclass(frozen=True)
class ProviderWebhookEvent:
    """Parsed event extracted from a Meta webhook delivery.

    A single Meta webhook body can carry multiple events (an ``entry[]``
    with multiple ``changes[].value.messages[]`` and ``statuses[]``).
    Providers parse the body into a list of these.
    """

    event_id: str               # Stable id used for idempotency.
    event_type: str             # "messages" | "statuses" | "errors" | ...
    direction: str              # "inbound" | "status" | "system"
    provider_message_id: str    # Meta wamid.
    from_phone: str             # E.164 (sender, inbound only)
    to_phone: str               # E.164 (recipient, inbound only)
    status: str                 # status name when event_type=statuses
    timestamp: int              # Unix seconds (Meta sends seconds).
    body: str                   # Text body when inbound.
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderStatusResult:
    """Result of polling for the live status of a single message."""

    provider: str
    provider_message_id: str
    status: str
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    """Result of a provider health check."""

    provider: str
    healthy: bool
    detail: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class WhatsAppProvider(Protocol):
    """Protocol every provider implements.

    Phase 5A only wires ``send_template_message``, ``verify_webhook``,
    ``parse_webhook_event``, and ``health_check`` into the live HTTP
    surface. ``send_text_message`` and ``get_message_status`` are part of
    the contract so future Phase 5B/5C code can add them without another
    interface migration.
    """

    name: str

    def send_template_message(
        self,
        *,
        to_phone: str,
        template_name: str,
        language: str,
        components: list[Mapping[str, Any]],
        idempotency_key: str,
    ) -> ProviderSendResult: ...

    def send_text_message(
        self,
        *,
        to_phone: str,
        body: str,
        idempotency_key: str,
    ) -> ProviderSendResult: ...

    def verify_webhook(
        self,
        *,
        signature_header: str,
        body: bytes,
        timestamp_header: str | None = None,
    ) -> bool: ...

    def parse_webhook_event(
        self,
        *,
        body: Mapping[str, Any],
    ) -> list[ProviderWebhookEvent]: ...

    def get_message_status(
        self,
        *,
        provider_message_id: str,
    ) -> ProviderStatusResult: ...

    def health_check(self) -> ProviderHealth: ...


__all__ = (
    "ProviderError",
    "ProviderHealth",
    "ProviderSendResult",
    "ProviderStatusResult",
    "ProviderWebhookEvent",
    "WhatsAppProvider",
)
