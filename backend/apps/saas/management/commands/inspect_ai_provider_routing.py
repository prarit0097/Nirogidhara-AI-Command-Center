"""``python manage.py inspect_ai_provider_routing --json``.

Phase 6G — AI provider routing diagnostic. Read-only.
"""
from __future__ import annotations

import json as _json
from typing import Any

from django.core.management.base import BaseCommand

from apps.saas.ai_runtime_preview import preview_all_ai_provider_routes


class Command(BaseCommand):
    help = (
        "Read-only Phase 6G AI provider routing preview. Reports "
        "primary/fallback providers, NVIDIA model mapping, task-wise "
        "max_tokens, and env-key presence. Never returns raw API keys."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        report: dict[str, Any] = preview_all_ai_provider_routes()
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return
        self._render_text(report)

    def _render_text(self, report: dict[str, Any]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING("Phase 6G AI provider routing")
        )
        runtime = report.get("runtime", {})
        self.stdout.write(
            f"  runtimeMode      : {runtime.get('runtimeMode')}"
        )
        self.stdout.write(
            f"  primaryProvider  : {runtime.get('primaryProvider')}"
        )
        self.stdout.write(
            f"  fallbackProvider : {runtime.get('fallbackProvider')}"
        )
        env_status = runtime.get("envKeyPresence", {})
        for key, present in env_status.items():
            self.stdout.write(f"    env[{key}] = {present}")
        for task in report.get("tasks", []):
            self.stdout.write(
                f"  - {task['taskType']:<24} · "
                f"primary={task['primaryProvider']}/"
                f"{task['primaryModel']} · "
                f"fallback={task['fallbackProvider']}/"
                f"{task['fallbackModel']} · "
                f"max_tokens={task['maxTokens']} "
                f"({task['maxTokensSource']})"
            )
        self.stdout.write(
            f"safeToStartAiDryRun : {report.get('safeToStartAiDryRun')}"
        )
        self.stdout.write(
            f"nextAction          : {report.get('nextAction')}"
        )
