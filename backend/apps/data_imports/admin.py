from __future__ import annotations

from django.contrib import admin

from .models import (
    ImportedCallingCampaign,
    ImportedCallQueueItem,
    ImportedDataRow,
    ImportedDataset,
)


@admin.register(ImportedDataset)
class ImportedDatasetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "total_rows", "valid_rows", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "source_label", "problem_category")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImportedDataRow)
class ImportedDataRowAdmin(admin.ModelAdmin):
    # raw_phone intentionally NOT in list_display to avoid surfacing full PII.
    list_display = ("id", "dataset", "row_number", "raw_name", "validation_status")
    list_filter = ("validation_status",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImportedCallingCampaign)
class ImportedCallingCampaignAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "total_contacts", "interested_count", "order_created_count")
    list_filter = ("status",)
    search_fields = ("name", "problem_category")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImportedCallQueueItem)
class ImportedCallQueueItemAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "status", "last_outcome", "call_attempts", "escalation_flag")
    list_filter = ("status", "escalation_flag")
    readonly_fields = ("created_at", "updated_at")
