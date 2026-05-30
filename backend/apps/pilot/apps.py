from __future__ import annotations

from django.apps import AppConfig


class PilotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pilot"
    verbose_name = "Controlled Internal Pilot Readiness (Phase 16F)"
