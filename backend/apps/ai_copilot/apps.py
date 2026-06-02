from __future__ import annotations

from django.apps import AppConfig


class AiCopilotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_copilot"
    verbose_name = "AI Copilot (internal, human-approved)"
