"""Phase 5D — Claim Vault coverage audit command.

Read-only. Prints a human-readable summary of approved Claim Vault
coverage by product / category and exits non-zero when any row is at
``missing`` / ``weak`` risk so CI can fail loudly.

Usage::

    python manage.py check_claim_vault_coverage
    python manage.py check_claim_vault_coverage --json
    python manage.py check_claim_vault_coverage --strict-weak  # exit 1 on weak too
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.compliance.coverage import build_coverage_report


class Command(BaseCommand):
    help = "Audit approved Claim Vault coverage for active products."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            dest="emit_json",
            help="Emit the coverage report as JSON instead of a table.",
        )
        parser.add_argument(
            "--strict-weak",
            action="store_true",
            dest="strict_weak",
            help=(
                "Exit non-zero when any product is at 'weak' risk "
                "(default only treats 'missing' as a failure)."
            ),
        )

    def handle(self, *args, **options) -> None:
        report = build_coverage_report()
        emit_json = bool(options.get("emit_json"))
        strict_weak = bool(options.get("strict_weak"))

        if emit_json:
            self.stdout.write(json.dumps(report.to_dict(), indent=2))
        else:
            self.stdout.write("Claim Vault coverage report")
            self.stdout.write("=" * 60)
            for item in report.items:
                badge = {
                    "ok": self.style.SUCCESS("ok"),
                    "weak": self.style.WARNING("weak"),
                    "missing": self.style.ERROR("missing"),
                }.get(item.risk, item.risk)
                self.stdout.write(
                    f"{badge:>10}  {item.product:<32}  approved={item.approved_claim_count}  "
                    f"usage={'no' if item.missing_required_usage_claims else 'yes'}  "
                    f"notes={','.join(item.notes) or '-'}"
                )
            self.stdout.write("-" * 60)
            self.stdout.write(
                f"total={report.total_products}  ok={report.ok_count}  "
                f"weak={report.weak_count}  missing={report.missing_count}"
            )

        # Exit code: missing always fails, weak optionally fails.
        if report.missing_count > 0 or (strict_weak and report.weak_count > 0):
            raise SystemExit(1)
