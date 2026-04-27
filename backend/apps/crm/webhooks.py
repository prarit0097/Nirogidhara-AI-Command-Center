"""Meta Lead Ads webhook receiver.

Two HTTP methods on the same path:

- ``GET  /api/webhooks/meta/leads/`` — Meta's verification handshake. We
  echo ``hub.challenge`` only when ``hub.mode == "subscribe"`` and
  ``hub.verify_token == META_VERIFY_TOKEN``. Anything else returns 403.

- ``POST /api/webhooks/meta/leads/`` — Lead delivery. We:
  1. Verify ``X-Hub-Signature-256`` (HMAC-SHA256 against the raw body)
     using ``META_WEBHOOK_SECRET`` (or ``META_APP_SECRET`` as fallback)
     when configured. Empty secret → signature check is skipped so dev
     fixtures stay simple. Mismatch → 400.
  2. Parse the payload into one or more ``MetaLead`` dataclasses.
  3. For each lead, insert a row into ``MetaLeadEvent`` (PK leadgen_id) for
     idempotency. Duplicates short-circuit with 200 and no Lead changes.
  4. Call ``ingest_meta_lead`` to upsert the Lead and write an
     ``lead.meta_ingested`` AuditEvent.

Compliance hard stop (Master Blueprint §26 #4): we persist Meta's payload
verbatim into ``Lead.raw_source_payload`` for later attribution, but we
never inject any of that text into AI prompts. Any future prompt-builder
must pull medical content only from ``apps.compliance.Claim``.
"""
from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .integrations.meta_client import (
    parse_lead_payload,
    verify_subscription_challenge,
    verify_webhook_signature,
)
from .models import MetaLeadEvent
from .services import ingest_meta_lead


class MetaLeadsWebhookView(APIView):
    """``/api/webhooks/meta/leads/`` — Meta Lead Ads verification + delivery."""

    permission_classes = [AllowAny]
    authentication_classes: list = []  # public — auth comes from token / signature

    # ----- GET: subscription verification handshake -----

    def get(self, request):
        mode = request.query_params.get("hub.mode") or ""
        token = request.query_params.get("hub.verify_token") or ""
        challenge = request.query_params.get("hub.challenge") or ""

        echoed = verify_subscription_challenge(
            mode=mode, token=token, challenge=challenge
        )
        if echoed is None:
            return Response({"detail": "verification failed"}, status=403)
        # Meta expects the challenge body back verbatim (text/plain). DRF
        # will still send JSON content-type but the integer/text body is
        # what Meta checks against.
        return Response(echoed, status=200)

    # ----- POST: lead delivery -----

    def post(self, request):
        body = request.body or b""

        # Signature is enforced only when a secret is configured. Local dev
        # / mock mode default leaves both secrets empty so test fixtures
        # don't need to sign every request.
        webhook_secret = getattr(settings, "META_WEBHOOK_SECRET", "") or ""
        app_secret = getattr(settings, "META_APP_SECRET", "") or ""
        secret = webhook_secret or app_secret
        if secret:
            signature = (
                request.META.get("HTTP_X_HUB_SIGNATURE_256")
                or request.META.get("HTTP_X_HUB_SIGNATURE")
                or ""
            )
            if not verify_webhook_signature(body, signature, secret=secret):
                return Response({"detail": "invalid signature"}, status=400)

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=400)

        leads = parse_lead_payload(payload)
        if not leads:
            return Response({"detail": "no leads", "ingested": 0}, status=200)

        results: list[dict[str, Any]] = []
        for meta_lead in leads:
            results.append(_process_one_lead(meta_lead))
        return Response(
            {"detail": "ok", "ingested": len(results), "leads": results},
            status=200,
        )


def _process_one_lead(meta_lead) -> dict[str, Any]:
    """Idempotent ingest for a single MetaLead dataclass."""
    # Idempotency: leadgen_id is the PK of MetaLeadEvent.
    try:
        with transaction.atomic():
            ingested_lead, action = ingest_meta_lead(meta_lead)
            MetaLeadEvent.objects.create(
                leadgen_id=meta_lead.leadgen_id,
                page_id=meta_lead.page_id,
                form_id=meta_lead.form_id,
                ad_id=meta_lead.ad_id,
                campaign_id=meta_lead.campaign_id,
                lead_id=ingested_lead.id,
                status=MetaLeadEvent.Status.OK,
                payload=dict(meta_lead.raw or {}),
            )
        return {
            "leadgenId": meta_lead.leadgen_id,
            "leadId": ingested_lead.id,
            "action": action,
        }
    except IntegrityError:
        # Duplicate leadgen_id — record was already processed.
        existing = MetaLeadEvent.objects.filter(leadgen_id=meta_lead.leadgen_id).first()
        return {
            "leadgenId": meta_lead.leadgen_id,
            "leadId": getattr(existing, "lead_id", "") or "",
            "action": "duplicate",
        }


__all__ = ("MetaLeadsWebhookView",)
