# Phase 5E — DiscountOfferLog model.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_governance", "0006_phase4d_approval_execution_log"),
        ("crm", "0002_phase2e_meta_fields"),
        ("orders", "0002_order_confirmation_notes_order_confirmation_outcome_and_more"),
        ("whatsapp", "0003_phase5d_handoff_lifecycle"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiscountOfferLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "source_channel",
                    models.CharField(
                        choices=[
                            ("whatsapp_ai", "whatsapp_ai"),
                            ("ai_call", "ai_call"),
                            ("confirmation", "confirmation"),
                            ("delivery", "delivery"),
                            ("rto", "rto"),
                            ("operator", "operator"),
                            ("system", "system"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("order_booking", "order_booking"),
                            ("confirmation", "confirmation"),
                            ("delivery", "delivery"),
                            ("rto", "rto"),
                            ("reorder", "reorder"),
                            ("customer_success", "customer_success"),
                        ],
                        max_length=24,
                    ),
                ),
                ("trigger_reason", models.CharField(max_length=80)),
                ("previous_discount_pct", models.IntegerField(default=0)),
                ("offered_additional_pct", models.IntegerField(default=0)),
                ("resulting_total_discount_pct", models.IntegerField(default=0)),
                ("cap_remaining_pct", models.IntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("offered", "offered"),
                            ("accepted", "accepted"),
                            ("rejected", "rejected"),
                            ("blocked", "blocked"),
                            ("skipped", "skipped"),
                            ("needs_ceo_review", "needs_ceo_review"),
                        ],
                        default="offered",
                        max_length=24,
                    ),
                ),
                (
                    "blocked_reason",
                    models.CharField(blank=True, default="", max_length=80),
                ),
                (
                    "offered_by_agent",
                    models.CharField(blank=True, default="", max_length=40),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approval_request",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="discount_offers",
                        to="ai_governance.approvalrequest",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="discount_offers",
                        to="whatsapp.whatsappconversation",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="discount_offers",
                        to="crm.customer",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="discount_offers",
                        to="orders.order",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["order", "-created_at"],
                        name="orders_disc_order_i_dol_idx",
                    ),
                    models.Index(
                        fields=["status", "-created_at"],
                        name="orders_disc_status_dol_idx",
                    ),
                    models.Index(
                        fields=["stage", "-created_at"],
                        name="orders_disc_stage_dol_idx",
                    ),
                    models.Index(
                        fields=["source_channel", "-created_at"],
                        name="orders_disc_source_dol_idx",
                    ),
                ],
            },
        ),
    ]
