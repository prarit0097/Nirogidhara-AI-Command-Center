from django.contrib import admin

from .models import RewardPenalty, RewardPenaltyEvent


@admin.register(RewardPenalty)
class RewardPenaltyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "agent_id",
        "agent_type",
        "reward",
        "penalty",
        "rewarded_orders",
        "penalized_orders",
        "last_calculated_at",
    )
    list_filter = ("agent_type",)
    search_fields = ("name", "agent_id")
    ordering = ("sort_order", "name")


@admin.register(RewardPenaltyEvent)
class RewardPenaltyEventAdmin(admin.ModelAdmin):
    list_display = (
        "order_id_snapshot",
        "agent_name",
        "agent_type",
        "event_type",
        "reward_score",
        "penalty_score",
        "net_score",
        "calculated_at",
    )
    list_filter = ("event_type", "agent_name", "agent_type", "source")
    search_fields = ("order_id_snapshot", "agent_name", "unique_key")
    ordering = ("-calculated_at",)
    readonly_fields = ("unique_key", "calculated_at")
