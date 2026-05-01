"""``python manage.py ensure_default_organization --json``.

Phase 6A — SaaS Foundation Safe Migration.

Idempotent seeder for the default organization + branch. Creates exactly
one ``Organization(code='nirogidhara')`` + one ``Branch(code='main')``
under it, then attaches every superuser as ``owner`` and every
admin/director user as ``admin`` so existing operators inherit a working
membership without any manual click-ops.

LOCKED rules:

- Idempotent — safe to re-run; never duplicates.
- NEVER mutates ``Customer`` / ``Order`` / ``Payment`` / ``Shipment``
  / ``DiscountOfferLog`` / ``WhatsAppMessage`` / ``WhatsAppConversation``.
- NEVER touches WhatsApp env flags or any provider settings.
- NEVER prints secrets.
- Writes one ``saas.default_organization.ensured`` audit row per run so
  the operator can correlate the seed with deploys.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from apps.saas.models import (
    Branch,
    Organization,
    OrganizationMembership,
)
from apps.saas.selectors import (
    DEFAULT_BRANCH_CODE,
    DEFAULT_BRANCH_NAME,
    DEFAULT_ORGANIZATION_CODE,
    DEFAULT_ORGANIZATION_LEGAL_NAME,
    DEFAULT_ORGANIZATION_NAME,
)


class Command(BaseCommand):
    help = (
        "Idempotent seeder for the default SaaS organization + branch. "
        "Safe to run on every deploy; never mutates business data."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")
        parser.add_argument(
            "--skip-memberships",
            action="store_true",
            help=(
                "Skip auto-attaching superusers/admin users as default "
                "memberships. Useful for tests."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        report: dict[str, Any] = {
            "passed": False,
            "organizationId": 0,
            "organizationCode": DEFAULT_ORGANIZATION_CODE,
            "branchId": 0,
            "branchCode": DEFAULT_BRANCH_CODE,
            "createdOrganization": False,
            "createdBranch": False,
            "membershipsCreated": 0,
            "membershipsSkipped": False,
            "warnings": [],
            "nextAction": "",
        }

        # --- Organization ---------------------------------------------
        org, created_org = Organization.objects.get_or_create(
            code=DEFAULT_ORGANIZATION_CODE,
            defaults={
                "name": DEFAULT_ORGANIZATION_NAME,
                "legal_name": DEFAULT_ORGANIZATION_LEGAL_NAME,
                "status": Organization.Status.ACTIVE,
                "timezone": "Asia/Kolkata",
                "country": "IN",
                "metadata": {"seededBy": "ensure_default_organization"},
            },
        )
        report["organizationId"] = org.id
        report["createdOrganization"] = bool(created_org)

        # --- Branch ---------------------------------------------------
        branch, created_branch = Branch.objects.get_or_create(
            organization=org,
            code=DEFAULT_BRANCH_CODE,
            defaults={
                "name": DEFAULT_BRANCH_NAME,
                "status": Branch.Status.ACTIVE,
                "metadata": {"seededBy": "ensure_default_organization"},
            },
        )
        report["branchId"] = branch.id
        report["createdBranch"] = bool(created_branch)

        # --- Memberships ---------------------------------------------
        if options.get("skip_memberships"):
            report["membershipsSkipped"] = True
        else:
            User = get_user_model()
            created_count = 0
            user_role_field = getattr(User, "role", None)
            director_value = "director"
            admin_value = "admin"
            for user in User.objects.all():
                # Owner role for superusers; admin role for users marked
                # director / admin in the legacy User.role field; viewer
                # otherwise. Existing memberships are NEVER overwritten.
                if user.is_superuser:
                    desired_role = OrganizationMembership.OrgRole.OWNER
                elif getattr(user, "role", "") == director_value:
                    desired_role = OrganizationMembership.OrgRole.OWNER
                elif getattr(user, "role", "") == admin_value:
                    desired_role = OrganizationMembership.OrgRole.ADMIN
                else:
                    desired_role = OrganizationMembership.OrgRole.VIEWER
                _, created_member = (
                    OrganizationMembership.objects.get_or_create(
                        organization=org,
                        user=user,
                        defaults={
                            "role": desired_role,
                            "status": (
                                OrganizationMembership.Status.ACTIVE
                            ),
                            "metadata": {
                                "seededBy": "ensure_default_organization"
                            },
                        },
                    )
                )
                if created_member:
                    created_count += 1
            report["membershipsCreated"] = created_count

        # --- Audit row -------------------------------------------------
        write_event(
            kind="saas.default_organization.ensured",
            text=(
                f"Default organization ensured · {DEFAULT_ORGANIZATION_CODE} "
                f"(created_org={created_org}, created_branch={created_branch})"
            ),
            tone=AuditEvent.Tone.INFO,
            payload={
                "organization_id": org.id,
                "organization_code": org.code,
                "branch_id": branch.id,
                "branch_code": branch.code,
                "created_organization": bool(created_org),
                "created_branch": bool(created_branch),
                "memberships_created": report["membershipsCreated"],
            },
        )

        report["passed"] = True
        report["nextAction"] = (
            "ready_for_phase_6b_default_org_data_backfill"
            if not (created_org or created_branch)
            else "default_organization_seeded"
        )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Organization '{org.code}' ready (id={org.id}, "
                f"created={created_org}); branch '{branch.code}' "
                f"(id={branch.id}, created={created_branch}); "
                f"memberships_created={report['membershipsCreated']}"
            )
        )
