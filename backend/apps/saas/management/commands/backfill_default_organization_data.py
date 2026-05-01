"""``python manage.py backfill_default_organization_data --dry-run|--apply --json``.

Phase 6B — Default Org Data Backfill Plan.

Idempotently sets ``organization`` (and ``branch`` where the model has
that field) on every existing business-state row to the seeded default
``nirogidhara`` org. Defaults to ``--dry-run``; ``--apply`` is required
for any DB writes.

LOCKED rules:

- ``--dry-run`` is the default. No DB writes unless ``--apply`` is set.
- Only updates rows where the field is NULL — NEVER overwrites an
  existing org / branch assignment.
- NEVER mutates business state (no status / amount / phone / payload
  changes). Touches only the new ``organization_id`` / ``branch_id``
  columns added in Phase 6B.
- NEVER calls a provider API.
- NEVER writes a customer-facing message.
- Idempotent: running twice produces the same end state; the second
  run reports zero rows updated.
- Writes ``saas.default_org_backfill.{started,completed,failed}``
  audit rows so the operator can correlate the backfill with deploys.
"""
from __future__ import annotations

import json as _json
import traceback
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from apps.saas.models import Branch, Organization
from apps.saas.selectors import (
    DEFAULT_BRANCH_CODE,
    DEFAULT_ORGANIZATION_CODE,
)


# Each tuple: ``(label, model_path, has_branch)``.
# Order matters only for clarity; backfills run in this listing order.
_TARGETS: tuple[tuple[str, str, bool], ...] = (
    ("crm.Lead", "crm.Lead", True),
    ("crm.Customer", "crm.Customer", True),
    ("orders.Order", "orders.Order", True),
    ("orders.DiscountOfferLog", "orders.DiscountOfferLog", False),
    ("payments.Payment", "payments.Payment", True),
    ("shipments.Shipment", "shipments.Shipment", True),
    ("calls.Call", "calls.Call", True),
    ("whatsapp.WhatsAppConsent", "whatsapp.WhatsAppConsent", False),
    ("whatsapp.WhatsAppConversation", "whatsapp.WhatsAppConversation", True),
    ("whatsapp.WhatsAppMessage", "whatsapp.WhatsAppMessage", False),
    (
        "whatsapp.WhatsAppLifecycleEvent",
        "whatsapp.WhatsAppLifecycleEvent",
        False,
    ),
    (
        "whatsapp.WhatsAppHandoffToCall",
        "whatsapp.WhatsAppHandoffToCall",
        False,
    ),
    (
        "whatsapp.WhatsAppPilotCohortMember",
        "whatsapp.WhatsAppPilotCohortMember",
        False,
    ),
    ("audit.AuditEvent", "audit.AuditEvent", False),
)


def _resolve_model(label: str):
    from django.apps import apps

    app_label, model_name = label.split(".", 1)
    return apps.get_model(app_label, model_name)


def _ensure_default_org_and_branch() -> tuple[Organization, Branch | None]:
    """Reuse the Phase 6A seeder logic but skip membership writes here.

    Membership creation is idempotent and harmless, but the backfill
    command's job is data scoping — keeping it focused makes the audit
    trail cleaner.
    """
    org = Organization.objects.filter(code=DEFAULT_ORGANIZATION_CODE).first()
    if org is None:
        org = Organization.objects.create(
            code=DEFAULT_ORGANIZATION_CODE,
            name="Nirogidhara Private Limited",
            legal_name="Nirogidhara Private Limited",
            status=Organization.Status.ACTIVE,
            timezone="Asia/Kolkata",
            country="IN",
            metadata={"seededBy": "backfill_default_organization_data"},
        )
    branch = Branch.objects.filter(
        organization=org, code=DEFAULT_BRANCH_CODE
    ).first()
    if branch is None:
        branch = Branch.objects.create(
            organization=org,
            code=DEFAULT_BRANCH_CODE,
            name="Main Branch",
            status=Branch.Status.ACTIVE,
            metadata={"seededBy": "backfill_default_organization_data"},
        )
    return org, branch


