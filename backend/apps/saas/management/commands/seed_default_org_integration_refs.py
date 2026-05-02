"""``python manage.py seed_default_org_integration_refs --dry-run|--apply --json``.

Phase 6F — Per-Org Runtime Integration Routing Plan.

Idempotent seeder for the default organization's
:class:`OrganizationIntegrationSetting` rows. Creates secret references
ONLY (e.g. ``ENV:META_WA_ACCESS_TOKEN``) — never raw secret values.
Defaults to ``--dry-run``; ``--apply`` is required for any DB write.

LOCKED rules:

- Dry-run is the default. No DB writes unless ``--apply`` is set.
- NEVER stores a raw secret value. Only ``ENV:`` / ``VAULT:`` refs.
- NEVER activates per-org runtime routing. ``runtimeUsesPerOrgSettings``
  stays ``False`` even after this seeder runs.
- Idempotent: re-running with ``--apply`` is safe — existing rows are
  updated only when their secret_refs / config differ from the seed
  template.
- Emits ``saas.integration_refs.seeded`` audit row per provider per
  run.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.saas.context import get_default_organization
from apps.saas.integration_runtime import (
    _DEFAULT_PROVIDER_ENV_KEYS,
)
from apps.saas.integration_settings import (
    EXPECTED_SECRET_REFS,
    PROVIDER_LABELS,
)
from apps.saas.models import (
    Organization,
    OrganizationIntegrationSetting,
)


def _build_seed_template(provider_type: str) -> dict[str, Any]:
    """Compose ``secret_refs`` + non-sensitive ``config`` for a provider.

    Secret refs are ``ENV:VAR_NAME`` strings only. Config carries the
    same env-var names so the operator can see what's expected without
    inspecting code.
    """
    env_keys = _DEFAULT_PROVIDER_ENV_KEYS.get(provider_type, {})
    expected_refs = set(EXPECTED_SECRET_REFS.get(provider_type, ()))
    secret_refs = {
        friendly: f"ENV:{env_var}"
        for friendly, env_var in env_keys.items()
        if friendly in expected_refs
    }
    config = {
        f"{friendly}_env_var": env_var
        for friendly, env_var in env_keys.items()
        if friendly not in expected_refs
    }
    return {"secret_refs": secret_refs, "config": config}


class Command(BaseCommand):
    help = (
        "Idempotent seeder for the default organization's per-provider "
        "integration setting rows. Stores ENV: / VAULT: secret refs "
        "only. Never stores raw secrets, never activates runtime "
        "routing."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the seed; default is --dry-run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing (default).",
        )
        parser.add_argument(
            "--organization-code",
            default="",
            help=(
                "Optional org code to seed. Defaults to the seeded "
                "'nirogidhara' default organization."
            ),
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        apply_flag = bool(options.get("apply"))
        dry_run = not apply_flag

        code = (options.get("organization_code") or "").strip()
        if code:
            org = Organization.objects.filter(code=code).first()
        else:
            org = get_default_organization()

        report: dict[str, Any] = {
            "passed": False,
            "dryRun": dry_run,
            "organizationId": org.id if org else None,
            "organizationCode": org.code if org else "",
            "providers": [],
            "totalCreated": 0,
            "totalUpdated": 0,
            "totalUnchanged": 0,
            "warnings": [],
            "errors": [],
            "nextAction": "",
        }

        if org is None:
            report["errors"].append(
                "Default organization is missing — run "
                "ensure_default_organization first."
            )
            report["nextAction"] = "fix_runtime_routing_blockers"
            if options.get("json"):
                self.stdout.write(_json.dumps(report, default=str))
                return
            self._render_text(report)
            return

        for provider_type in PROVIDER_LABELS:
            template = _build_seed_template(provider_type)
            display_name = PROVIDER_LABELS[provider_type]
            existing = OrganizationIntegrationSetting.objects.filter(
                organization=org,
                provider_type=provider_type,
                display_name=display_name,
            ).first()

            row: dict[str, Any] = {
                "providerType": provider_type,
                "displayName": display_name,
                "templateSecretRefKeys": sorted(
                    template["secret_refs"].keys()
                ),
                "templateConfigKeys": sorted(template["config"].keys()),
                "action": "skipped",
                "settingId": existing.id if existing else None,
            }

            desired_status = (
                OrganizationIntegrationSetting.Status.CONFIGURED
                if template["secret_refs"]
                else OrganizationIntegrationSetting.Status.DRAFT
            )

            if existing is None:
                row["action"] = "would_create" if dry_run else "create"
                if not dry_run:
                    setting = OrganizationIntegrationSetting.objects.create(
                        organization=org,
                        provider_type=provider_type,
                        display_name=display_name,
                        status=desired_status,
                        secret_refs=template["secret_refs"],
                        config=template["config"],
                        is_active=False,
                    )
                    row["settingId"] = setting.id
                    report["totalCreated"] += 1
            else:
                # Only update when secret_refs / config / status differ.
                changed_fields: list[str] = []
                if (existing.secret_refs or {}) != template["secret_refs"]:
                    changed_fields.append("secret_refs")
                if (existing.config or {}) != template["config"]:
                    changed_fields.append("config")
                if existing.status != desired_status:
                    changed_fields.append("status")
                if changed_fields:
                    row["action"] = (
                        "would_update" if dry_run else "update"
                    )
                    row["changedFields"] = changed_fields
                    if not dry_run:
                        existing.secret_refs = template["secret_refs"]
                        existing.config = template["config"]
                        existing.status = desired_status
                        existing.save(
                            update_fields=[
                                "secret_refs",
                                "config",
                                "status",
                                "updated_at",
                            ]
                        )
                        report["totalUpdated"] += 1
                else:
                    row["action"] = "unchanged"
                    report["totalUnchanged"] += 1

            report["providers"].append(row)

            if not dry_run and row["action"] in {"create", "update"}:
                write_event(
                    kind="saas.integration_refs.seeded",
                    text=(
                        f"Integration secret refs seeded · "
                        f"{provider_type} · {row['action']}"
                    ),
                    tone=AuditEvent.Tone.INFO,
                    payload={
                        "organization_id": org.id,
                        "organization_code": org.code,
                        "provider_type": provider_type,
                        "display_name": display_name,
                        "action": row["action"],
                        "secret_ref_keys": row[
                            "templateSecretRefKeys"
                        ],
                        # Never include raw values.
                    },
                    organization=org,
                )

        report["passed"] = True
        if dry_run:
            if any(
                provider["action"]
                in {"would_create", "would_update"}
                for provider in report["providers"]
            ):
                report["nextAction"] = (
                    "run_seed_default_org_integration_refs_apply"
                )
            else:
                report["nextAction"] = (
                    "ready_for_phase_6g_controlled_runtime_routing_dry_run"
                )
        else:
            report["nextAction"] = (
                "ready_for_phase_6g_controlled_runtime_routing_dry_run"
            )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        mode = "DRY-RUN" if report["dryRun"] else "APPLY"
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Phase 6F integration-ref seed ({mode})"
            )
        )
        self.stdout.write(
            f"  organization : {report['organizationCode']} "
            f"(id={report['organizationId']})"
        )
        for row in report["providers"]:
            self.stdout.write(
                f"  - {row['providerType']:<16} · "
                f"action={row['action']:<14} · "
                f"refs={','.join(row['templateSecretRefKeys']) or '-'}"
            )
        self.stdout.write(
            f"  totals       : created={report['totalCreated']} "
            f"updated={report['totalUpdated']} "
            f"unchanged={report['totalUnchanged']}"
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
