"""Phase 5E-Smoke — controlled AI / WhatsApp / Vapi smoke test command.

Safe by default. Runs five smoke scenarios (or one) without sending
real customer messages or dialing any real number:

  ai-reply        - exercise the WhatsApp AI Chat orchestrator with a
                    scripted Hindi/Hinglish/English inbound and a mocked
                    LLM decision. Auto-reply stays OFF.
  claim-vault     - seed default claims (optionally with --reset-demo)
                    + run the coverage report.
  rescue-discount - exercise the cumulative 50% cap math through four
                    deterministic cases (0% / 40% / 50% / CAIO).
  vapi-handoff    - trigger WhatsApp → Vapi handoff in mock mode +
                    verify idempotency + safety-reason skip.
  reorder-day20   - eligibility filter + sweep dry-run (idempotent).
  all             - run every scenario above in safe order.

Examples::

    python manage.py run_controlled_ai_smoke_test --scenario claim-vault --json
    python manage.py run_controlled_ai_smoke_test --scenario ai-reply --language hindi
    python manage.py run_controlled_ai_smoke_test --scenario rescue-discount --json
    python manage.py run_controlled_ai_smoke_test --scenario vapi-handoff --mock-vapi
    python manage.py run_controlled_ai_smoke_test --scenario reorder-day20 --dry-run
    python manage.py run_controlled_ai_smoke_test --scenario all --json

Defaults are SAFE: --dry-run is on, WhatsApp + Vapi are mocked, OpenAI
is OFF (deterministic mocked LLM decision used). Pass --use-openai to
let the orchestrator hit the real OpenAI provider during the ai-reply
scenario (still no real WhatsApp send — the WhatsApp provider stays
mock).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Run the controlled AI / WhatsApp / Vapi smoke harness. Safe "
        "defaults — never sends real customer messages."
    )

    def add_arguments(self, parser) -> None:
        from apps.whatsapp.smoke_harness import (
            SUPPORTED_LANGUAGES,
            SUPPORTED_SCENARIOS,
        )

        parser.add_argument(
            "--scenario",
            choices=list(SUPPORTED_SCENARIOS),
            default="all",
            help="Which scenario to run. Default: all.",
        )
        parser.add_argument(
            "--language",
            choices=list(SUPPORTED_LANGUAGES),
            default="hinglish",
            help="Customer language for the ai-reply scenario.",
        )
        parser.add_argument(
            "--customer-phone",
            default="",
            help=(
                "Override the smoke customer phone. The harness uses "
                "+919999900001 by default; only override on a fully "
                "isolated dev DB."
            ),
        )
        parser.add_argument(
            "--use-openai",
            action="store_true",
            help=(
                "Hit the real OpenAI provider during ai-reply (still no "
                "real WhatsApp send). Requires OPENAI_API_KEY. Default: "
                "deterministic mocked decision."
            ),
        )
        parser.add_argument(
            "--mock-whatsapp",
            dest="mock_whatsapp",
            action="store_true",
            default=True,
            help="Force WHATSAPP_PROVIDER=mock for the run (default: on).",
        )
        parser.add_argument(
            "--no-mock-whatsapp",
            dest="mock_whatsapp",
            action="store_false",
            help=(
                "Allow the run to use the configured WHATSAPP_PROVIDER. "
                "The harness still refuses to run with provider="
                "meta_cloud — switch the provider explicitly first."
            ),
        )
        parser.add_argument(
            "--mock-vapi",
            dest="mock_vapi",
            action="store_true",
            default=True,
            help="Force VAPI_MODE=mock for the run (default: on).",
        )
        parser.add_argument(
            "--no-mock-vapi",
            dest="mock_vapi",
            action="store_false",
            help="Allow the run to use the configured VAPI_MODE.",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=True,
            help="Default: report-only, never queue a real send.",
        )
        parser.add_argument(
            "--no-dry-run",
            dest="dry_run",
            action="store_false",
            help=(
                "Allow the harness to queue messages through the mock "
                "WhatsApp provider. Real customer sends still require "
                "--no-mock-whatsapp + a non-mock provider configured."
            ),
        )
        parser.add_argument(
            "--reset-demo-claims",
            action="store_true",
            help=(
                "Pass --reset-demo to seed_default_claims (claim-vault "
                "scenario only). Real admin-added claims are still "
                "never overwritten."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="emit_json",
            help="Emit the full result as JSON instead of human output.",
        )

    def handle(self, *args, **options) -> None:
        from apps.whatsapp.smoke_harness import run_smoke_harness

        try:
            result = run_smoke_harness(
                scenario=options["scenario"],
                dry_run=options["dry_run"],
                mock_whatsapp=options["mock_whatsapp"],
                mock_vapi=options["mock_vapi"],
                use_openai=options["use_openai"],
                language=options["language"],
                customer_phone=options.get("customer_phone") or "",
                reset_demo_claims=options.get("reset_demo_claims", False),
            )
        except (RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options.get("emit_json"):
            self.stdout.write(json.dumps(result.to_dict(), indent=2))
        else:
            self._render_human(result)

        if not result.overall_passed:
            raise CommandError(
                f"Smoke harness FAILED for scenario "
                f"{options['scenario']!r}. See output above."
            )

    # ------------------------------------------------------------------
    # Human-readable summary
    # ------------------------------------------------------------------

    def _render_human(self, result) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nControlled AI Smoke Harness · scenario={result.options['scenario']}"
        ))
        self.stdout.write(
            f"  options: dryRun={result.options['dryRun']} "
            f"mockWhatsapp={result.options['mockWhatsapp']} "
            f"mockVapi={result.options['mockVapi']} "
            f"useOpenai={result.options['useOpenai']} "
            f"language={result.options['language']}"
        )
        self.stdout.write(f"  startedAt: {result.started_at}")
        self.stdout.write(f"  completedAt: {result.completed_at}")

        for scenario in result.scenarios:
            badge = (
                self.style.SUCCESS("PASS") if scenario.passed
                else self.style.ERROR("FAIL")
            )
            self.stdout.write(f"\n  [{badge}] {scenario.name}")
            if scenario.objects_created:
                items = ", ".join(
                    f"{k}={v}" for k, v in scenario.objects_created.items()
                )
                self.stdout.write(f"      objects: {items}")
            self.stdout.write(
                f"      audit_events_emitted: {scenario.audit_events_emitted}"
            )
            for warning in scenario.warnings:
                self.stdout.write(self.style.WARNING(f"      warn: {warning}"))
            for error in scenario.errors:
                self.stdout.write(self.style.ERROR(f"      error: {error}"))
            if scenario.next_action:
                self.stdout.write(f"      next: {scenario.next_action}")

        overall = (
            self.style.SUCCESS("OVERALL PASS") if result.overall_passed
            else self.style.ERROR("OVERALL FAIL")
        )
        self.stdout.write(f"\n  {overall}\n")
