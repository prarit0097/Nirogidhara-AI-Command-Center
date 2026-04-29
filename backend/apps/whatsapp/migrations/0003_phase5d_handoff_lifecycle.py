# Phase 5D — WhatsAppHandoffToCall + WhatsAppLifecycleEvent.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calls", "0002_phase2d_vapi_fields"),
        ("crm", "0002_phase2e_meta_fields"),
        ("whatsapp", "0002_whatsappinternalnote"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppHandoffToCall",
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
                ("reason", models.CharField(max_length=80)),
                (
                    "trigger_source",
                    models.CharField(
                        choices=[
                            ("ai", "ai"),
                            ("operator", "operator"),
                            ("lifecycle", "lifecycle"),
                            ("system", "system"),
                        ],
                        default="ai",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("triggered", "triggered"),
                            ("failed", "failed"),
                            ("skipped", "skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "provider_call_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("triggered_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                (
                    "call",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="whatsapp_handoffs",
                        to="calls.call",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="call_handoffs",
                        to="whatsapp.whatsappconversation",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="whatsapp_call_handoffs",
                        to="crm.customer",
                    ),
                ),
                (
                    "inbound_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="call_handoffs",
                        to="whatsapp.whatsappmessage",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="whatsapp_handoffs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["conversation", "-created_at"],
                        name="whatsapp_wh_convers_h0_idx",
                    ),
                    models.Index(
                        fields=["status", "-created_at"],
                        name="whatsapp_wh_status_h0_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="whatsapphandofftocall",
            constraint=models.UniqueConstraint(
                condition=models.Q(("inbound_message", None), _negated=True),
                fields=("conversation", "inbound_message", "reason"),
                name="uniq_whatsapp_handoff_per_inbound",
            ),
        ),
        migrations.CreateModel(
            name="WhatsAppLifecycleEvent",
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
                    "action_key",
                    models.CharField(db_index=True, max_length=120),
                ),
                (
                    "object_type",
                    models.CharField(
                        choices=[
                            ("order", "order"),
                            ("payment", "payment"),
                            ("shipment", "shipment"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "object_id",
                    models.CharField(db_index=True, max_length=64),
                ),
                ("event_kind", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "queued"),
                            ("sent", "sent"),
                            ("blocked", "blocked"),
                            ("skipped", "skipped"),
                            ("failed", "failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                (
                    "block_reason",
                    models.CharField(blank=True, default="", max_length=80),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                (
                    "idempotency_key",
                    models.CharField(max_length=200, unique=True),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="whatsapp_lifecycle_events",
                        to="crm.customer",
                    ),
                ),
                (
                    "message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifecycle_events",
                        to="whatsapp.whatsappmessage",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["object_type", "object_id", "-created_at"],
                        name="whatsapp_wh_object_l0_idx",
                    ),
                    models.Index(
                        fields=["status", "-created_at"],
                        name="whatsapp_wh_lstatus_l0_idx",
                    ),
                    models.Index(
                        fields=["action_key", "-created_at"],
                        name="whatsapp_wh_action_l0_idx",
                    ),
                ],
            },
        ),
    ]
