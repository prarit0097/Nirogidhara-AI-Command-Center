from __future__ import annotations

from django.apps import AppConfig


class IntegrationHardeningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integration_hardening"
    verbose_name = "Payment / Logistics Integration Hardening (Phase 16E)"
