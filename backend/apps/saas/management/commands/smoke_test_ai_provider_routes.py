"""``python manage.py smoke_test_ai_provider_routes --task <name|all> --json``.

Phase 6G — optional explicit AI provider smoke test.

This is the ONLY runtime path in Phase 6G that may issue a live
NVIDIA / OpenAI request. Designed for the operator to verify
provider reachability with a tiny non-customer prompt.

LOCKED rules:

- Default prompt: ``"Reply only OK"`` — never includes customer data.
- ``max_tokens`` defaults to ``AI_MAX_TOKENS_SMOKE`` env / route default.
- API keys are NEVER logged or returned. ``responsePreview`` truncated
  to 120 chars.
- Failures are captured and reported — the command never crashes the
  server.
- The command writes one ``ai.provider_smoke_test.completed`` /
  ``.failed`` audit row per task per run.
"""
from __future__ import annotations

import json as _json
import os
import time
from typing import Any

from django.core.management.base import BaseCommand

from apps.audit.models import AuditEvent
from apps.audit.signals import write_event
from apps.saas.ai_runtime_preview import (
    AI_TASK_ROUTES,
    get_ai_task_max_tokens,
    get_ai_task_route,
    preview_ai_provider_route,
)


_DEFAULT_PROMPT = "Reply only OK"
_DEFAULT_TIMEOUT_SECONDS = 12.0


def _provider_call(
    *,
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Issue a tiny chat completion request. Returns a status payload —
    NEVER raises. The implementation is provider-specific but kept
    minimal: we only need a status code + a short response preview.
    """
    if provider == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY") or ""
        base_url = (
            os.environ.get("NVIDIA_API_BASE_URL")
            or "https://integrate.api.nvidia.com/v1"
        )
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        base_url = (
            os.environ.get("OPENAI_API_BASE_URL")
            or "https://api.openai.com/v1"
        )
    else:
        return {
            "passed": False,
            "statusCode": 0,
            "responsePreview": "",
            "error": f"Unsupported provider: {provider}",
        }

    if not api_key:
        return {
            "passed": False,
            "statusCode": 0,
            "responsePreview": "",
            "error": f"{provider.upper()} API key is not set",
        }

    try:
        import requests  # local import; requests is already a dep
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "statusCode": 0,
            "responsePreview": "",
            "error": f"requests import failed: {exc}",
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    started = time.time()
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "statusCode": 0,
            "responsePreview": "",
            "error": f"request failed: {exc.__class__.__name__}",
            "elapsedMs": int((time.time() - started) * 1000),
        }

    body_text = ""
    try:
        data = resp.json()
        choices = data.get("choices") or []
        if choices:
            body_text = (
                (choices[0].get("message") or {}).get("content")
                or ""
            )[:120]
        else:
            body_text = (
                _json.dumps(data, default=str)[:120]
                if data
                else ""
            )
    except Exception:  # noqa: BLE001
        body_text = (resp.text or "")[:120]

    return {
        "passed": 200 <= resp.status_code < 300 and bool(body_text),
        "statusCode": resp.status_code,
        "responsePreview": body_text,
        "error": "",
        "elapsedMs": int((time.time() - started) * 1000),
    }


class Command(BaseCommand):
    help = (
        "Run a tiny smoke test against the AI providers (NVIDIA / "
        "OpenAI). Default prompt 'Reply only OK'. Never includes "
        "customer data; never logs API keys."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--task",
            default="all",
            help=(
                "AI task type to test, or 'all' for the full route "
                "matrix. Default: all."
            ),
        )
        parser.add_argument(
            "--provider",
            default="primary",
            choices=("primary", "fallback"),
            help="Test the primary or fallback provider for the task.",
        )
        parser.add_argument(
            "--prompt",
            default=_DEFAULT_PROMPT,
            help=f"Override the smoke prompt (default: '{_DEFAULT_PROMPT}').",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=_DEFAULT_TIMEOUT_SECONDS,
            help="Per-call timeout in seconds (default 12).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    def handle(self, *args, **options) -> None:
        task_name = (options.get("task") or "all").strip()
        provider_choice = options.get("provider") or "primary"
        prompt = options.get("prompt") or _DEFAULT_PROMPT
        timeout = float(options.get("timeout") or _DEFAULT_TIMEOUT_SECONDS)

        tasks = (
            list(AI_TASK_ROUTES)
            if task_name == "all"
            else [route for route in AI_TASK_ROUTES if route.task_type == task_name]
        )
        if not tasks:
            report = {
                "passed": False,
                "errors": [f"Unknown task: {task_name}"],
                "results": [],
            }
            if options.get("json"):
                self.stdout.write(_json.dumps(report, default=str))
            else:
                self.stderr.write(self.style.ERROR(report["errors"][0]))
            return

        results: list[dict[str, Any]] = []
        for route in tasks:
            preview = preview_ai_provider_route(route.task_type)
            provider = (
                route.primary_provider
                if provider_choice == "primary"
                else route.fallback_provider
            )
            model = (
                preview["primaryModel"]
                if provider_choice == "primary"
                else preview["fallbackModel"]
            )
            max_tokens = get_ai_task_max_tokens(route.task_type)["value"]

            outcome = _provider_call(
                provider=provider,
                model=model,
                prompt=prompt,
                max_tokens=max_tokens,
                timeout_seconds=timeout,
            )
            entry = {
                "taskType": route.task_type,
                "provider": provider,
                "model": model,
                "promptPreview": prompt[:120],
                "maxTokens": max_tokens,
                "statusCode": outcome.get("statusCode", 0),
                "responsePreview": outcome.get("responsePreview", ""),
                "passed": bool(outcome.get("passed")),
                "error": outcome.get("error", ""),
                "elapsedMs": outcome.get("elapsedMs", 0),
            }
            results.append(entry)

            audit_kind = (
                "ai.provider_smoke_test.completed"
                if entry["passed"]
                else "ai.provider_smoke_test.failed"
            )
            tone = (
                AuditEvent.Tone.SUCCESS
                if entry["passed"]
                else AuditEvent.Tone.WARNING
            )
            write_event(
                kind=audit_kind,
                text=(
                    f"AI smoke test · task={entry['taskType']} · "
                    f"provider={entry['provider']} · "
                    f"status={entry['statusCode']}"
                ),
                tone=tone,
                payload={
                    "task_type": entry["taskType"],
                    "provider": entry["provider"],
                    "model": entry["model"],
                    "status_code": entry["statusCode"],
                    "passed": entry["passed"],
                    "max_tokens": entry["maxTokens"],
                    "elapsed_ms": entry["elapsedMs"],
                    # Never include API key or full prompt body.
                    "response_preview": entry["responsePreview"][:120],
                },
            )

        passed = all(entry["passed"] for entry in results) if results else False
        report = {
            "passed": passed,
            "task": task_name,
            "providerChoice": provider_choice,
            "results": results,
        }
        if options.get("json"):
            self.stdout.write(_json.dumps(report, default=str))
            return

        for entry in results:
            tone = self.style.SUCCESS if entry["passed"] else self.style.WARNING
            self.stdout.write(
                tone(
                    f"  {entry['taskType']:<24} · "
                    f"{entry['provider']}/{entry['model']} · "
                    f"status={entry['statusCode']} · "
                    f"passed={entry['passed']} · "
                    f"resp='{entry['responsePreview'][:60]}'"
                )
            )
        self.stdout.write(f"overall passed: {passed}")
