from django.apps import AppConfig


class WhatsAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.whatsapp"
    label = "whatsapp"
    verbose_name = "WhatsApp (Phase 5A)"

    def ready(self) -> None:  # pragma: no cover - import side effect
        # Phase 5D — register lifecycle signal receivers.
        from . import signals  # noqa: F401
