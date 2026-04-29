"""Phase 5E — Seed default / demo Claim Vault rows.

Idempotent. Seeds conservative, non-cure, non-guarantee phrases for the
eight current product categories so the WhatsApp AI Chat Agent and the
Phase 5D lifecycle ``usage_explanation`` template have at least *some*
Claim Vault grounding to test against in dev / demo environments.

LOCKED Phase 5E rules (Prarit, Apr 2026):
- The seeded claims are explicitly demo / default and are flagged as
  such via ``Claim.version="demo-v1"`` + ``Claim.compliance="Demo Default"``
  + ``Claim.doctor="Demo Default"``. The Phase 5D coverage report
  surfaces these rows with ``risk="demo_ok"`` and a note asking ops to
  replace them before full live rollout.
- Phrases avoid cure / guarantee / no-side-effects / doctor-not-needed
  language. Every demo claim explicitly recommends consulting a doctor
  for serious symptoms / pregnancy / ongoing illness.
- The command is idempotent. It refuses to overwrite existing rows
  unless ``--reset-demo`` is passed AND the existing row is itself a
  demo seed; production / admin-added rows are NEVER overwritten.

Usage::

    python manage.py seed_default_claims
    python manage.py seed_default_claims --reset-demo
    python manage.py seed_default_claims --json   # machine-readable
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.compliance.coverage import _is_demo_claim
from apps.compliance.models import Claim


SEED_DEMO_VERSION = "demo-v1"
SEED_DEMO_DOCTOR = "Demo Default"
SEED_DEMO_COMPLIANCE = "Demo Default"


# Ordered tuple — first entry per category becomes the canonical key
# matching customer.product_interest / category slug. Aliases stay
# under the same key so a search for any name resolves the same row.
DEFAULT_CLAIMS: tuple[dict[str, object], ...] = (
    {
        "product": "Weight Management",
        "approved": [
            "Supports general wellness as part of an Ayurvedic lifestyle routine.",
            "May support digestion and metabolism when used as directed alongside diet and lifestyle discipline.",
            "Take 1 capsule twice daily after meals with warm water unless your doctor advises otherwise.",
            "For serious symptoms, ongoing illness, pregnancy, or medication use, consult a qualified doctor.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "Doctor ki zarurat nahi",
            "100% cure",
        ],
    },
    {
        "product": "Blood Purification",
        "approved": [
            "Traditional Ayurvedic blend to support skin and overall wellness.",
            "Take 1 capsule twice daily after meals with warm water as directed.",
            "Supports lifestyle-led skin care; results vary by individual.",
            "If you have an active skin condition, ongoing illness, or are pregnant, consult a qualified doctor before starting.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "100% cure",
        ],
    },
    {
        "product": "Men Wellness",
        "approved": [
            "Ayurvedic supplement intended to support general wellness in men.",
            "Take 1 capsule twice daily after meals with warm water unless directed otherwise.",
            "Best used alongside balanced diet, sleep, and exercise.",
            "If you have a chronic condition, are on medication, or under 18, consult a qualified doctor first.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "100% cure",
        ],
    },
    {
        "product": "Women Wellness",
        "approved": [
            "Ayurvedic supplement designed to support general wellness in women.",
            "Take 1 capsule twice daily after meals with warm water unless directed otherwise.",
            "If you are pregnant, breastfeeding, planning pregnancy, or on medication, consult a qualified doctor first.",
            "Lifestyle, diet, and sleep matter alongside any supplement.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "100% cure",
        ],
    },
    {
        "product": "Immunity",
        "approved": [
            "Ayurvedic blend formulated to support general immunity.",
            "Take 1 capsule twice daily after meals with warm water as directed.",
            "Pair with rest, hydration, and a balanced diet for best results.",
            "For active infections, fever, or chronic illness, consult a qualified doctor.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "100% cure",
            "Replaces all medication",
        ],
    },
    {
        "product": "Lungs Detox",
        "approved": [
            "Traditional Ayurvedic blend to support general respiratory wellness.",
            "Take 1 capsule twice daily after meals with warm water unless directed otherwise.",
            "Avoid known irritants and consult a qualified doctor for ongoing breathing issues, asthma, or lung disease.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "100% cure",
        ],
    },
    {
        "product": "Body Detox",
        "approved": [
            "Ayurvedic supplement intended to support general body wellness routines.",
            "Take 1 capsule twice daily after meals with warm water as directed.",
            "Maintain hydration and a balanced diet alongside.",
            "Consult a qualified doctor before use if you have liver / kidney conditions, are pregnant, or take regular medication.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "100% cure",
        ],
    },
    {
        "product": "Joint Care",
        "approved": [
            "Ayurvedic blend formulated to support general joint wellness.",
            "Take 1 capsule twice daily after meals with warm water as directed.",
            "Combine with appropriate movement and rest as advised by your physician.",
            "For persistent pain, swelling, or post-surgical care, consult a qualified doctor first.",
        ],
        "disallowed": [
            "Guaranteed cure",
            "Permanent solution",
            "No side effects for everyone",
            "100% cure",
        ],
    },
)


class Command(BaseCommand):
    help = (
        "Seed conservative, non-cure default Claim Vault rows for the "
        "eight current product categories. Idempotent. Use --reset-demo "
        "to refresh existing demo seeds; admin-added real claims are "
        "never overwritten."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset-demo",
            action="store_true",
            dest="reset_demo",
            help=(
                "Refresh existing demo / default rows. Real admin-added "
                "Claim rows are still never overwritten."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="emit_json",
            help="Emit a JSON summary instead of human-readable output.",
        )

    def handle(self, *args, **options) -> None:
        reset_demo = bool(options.get("reset_demo"))
        emit_json = bool(options.get("emit_json"))

        created: list[str] = []
        updated: list[str] = []
        skipped: list[str] = []
        protected: list[str] = []

        for entry in DEFAULT_CLAIMS:
            product = str(entry["product"])
            approved = list(entry.get("approved") or [])
            disallowed = list(entry.get("disallowed") or [])
            existing = Claim.objects.filter(product=product).first()
            if existing is None:
                Claim.objects.create(
                    product=product,
                    approved=approved,
                    disallowed=disallowed,
                    doctor=SEED_DEMO_DOCTOR,
                    compliance=SEED_DEMO_COMPLIANCE,
                    version=SEED_DEMO_VERSION,
                )
                created.append(product)
                continue

            if not _is_demo_claim(existing):
                # Real admin / doctor-approved row — never touch.
                protected.append(product)
                continue

            if not reset_demo:
                skipped.append(product)
                continue

            existing.approved = approved
            existing.disallowed = disallowed
            existing.doctor = SEED_DEMO_DOCTOR
            existing.compliance = SEED_DEMO_COMPLIANCE
            existing.version = SEED_DEMO_VERSION
            existing.save(
                update_fields=[
                    "approved",
                    "disallowed",
                    "doctor",
                    "compliance",
                    "version",
                ]
            )
            updated.append(product)

        write_event(
            kind="compliance.default_claims.seeded",
            text=(
                f"Default Claim Vault seeded · created={len(created)} "
                f"updated={len(updated)} skipped={len(skipped)} "
                f"protected={len(protected)}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "protected": protected,
                "reset_demo": reset_demo,
                "version": SEED_DEMO_VERSION,
                "at": timezone.now().isoformat(),
            },
        )

        summary = {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "protected": protected,
            "resetDemo": reset_demo,
        }
        if emit_json:
            self.stdout.write(json.dumps(summary, indent=2))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Default Claim Vault seed complete. "
            f"created={len(created)} updated={len(updated)} "
            f"skipped(demo)={len(skipped)} protected(real)={len(protected)}"
        ))
        for label, items in (
            ("created", created),
            ("updated", updated),
            ("skipped (demo, no --reset-demo)", skipped),
            ("protected (real claim — never overwritten)", protected),
        ):
            if items:
                self.stdout.write(f"  {label}: {', '.join(items)}")
