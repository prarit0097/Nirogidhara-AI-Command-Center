"""Phase 5A — Baileys dev-only stub.

Locked rules (Master Blueprint + Phase 5A-0):

- Production target is Meta Cloud. Baileys is **NEVER** used in production.
- This stub refuses to load when ``DJANGO_DEBUG=False`` AND
  ``WHATSAPP_DEV_PROVIDER_ENABLED!=true``.
- It does **not** ship a real Baileys integration. The send / parse
  methods raise so a misconfigured production environment fails closed
  rather than sending traffic through the wrong path.

Why: the reference repo's Baileys provider proxies to a separate Node
process. Nirogidhara has no path to ship that in production (ToS risk).
We keep the provider name in the registry only to make the dev/demo
toggle explicit; it has no live transport.
"""
from __future__ import annotations

from typing import Any, Mapping

from django.conf import settings

from .base import (
    ProviderError,
    ProviderHealth,
    ProviderSendResult,
    ProviderStatusResult,
    ProviderWebhookEvent,
)


class BaileysDevProviderDisabled(ProviderError):
    """Raised when ``baileys_dev`` is selected without explicit dev opt-in."""


class BaileysDevProvider:
    """Dev/demo-only stub. Refuses to actually send."""

    name = "baileys_dev"

    def __init__(self) -> None:
        debug = bool(getattr(settings, "DEBUG", False))
        explicit = bool(getattr(settings, "WHATSAPP_DEV_PROVIDER_ENABLED", False))
        if not (debug and explicit):
            raise BaileysDevProviderDisabled(
                (
                    "baileys_dev is dev-only and disabled by default. "
                    "Set DJANGO_DEBUG=true AND WHATSAPP_DEV_PROVIDER_ENABLED=true "
                    "to enable it locally; production must use WHATSAPP_PROVIDER=meta_cloud."
                ),
                error_code="baileys_disabled",
                retryable=False,
            )

    def send_template_message(self, **_: Any) -> ProviderSendResult:
        raise ProviderError(
            (
                "BaileysDevProvider has no production transport. "
                "Use WHATSAPP_PROVIDER=mock for local tests or "
                "WHATSAPP_PROVIDER=meta_cloud for real sends."
            ),
            error_code="baileys_no_transport",
            retryable=False,
        )

    def send_text_message(self, **_: Any) -> ProviderSendResult:
        raise ProviderError(
            "BaileysDevProvider has no production transport.",
            error_code="baileys_no_transport",
            retryable=False,
        )

    def verify_webhook(
        self,
        *,
        signature_header: str,
        body: bytes,
        timestamp_header: str | None = None,
    ) -> bool:
        return False

    def parse_webhook_event(
        self, *, body: Mapping[str, Any]
    ) -> list[ProviderWebhookEvent]:
        return []

    def get_message_status(
        self, *, provider_message_id: str
    ) -> ProviderStatusResult:
        return ProviderStatusResult(
            provider=self.name,
            provider_message_id=provider_message_id,
            status="unknown",
            raw={"detail": "baileys_dev has no live transport"},
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            healthy=False,
            detail="baileys_dev is a dev/demo stub with no production transport.",
            metadata={"configured": False},
        )


__all__ = ("BaileysDevProvider", "BaileysDevProviderDisabled")
