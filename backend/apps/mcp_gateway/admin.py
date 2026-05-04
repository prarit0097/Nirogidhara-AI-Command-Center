"""Phase 6M-0 — Django admin registrations (read-only browsing)."""
from __future__ import annotations

from django.contrib import admin

from .models import (
    McpAccessPolicy,
    McpClientApp,
    McpPromptDefinition,
    McpResourceDefinition,
    McpToolDefinition,
    McpToolInvocationLog,
)


@admin.register(McpClientApp)
class McpClientAppAdmin(admin.ModelAdmin):
    list_display = ("client_id", "name", "provider", "is_active", "read_only")
    list_filter = ("provider", "is_active", "read_only")
    search_fields = ("client_id", "name")


@admin.register(McpAccessPolicy)
class McpAccessPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "read_only", "client_app")
    list_filter = ("enabled", "read_only", "allow_write_tools", "allow_provider_tools")


@admin.register(McpToolDefinition)
class McpToolDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "risk_level",
        "enabled",
        "read_only",
        "provider_call_allowed",
        "business_mutation_allowed",
    )
    list_filter = ("category", "risk_level", "enabled", "read_only")
    search_fields = ("name", "title")


@admin.register(McpResourceDefinition)
class McpResourceDefinitionAdmin(admin.ModelAdmin):
    list_display = ("uri", "name", "enabled", "read_only", "pii_exposure_level")
    search_fields = ("uri", "name")


@admin.register(McpPromptDefinition)
class McpPromptDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "risk_level", "enabled")
    search_fields = ("name", "title")


@admin.register(McpToolInvocationLog)
class McpToolInvocationLogAdmin(admin.ModelAdmin):
    list_display = (
        "invocation_id",
        "tool_name",
        "status",
        "risk_level",
        "provider_call_attempted",
        "business_mutation_attempted",
        "created_at",
    )
    list_filter = (
        "status",
        "tool_category",
        "risk_level",
        "provider_call_attempted",
        "business_mutation_attempted",
    )
    search_fields = ("invocation_id", "tool_name")
    readonly_fields = [field.name for field in McpToolInvocationLog._meta.fields]
