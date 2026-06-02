from __future__ import annotations

from django.contrib import admin

from .models import AiCopilotReviewEvent, AiCopilotSuggestion


@admin.register(AiCopilotSuggestion)
class AiCopilotSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "suggestion_type", "source_type", "status", "ai_mode",
        "external_action_taken", "created_at",
    )
    list_filter = (
        "suggestion_type", "source_type", "status", "ai_mode",
        "external_action_taken",
    )
    search_fields = ("title", "source_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AiCopilotReviewEvent)
class AiCopilotReviewEventAdmin(admin.ModelAdmin):
    list_display = ("id", "suggestion", "action", "actor", "created_at")
    list_filter = ("action",)
    readonly_fields = ("created_at",)
