"""Phase 5D — Claim Vault coverage audit.

Reports approved Claim Vault coverage by product / category. Used by:

- The new ``GET /api/compliance/claim-coverage/`` endpoint (admin/director).
- The ``check_claim_vault_coverage`` management command (CI / nightly).
- The Phase 5D WhatsApp lifecycle service when sending a product-specific
  template — if ``has_approved_claims`` is False the lifecycle gate fails
  closed and routes to an internal note instead of a customer message.

The coverage report is read-only. No mutations. No audit rows for the
read path; the API layer can opt to write a single
``compliance.claim_coverage.checked`` audit when the coverage check is
the action being audited.

Risk levels:
- ``ok``      — at least one approved phrase + at least one usage / key
                lifecycle hint covered for the relevant product.
- ``weak``    — Claim row exists but ``approved`` list is empty OR no
                lifecycle-required keyword appears in any approved phrase.
- ``missing`` — no Claim row found for the product / category at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from django.db.models import Q

from apps.compliance.models import Claim


# Phrases the lifecycle templates rely on. If at least one approved
# phrase mentions one of these keywords for a product, we mark the
# product "ok" for usage / dosage messaging. The list is intentionally
# loose — Claim Vault rows are doctor-reviewed and free-text, so we
# don't try to parse the language model's vocabulary, we just want a
# trip-wire that says "doctor wrote *something* about how to use it".
USAGE_HINT_KEYWORDS: tuple[str, ...] = (
    # Dosage / form keywords.
    "capsule",
    "capsules",
    "dose",
    "dosage",
    "take",
    "intake",
    "morning",
    "evening",
    "after meal",
    "before meal",
    "warm water",
    "milk",
    "ayurveda",
    "ayurvedic",
    "blend",
    "supplement",
    # Phase 5E-Hotfix-2 — explicit usage-guidance phrases used by the
    # demo Claim Vault seed. These let the coverage detector recognise
    # "use as directed on the label" / "consult a practitioner" / etc.
    # as a usage hint without forcing the demo phrase to repeat
    # capsule/dose wording verbatim.
    "directed",
    "label",
    "practitioner",
    "hydration",
    "balanced diet",
    "routine",
    "discontinue",
    "professional advice",
    "unusual reaction",
)


@dataclass(frozen=True)
class ClaimVaultCoverageItem:
    """Single coverage row, one per product / category bucket."""

    product: str
    category: str
    approved_claim_count: int
    has_approved_claims: bool
    missing_required_usage_claims: bool
    last_approved_at: str  # ISO string; empty when no Claim row exists
    risk: str  # "ok" | "weak" | "missing" | "demo_ok"
    notes: tuple[str, ...] = field(default_factory=tuple)
    is_demo_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "category": self.category,
            "approvedClaimCount": self.approved_claim_count,
            "hasApprovedClaims": self.has_approved_claims,
            "missingRequiredUsageClaims": self.missing_required_usage_claims,
            "lastApprovedAt": self.last_approved_at,
            "risk": self.risk,
            "notes": list(self.notes),
            "isDemoDefault": self.is_demo_default,
        }


@dataclass(frozen=True)
class ClaimVaultCoverageReport:
    """Aggregate coverage report."""

    items: tuple[ClaimVaultCoverageItem, ...]
    total_products: int
    ok_count: int
    weak_count: int
    missing_count: int

    @property
    def demo_count(self) -> int:
        return sum(1 for item in self.items if item.is_demo_default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalProducts": self.total_products,
            "okCount": self.ok_count,
            "weakCount": self.weak_count,
            "missingCount": self.missing_count,
            "demoCount": self.demo_count,
            "items": [item.to_dict() for item in self.items],
        }


def _looks_like_usage(phrases: Iterable[str]) -> bool:
    haystack = " ".join((p or "").lower() for p in phrases)
    if not haystack:
        return False
    return any(keyword in haystack for keyword in USAGE_HINT_KEYWORDS)


DEMO_CLAIM_MARKERS: tuple[str, ...] = (
    "demo-v",  # version field marker — e.g. "demo-v1"
    "Demo Default",  # doctor / compliance fields marker
)


def _is_demo_claim(claim: Claim) -> bool:
    """Detect whether a Claim row was sown by the Phase 5E default seed."""
    fields = (
        (claim.version or ""),
        (claim.doctor or ""),
        (claim.compliance or ""),
    )
    return any(
        marker.lower() in (value or "").lower()
        for marker in DEMO_CLAIM_MARKERS
        for value in fields
    )


def _coverage_for_claim(claim: Claim, *, category: str = "") -> ClaimVaultCoverageItem:
    approved = list(claim.approved or [])
    approved_count = len(approved)
    has_approved = approved_count > 0
    has_usage = _looks_like_usage(approved)
    is_demo = _is_demo_claim(claim)
    notes: list[str] = []
    if not has_approved:
        notes.append("approved_list_empty")
    if has_approved and not has_usage:
        notes.append("missing_usage_hint")
    if is_demo:
        notes.append(
            "demo default claim; replace with doctor-approved final claim "
            "before full live rollout"
        )
    last_approved_at = (
        claim.updated_at.isoformat() if claim.updated_at and has_approved else ""
    )
    if not has_approved:
        risk = "missing"
    elif not has_usage:
        risk = "weak"
    elif is_demo:
        risk = "demo_ok"
    else:
        risk = "ok"
    return ClaimVaultCoverageItem(
        product=claim.product,
        category=category or claim.product,
        approved_claim_count=approved_count,
        has_approved_claims=has_approved,
        missing_required_usage_claims=not has_usage,
        last_approved_at=last_approved_at,
        risk=risk,
        notes=tuple(notes),
        is_demo_default=is_demo,
    )


def build_coverage_report() -> ClaimVaultCoverageReport:
    """Build the full Claim Vault coverage report."""
    items: list[ClaimVaultCoverageItem] = []
    for claim in Claim.objects.all().order_by("product"):
        items.append(_coverage_for_claim(claim))

    # Optional: surface catalog Products that have no Claim row at all.
    # We don't import catalog at module load to keep the dependency one-way.
    try:
        from apps.catalog.models import Product

        existing_keys = {item.product.lower() for item in items}
        catalog_qs = Product.objects.filter(is_active=True).select_related("category")
        for product in catalog_qs:
            keys: list[str] = []
            for raw_key in product.active_claim_products or []:
                if isinstance(raw_key, str) and raw_key:
                    keys.append(raw_key)
            keys.append(product.name)
            covered = any(key.lower() in existing_keys for key in keys)
            if covered:
                continue
            items.append(
                ClaimVaultCoverageItem(
                    product=product.name,
                    category=getattr(product.category, "name", "") or product.name,
                    approved_claim_count=0,
                    has_approved_claims=False,
                    missing_required_usage_claims=True,
                    last_approved_at="",
                    risk="missing",
                    notes=("no_claim_row_for_active_product",),
                )
            )
    except Exception:  # noqa: BLE001 - catalog optional at audit time
        pass

    ok = sum(1 for item in items if item.risk in {"ok", "demo_ok"})
    weak = sum(1 for item in items if item.risk == "weak")
    missing = sum(1 for item in items if item.risk == "missing")

    return ClaimVaultCoverageReport(
        items=tuple(items),
        total_products=len(items),
        ok_count=ok,
        weak_count=weak,
        missing_count=missing,
    )


def coverage_for_product(product_or_category: str) -> ClaimVaultCoverageItem:
    """Return coverage for a single product / category lookup.

    Used by the lifecycle service: if the gate's product key resolves to
    a Claim row with ``has_approved_claims=True`` the lifecycle send may
    proceed; otherwise it fails closed.
    """
    key = (product_or_category or "").strip()
    if not key:
        return ClaimVaultCoverageItem(
            product="",
            category="",
            approved_claim_count=0,
            has_approved_claims=False,
            missing_required_usage_claims=True,
            last_approved_at="",
            risk="missing",
            notes=("empty_product_key",),
        )
    claim = (
        Claim.objects.filter(Q(product__iexact=key))
        .first()
        or Claim.objects.filter(product__icontains=key).first()
    )
    if claim is None:
        return ClaimVaultCoverageItem(
            product=key,
            category=key,
            approved_claim_count=0,
            has_approved_claims=False,
            missing_required_usage_claims=True,
            last_approved_at="",
            risk="missing",
            notes=("no_claim_row",),
        )
    return _coverage_for_claim(claim, category=key)


__all__ = (
    "ClaimVaultCoverageItem",
    "ClaimVaultCoverageReport",
    "USAGE_HINT_KEYWORDS",
    "build_coverage_report",
    "coverage_for_product",
)
