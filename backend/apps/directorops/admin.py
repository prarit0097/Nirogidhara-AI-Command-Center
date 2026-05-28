from __future__ import annotations

from django.contrib import admin

from .models import DirectorBriefingReview, TeamRoleAssignment


@admin.register(DirectorBriefingReview)
class DirectorBriefingReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "reviewer", "decision_status", "snapshot_ref", "created_at")
    list_filter = ("decision_status",)
    search_fields = ("note",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(TeamRoleAssignment)
class TeamRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "operational_role", "is_active", "updated_at")
    list_filter = ("operational_role", "is_active")
    search_fields = ("user__username",)
    readonly_fields = ("created_at", "updated_at")
