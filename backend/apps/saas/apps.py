from __future__ import annotations

from django.apps import AppConfig


class SaasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.saas"
    verbose_name = "SaaS Foundation"

    def ready(self) -> None:  # pragma: no cover - signal wiring
        # Phase 6D — connect the pre_save auto-assignment signals once
        # every app is loaded.
        from . import signals  # noqa: F401 - import for side effects

        signals._connect_signal_handlers()
