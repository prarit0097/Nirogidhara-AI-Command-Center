"""Phase 5A — WhatsApp Celery tasks.

Local dev / CI runs in ``CELERY_TASK_ALWAYS_EAGER=true`` mode so
``.delay()`` is synchronous and no Redis is required.

Locked rules:

- ``send_whatsapp_message_task`` is idempotent on the
  :class:`apps.whatsapp.WhatsAppMessage.idempotency_key` constraint AND
  the early-exit in :func:`apps.whatsapp.services.send_queued_message`
  when ``provider_message_id`` is already populated.
- The task uses ``autoretry_for=(ProviderError,)`` with
  ``retry_backoff=True``, ``retry_jitter=True``, and ``max_retries=5`` —
  the service raises :class:`ProviderError` only when the failure is
  retryable; non-retryable failures propagate as a plain ``Exception``
  and the task surfaces them in the SendLog without retrying.
"""
from __future__ import annotations

from typing import Any

from celery import shared_task

from .integrations.whatsapp.base import ProviderError


@shared_task(
    name="apps.whatsapp.tasks.send_whatsapp_message",
    bind=True,
    autoretry_for=(ProviderError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
)
def send_whatsapp_message(self, message_id: str) -> dict[str, Any]:
    """Drive a queued :class:`WhatsAppMessage` through the provider once."""
    from .services import send_queued_message

    message = send_queued_message(message_id)
    return {
        "messageId": message.id,
        "status": message.status,
        "providerMessageId": message.provider_message_id,
    }


__all__ = ("send_whatsapp_message",)