class Command(BaseCommand):
    help = (
        "Idempotently scope every existing business-state row to the "
        "seeded default organization (and main branch where applicable). "
        "Defaults to --dry-run; pass --apply to actually write."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the org/branch assignments.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing (default).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        apply_flag = bool(options.get("apply"))
        dry_run = not apply_flag  # default: dry run unless --apply set

        org, branch = _ensure_default_org_and_branch()

        write_event(
            kind="saas.default_org_backfill.started",
            text=(
                f"Default-org backfill started · "
                f"mode={'apply' if apply_flag else 'dry_run'}"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "organization_id": org.id,
                "organization_code": org.code,
                "branch_id": branch.id if branch else None,
                "branch_code": branch.code if branch else "",
                "mode": "apply" if apply_flag else "dry_run",
            },
        )

        report: dict[str, Any] = {
            "passed": False,
            "dryRun": dry_run,
            "organizationId": org.id,
            "organizationCode": org.code,
            "branchId": branch.id if branch else None,
            "branchCode": branch.code if branch else "",
            "models": [],
            "totalRows": 0,
            "totalWouldUpdateOrganization": 0,
            "totalUpdatedOrganization": 0,
            "totalWouldUpdateBranch": 0,
            "totalUpdatedBranch": 0,
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        try:
            for label, model_path, has_branch in _TARGETS:
                try:
                    model = _resolve_model(model_path)
                except LookupError as exc:
                    report["warnings"].append(
                        f"{label}: model not found ({exc})"
                    )
                    continue

                qs = model.objects.all()
                total = qs.count()
                missing_org_qs = qs.filter(organization__isnull=True)
                missing_org = missing_org_qs.count()
                already_org = total - missing_org

                missing_branch = 0
                already_branch = 0
                if has_branch:
                    missing_branch_qs = qs.filter(branch__isnull=True)
                    missing_branch = missing_branch_qs.count()
                    already_branch = total - missing_branch

                row: dict[str, Any] = {
                    "model": label,
                    "totalRows": total,
                    "alreadyWithOrganization": already_org,
                    "missingOrganization": missing_org,
                    "wouldUpdateOrganization": missing_org if dry_run else 0,
                    "updatedOrganization": 0,
                    "hasBranchField": has_branch,
                    "alreadyWithBranch": already_branch,
                    "missingBranch": missing_branch,
                    "wouldUpdateBranch": (
                        missing_branch if (dry_run and has_branch) else 0
                    ),
                    "updatedBranch": 0,
                }

                if not dry_run and missing_org:
                    with transaction.atomic():
                        updated_org = missing_org_qs.update(
                            organization=org
                        )
                    row["updatedOrganization"] = updated_org
                    report["totalUpdatedOrganization"] += updated_org

                if not dry_run and has_branch and missing_branch:
                    with transaction.atomic():
                        # Re-filter on branch__isnull only (org may
                        # already have been set above; we still want
                        # to scope branch only on rows where it's NULL).
                        updated_branch = (
                            qs.filter(branch__isnull=True).update(
                                branch=branch
                            )
                        )
                    row["updatedBranch"] = updated_branch
                    report["totalUpdatedBranch"] += updated_branch

                report["models"].append(row)
                report["totalRows"] += total
                report["totalWouldUpdateOrganization"] += (
                    row["wouldUpdateOrganization"]
                )
                report["totalWouldUpdateBranch"] += row[
                    "wouldUpdateBranch"
                ]

            report["passed"] = True

            if dry_run:
                if report["totalWouldUpdateOrganization"] == 0 and (
                    report["totalWouldUpdateBranch"] == 0
                ):
                    report["nextAction"] = (
                        "ready_for_phase_6c_org_scoped_api_filtering_plan"
                    )
                else:
                    report["nextAction"] = (
                        "run_backfill_default_organization_data_apply"
                    )
            else:
                if report["totalUpdatedOrganization"] == 0 and (
                    report["totalUpdatedBranch"] == 0
                ):
                    report["nextAction"] = (
                        "ready_for_phase_6c_org_scoped_api_filtering_plan"
                    )
                else:
                    report["nextAction"] = (
                        "rerun_inspect_default_organization_coverage"
                    )

            write_event(
                kind="saas.default_org_backfill.completed",
                text=(
                    f"Default-org backfill completed · "
                    f"mode={'apply' if apply_flag else 'dry_run'} · "
                    f"updated_org={report['totalUpdatedOrganization']} "
                    f"updated_branch={report['totalUpdatedBranch']}"
                ),
                tone=AuditEvent.Tone.SUCCESS,
                payload={
                    "organization_id": org.id,
                    "organization_code": org.code,
                    "branch_id": branch.id if branch else None,
                    "mode": "apply" if apply_flag else "dry_run",
                    "total_rows": report["totalRows"],
                    "total_updated_org": report["totalUpdatedOrganization"],
                    "total_updated_branch": report["totalUpdatedBranch"],
                    "total_would_update_org": (
                        report["totalWouldUpdateOrganization"]
                    ),
                    "total_would_update_branch": (
                        report["totalWouldUpdateBranch"]
                    ),
                    "next_action": report["nextAction"],
                },
            )
        except Exception as exc:  # noqa: BLE001 - explicitly recorded
            report["errors"].append(str(exc))
            report["nextAction"] = "fix_backfill_blockers"
            write_event(
                kind="saas.default_org_backfill.failed",
                text=(
                    f"Default-org backfill failed · {exc.__class__.__name__}"
                ),
                tone=AuditEvent.Tone.DANGER,
                payload={
                    "organization_id": org.id,
                    "mode": "apply" if apply_flag else "dry_run",
                    "error": str(exc),
                    "trace": traceback.format_exc()[:1200],
                },
            )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        mode = "DRY-RUN" if report["dryRun"] else "APPLY"
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Default-org backfill ({mode})"
            )
        )
        self.stdout.write(
            f"  organization : {report['organizationCode']} "
            f"(id={report['organizationId']})"
        )
        self.stdout.write(
            f"  branch       : {report['branchCode']} "
            f"(id={report['branchId']})"
        )
        for row in report["models"]:
            verb = "would_update" if report["dryRun"] else "updated"
            self.stdout.write(
                f"  - {row['model']:<40} "
                f"total={row['totalRows']:<6} "
                f"missing_org={row['missingOrganization']:<6} "
                f"{verb}_org={row.get('wouldUpdateOrganization' if report['dryRun'] else 'updatedOrganization'):<6} "
                + (
                    f"missing_branch={row['missingBranch']:<6} "
                    f"{verb}_branch={row.get('wouldUpdateBranch' if report['dryRun'] else 'updatedBranch'):<6}"
                    if row["hasBranchField"]
                    else "branch=n/a"
                )
            )
        if report["warnings"]:
            self.stdout.write(self.style.WARNING("warnings:"))
            for w in report["warnings"]:
                self.stdout.write(f"  - {w}")
        if report["errors"]:
            self.stdout.write(self.style.ERROR("errors:"))
            for e in report["errors"]:
                self.stdout.write(f"  - {e}")
        self.stdout.write(f"nextAction: {report['nextAction']}")
