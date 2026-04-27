"""Meta Lead Ads adapter.

Three modes, selected by ``settings.META_MODE``:

- ``mock`` — parse the inbound webhook payload as-is using only the values
  the caller already sent. No network. Default for local dev and CI.
- ``test`` — parse the webhook ids out of the payload, then call Meta's
  Graph API to expand the lead (``GET /{leadgen_id}?access_token=...``).
  Requires ``META_PAGE_ACCESS_TOKEN``.
- ``live`` — same path as ``test`` against production. Set explicitly via
  env; never the default.

Tests patch ``_fetch_lead_via_graph`` (or set ``META_MODE=mock``) so the
real Graph API is never called from the test suite.

Compliance hard stop (Master Blueprint §26 #4): leads carry only the
metadata Meta gave us. No medical claim text is ever attached. Any future
prompt-builder MUST pull from ``apps.compliance.Claim``.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from django.conf import settings


class MetaClientError(Exception):
    """Raised when the underlying Graph call or configuration fails."""


@dataclass(frozen=True)
class MetaLead:
    """Normalised Meta Lead Ads payload — what the service layer wants."""

    leadgen_id: str
    page_id: str
    form_id: str
    ad_id: str
    campaign_id: str
    name: str
    phone: str
    email: str
    state: str
    city: str
    product_interest: str
    language: str
    source_detail: str
    raw: dict[str, Any]


# ----- Webhook signature verification (Meta uses sha256=<hex> in X-Hub-Signature-256) -----


def verify_webhook_signature(body: bytes, signature_header: str, secret: str | None = None) -> bool:
    """HMAC-SHA256 check for Meta's ``X-Hub-Signature-256`` header.

    Meta sends ``X-Hub-Signature-256: sha256=<hex>`` where the digest is
    ``HMAC_SHA256(app_secret, raw_body)``. ``META_WEBHOOK_SECRET`` overrides
    ``META_APP_SECRET`` if both are set, so dev fixtures can pin a known
    secret without touching the real app credentials.

    A missing secret or signature returns ``False``.
    """
    if secret is None:
        secret = (
            getattr(settings, "META_WEBHOOK_SECRET", "")
            or getattr(settings, "META_APP_SECRET", "")
            or ""
        )
    if not secret or not signature_header:
        return False
    if signature_header.startswith("sha256="):
        provided = signature_header.split("=", 1)[1]
    else:
        provided = signature_header
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, provided)


# ----- Verification challenge (GET) -----


def verify_subscription_challenge(
    *,
    mode: str,
    token: str,
    challenge: str,
    expected_token: str | None = None,
) -> str | None:
    """Return the challenge string when Meta's verification handshake passes.

    Meta sends ``GET ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...``.
    We answer with the challenge body when ``hub.mode == "subscribe"`` and the
    token matches ``META_VERIFY_TOKEN``. Returning ``None`` tells the view to
    respond ``403``.
    """
    if expected_token is None:
        expected_token = getattr(settings, "META_VERIFY_TOKEN", "") or ""
    if mode != "subscribe" or not expected_token:
        return None
    if not hmac.compare_digest(token or "", expected_token):
        return None
    return challenge or ""


# ----- Lead extraction -----


def parse_lead_payload(payload: dict[str, Any]) -> list[MetaLead]:
    """Walk the ``entry[].changes[].value`` tree and yield one MetaLead per
    leadgen entry.

    Real Meta deliveries look like::

        {
          "object": "page",
          "entry": [
            {
              "id": "<page-id>",
              "changes": [
                {"field": "leadgen", "value": {
                  "leadgen_id": "...", "form_id": "...", "ad_id": "...",
                  "campaign_id": "...", "page_id": "...",
                  "field_data": [
                    {"name": "full_name", "values": ["Rajesh Kumar"]},
                    {"name": "phone_number", "values": ["+91 9000000000"]},
                    ...
                  ]
                }}
              ]
            }
          ]
        }

    For mock / test fixtures we also accept the ``value`` block directly so
    tests don't have to wrap every payload in ``entry[].changes[]``.
    """
    leads: list[MetaLead] = []
    entries = payload.get("entry") or []

    if not entries and isinstance(payload.get("changes"), list):
        # Test fixture pattern: caller sent ``{"changes": [...]}`` directly.
        entries = [{"id": payload.get("page_id", ""), "changes": payload["changes"]}]

    if not entries and (
        payload.get("leadgen_id")
        or (payload.get("value") or {}).get("leadgen_id")
    ):
        # Test fixture pattern: caller sent the change ``value`` directly.
        value = payload.get("value") or payload
        entries = [{"id": value.get("page_id", ""), "changes": [{"field": "leadgen", "value": value}]}]

    for entry in entries:
        page_id = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            if (change.get("field") or "").lower() != "leadgen":
                continue
            value = change.get("value") or {}
            if not value:
                continue
            mock_value = _extract_mock_lead(value, page_id=page_id)
            if mock_value is not None:
                leads.append(mock_value)
    return leads


def _extract_mock_lead(value: dict[str, Any], *, page_id: str) -> MetaLead | None:
    """Pull a MetaLead out of a change ``value`` block (mock-mode happy path).

    Test/live mode uses ``_fetch_lead_via_graph`` to expand ids into the same
    dataclass via the Graph API.
    """
    leadgen_id = str(value.get("leadgen_id") or "")
    if not leadgen_id:
        return None

    field_data: list[dict[str, Any]] = list(value.get("field_data") or [])
    fields = {
        (entry.get("name") or "").lower(): entry.get("values") or []
        for entry in field_data
        if isinstance(entry, dict)
    }

    def _take(*names: str) -> str:
        for name in names:
            values = fields.get(name)
            if values:
                return str(values[0])
        return ""

    name = _take("full_name", "name", "first_name") or _take("first_name") + " " + _take(
        "last_name"
    )
    name = name.strip()

    return MetaLead(
        leadgen_id=leadgen_id,
        page_id=str(value.get("page_id") or page_id or ""),
        form_id=str(value.get("form_id") or ""),
        ad_id=str(value.get("ad_id") or ""),
        campaign_id=str(value.get("campaign_id") or ""),
        name=name,
        phone=_take("phone_number", "phone"),
        email=_take("email"),
        state=_take("state", "region"),
        city=_take("city"),
        product_interest=_take(
            "product_interest", "interested_product", "product"
        ),
        language=_take("language") or "Hinglish",
        source_detail=str(value.get("ad_id") or value.get("form_id") or "Meta Ads"),
        raw=dict(value),
    )


# ----- Graph API expansion (test / live) -----


def expand_lead(meta_lead: MetaLead) -> MetaLead:
    """In ``test`` / ``live`` mode, fetch the full lead via Graph API and
    return a refreshed dataclass. ``mock`` mode short-circuits to the input.

    Tests patch ``_fetch_lead_via_graph`` so this never hits the network.
    """
    mode = (getattr(settings, "META_MODE", "mock") or "mock").lower()
    if mode == "mock":
        return meta_lead
    if mode in {"test", "live"}:
        graph_payload = _fetch_lead_via_graph(meta_lead.leadgen_id)
        # The Graph response carries ``field_data`` exactly like the webhook,
        # so we re-run the mock extractor against it.
        synthetic = {
            "leadgen_id": meta_lead.leadgen_id,
            "page_id": meta_lead.page_id,
            "form_id": meta_lead.form_id,
            "ad_id": meta_lead.ad_id,
            "campaign_id": meta_lead.campaign_id,
            "field_data": graph_payload.get("field_data", []),
        }
        refreshed = _extract_mock_lead(synthetic, page_id=meta_lead.page_id)
        return refreshed or meta_lead
    raise MetaClientError(f"Unknown META_MODE: {mode!r}")


def _fetch_lead_via_graph(leadgen_id: str) -> dict[str, Any]:
    """Call ``GET /{leadgen_id}`` on the Graph API. Imported lazily so mock
    mode never needs the ``requests`` package.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - missing-dep path
        raise MetaClientError(
            "requests is not installed; run `pip install requests` "
            "or set META_MODE=mock."
        ) from exc

    token = getattr(settings, "META_PAGE_ACCESS_TOKEN", "") or ""
    api_version = getattr(settings, "META_GRAPH_API_VERSION", "v20.0") or "v20.0"
    if not token:
        raise MetaClientError(
            "META_PAGE_ACCESS_TOKEN not configured (mode=test/live)."
        )

    url = f"https://graph.facebook.com/{api_version}/{leadgen_id}"
    try:
        response = requests.get(url, params={"access_token": token}, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # pragma: no cover - real-network path
        raise MetaClientError(f"Meta Graph API error: {exc}") from exc


__all__ = (
    "MetaClientError",
    "MetaLead",
    "verify_webhook_signature",
    "verify_subscription_challenge",
    "parse_lead_payload",
    "expand_lead",
)
