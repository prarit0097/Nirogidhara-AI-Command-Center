"""``python manage.py inspect_controlled_runtime_routing_dry_run --json``.

Phase 6G — Controlled Runtime Routing Dry Run.

Read-only diagnostic. NEVER calls a provider, NEVER mutates data,
NEVER returns raw secrets.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.context import get_default_organization
from apps.saas.models import Organization
from apps.saas.runtime_dry_run import (
    preview_all_runtime_operations,
    preview_runtime_routing_for_operation,
    validate_dry_run_has_no_side_effects,
)


class Command(BaseCommand):
    help = (
        "Read-only Phase 6G diagnostic — controlled runtime routing "
        "dry-run preview. No external provider calls, no live side "
        "effects, no raw secrets."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--organization-code",
            default="",
            help=(
                "Optional org code to inspect. Defaults to the seeded "
                "'nirogidhara' default organization."
            ),
        )
        parser.add_argument(
            "--operation",
            default="all",
            help=(
                "Operation type to preview, or 'all' to walk the whole "
                "registry. Default: all."
            ),
        )
        parser.add_argument(
            "--include-ai",
            action="store_true",
            default=True,
            help="Include AI provider routing previews (default: on).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        code = (options.get("organization_code") or "").strip()
        if code:
            org = Organization.objects.filter(code=code).first()
        else:
            org = get_default_organization()

        operation = (options.get("operation") or "all").strip()
        include_ai = bool(options.get("include_ai", True))

        if operation == "all" or not operation:
            report = preview_all_runtime_operations(
                org, include_ai=include_ai
            )
        else:
            single = preview_runtime_routing_for_operation(
                operation, org=org
            )
            report = {
                "organization": (
                    {"id": org.id, "code": org.code, "name": org.name}
                    if org
                    else None
                ),
                "runtimeSource": "env_config",
                "perOrgRuntimeEnabled": False,
                "runtimeUsesPerOrgSettings": False,
                "dryRun": True,
                "liveExecutionAllowed": False,
                "operations": [single],
                "aiProviderRoutes": None,
                "global": {
                    "safeToStartPhase6H": not single.get("blockers"),
                    "blockers": single.get("blockers", []),
                    "warnings": single.get("warnings", []),
                    "nextAction": single.get("nextAction", ""),
                },
                "blockers": single.get("blockers", []),
                "warnings": single.get("warnings", []),
                "nextAction": single.get("nextAction", ""),
            }

        # Defence-in-depth: every operation in the report must satisfy
        # the no-side-effects invariants.
        for op in report["operations"]:
            if not validate_dry_run_has_no_side_effects(op):
                report.setdefault("warnings", []).append(
                    f"Invariant violated for {op.get('operationType')} "
                    "— refusing to render as dry-run."
                )

        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6G runtime dry-run preview")
        )
        org_payload = report.get("organization") or {}
        self.stdout.write(
            f"  organization              : "
            f"{org_payload.get('code', '<missing>')} "
            f"(id={org_payload.get('id', '<missing>')})"
        )
        self.stdout.write(
            f"  runtimeSource             : {report['runtimeSource']}"
        )
        self.stdout.write(
            f"  perOrgRuntimeEnabled      : "
            f"{report['perOrgRuntimeEnabled']}"
        )
        self.stdout.write(
            f"  dryRun / liveExecAllowed  : "
            f"{report['dryRun']} / {report['liveExecutionAllowed']}"
        )
        for op in report["operations"]:
            self.stdout.write(
                f"  - {op['operationType']:<32} · "
                f"provider={op['providerType']:<14} · "
                f"setting={op['providerSettingExists']} · "
                f"risk={op['sideEffectRisk']:<6} · "
                f"blockers={len(op.get('blockers') or [])} · "
                f"warnings={len(op.get('warnings') or [])}"
            )
        ai_block = report.get("aiProviderRoutes")
        if ai_block:
            self.stdout.write(self.style.MIGRATE_LABEL("AI routing:"))
            for task in ai_block.get("tasks", []):
                self.stdout.write(
                    f"  - {task['taskType']:<24} · "
                    f"primary={task['primaryProvider']}/"
                    f"{task['primaryModel']} · "
                    f"max_tokens={task['maxTokens']} "
                    f"({task['maxTokensSource']})"
                )
        self.stdout.write(
            f"safeToStartPhase6H : {report['global']['safeToStartPhase6H']}"
        )
        self.stdout.write(f"nextAction         : {report['nextAction']}")
