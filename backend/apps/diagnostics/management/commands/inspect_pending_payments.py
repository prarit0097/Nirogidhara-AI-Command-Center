"""Phase 10A — CLI: inspect pending payments drilldown.

Pretty-prints the same rows that the
``/api/v1/diagnostics/pending-payments/`` endpoint returns. Useful
for SSH / cron debugging. READ-ONLY — never mutates state, never
calls a provider.
"""
from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand

from apps.diagnostics.service import (
    DEFAULT_LIMIT,
    list_pending_payments_drilldown,
)


COLUMNS = (
    ("payment_id", "Payment"),
    ("payment_status", "Status"),
    ("amount", "Amount"),
    ("days_since_creation", "Days"),
    ("order_id", "Order"),
    ("order_state", "State"),
    ("order_status", "Stage"),
    ("customer_name", "Customer"),
    ("customer_phone", "Phone"),
    ("last_whatsapp_at", "Last WA"),
    ("last_call_at", "Last Call"),
    ("last_call_outcome", "Call Status"),
)


def _format_cell(value: Any) -> str:
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


class Command(BaseCommand):
    help = (
        "Read-only inspector for pending payments. Lists Payment rows "
        "with status Pending (+ Partial by default) joined with order, "
        "customer, and last-comm metadata."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--include-partial",
            dest="include_partial",
            action="store_true",
            default=True,
        )
        parser.add_argument(
            "--no-include-partial",
            dest="include_partial",
            action="store_false",
        )
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        parser.add_argument(
            "--state",
            default=None,
            help="Optional case-insensitive Order.state filter.",
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options) -> None:
        rows = list_pending_payments_drilldown(
            include_partial=bool(options.get("include_partial", True)),
            limit=int(options.get("limit") or DEFAULT_LIMIT),
            state_filter=options.get("state"),
        )
        if options.get("json"):
            self.stdout.write(json.dumps(rows, default=str))
            return
        if not rows:
            self.stdout.write("No pending payments found.")
            return
        # Pretty plain-text table — keeps the output operator-friendly
        # without pulling in a tabulate dependency.
        header = " | ".join(label for _, label in COLUMNS)
        self.stdout.write(header)
        self.stdout.write("-" * min(len(header), 200))
        for row in rows:
            self.stdout.write(
                " | ".join(_format_cell(row.get(key)) for key, _ in COLUMNS)
            )
        self.stdout.write(
            f"\nTotal: {len(rows)} pending payment(s) (read-only)."
        )
