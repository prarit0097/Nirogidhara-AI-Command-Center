from __future__ import annotations

from django.contrib import admin

from .models import (
    Branch,
    Organization,
    OrganizationFeatureFlag,
    OrganizationMembership,
    OrganizationSetting,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "status", "country", "created_at")
    search_fields = ("code", "name", "legal_name")
    list_filter = ("status", "country")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("organization", "code", "name", "status", "created_at")
    search_fields = ("code", "name")
    list_filter = ("status", "organization")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "status", "created_at")
    search_fields = ("user__username", "user__email")
    list_filter = ("role", "status", "organization")


@admin.register(OrganizationFeatureFlag)
class OrganizationFeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("organization", "key", "enabled", "updated_at")
    search_fields = ("key",)
    list_filter = ("enabled", "organization")


@admin.register(OrganizationSetting)
class OrganizationSettingAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "key",
        "is_sensitive",
        "updated_at",
    )
    search_fields = ("key",)
    list_filter = ("is_sensitive", "organization")
