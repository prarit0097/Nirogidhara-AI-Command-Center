"""Diagnostics app config."""
from __future__ import annotations

from django.apps import AppConfig


class DiagnosticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.diagnostics"
    verbose_name = "Diagnostics"
