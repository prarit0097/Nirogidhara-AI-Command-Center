# Phase 3A — AgentRun ledger for every LLM dispatch.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_governance", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentRun",
            fields=[
                (
                    "id",
                    models.CharField(max_length=32, primary_key=True, serialize=False),
                ),
                (
                    "agent",
                    models.CharField(
                        choices=[
                            ("ceo", "ceo"),
                            ("caio", "caio"),
                            ("ads", "ads"),
                            ("rto", "rto"),
                            ("sales_growth", "sales_growth"),
                            ("marketing", "marketing"),
                            ("cfo", "cfo"),
                            ("compliance", "compliance"),
                        ],
                        max_length=24,
                    ),
                ),
                ("prompt_version", models.CharField(default="v1.0", max_length=24)),
                ("input_payload", models.JSONField(blank=True, default=dict)),
                ("output_payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("success", "success"),
                            ("failed", "failed"),
                            ("skipped", "skipped"),
                        ],
                        default="pending",
                        max_length=12,
                    ),
                ),
                ("provider", models.CharField(default="disabled", max_length=16)),
                ("model", models.CharField(blank=True, default="", max_length=64)),
                ("latency_ms", models.IntegerField(default=0)),
                (
                    "cost_usd",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=10, null=True
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                ("dry_run", models.BooleanField(default=True)),
                ("triggered_by", models.CharField(blank=True, default="", max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["agent"], name="ai_governan_agent_5d4f2f_idx"),
                    models.Index(fields=["status"], name="ai_governan_status_2cd0b6_idx"),
                ],
            },
        ),
    ]
