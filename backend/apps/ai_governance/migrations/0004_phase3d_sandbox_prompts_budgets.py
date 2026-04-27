# Phase 3D — sandbox + prompt versioning + budget guards.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_governance", "0003_agentrun_cost_tracking"),
    ]

    operations = [
        # PromptVersion ledger.
        migrations.CreateModel(
            name="PromptVersion",
            fields=[
                ("id", models.CharField(max_length=32, primary_key=True, serialize=False)),
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
                ("version", models.CharField(max_length=24)),
                ("title", models.CharField(blank=True, default="", max_length=120)),
                ("system_policy", models.TextField(blank=True, default="")),
                ("role_prompt", models.TextField(blank=True, default="")),
                ("instruction_payload", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("sandbox", "sandbox"),
                            ("active", "active"),
                            ("rolled_back", "rolled_back"),
                            ("archived", "archived"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_by", models.CharField(blank=True, default="", max_length=80)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("rolled_back_at", models.DateTimeField(blank=True, null=True)),
                ("rollback_reason", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="promptversion",
            constraint=models.UniqueConstraint(
                fields=("agent", "version"),
                name="uniq_promptversion_agent_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="promptversion",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("agent",),
                name="uniq_promptversion_active_per_agent",
            ),
        ),
        migrations.AddIndex(
            model_name="promptversion",
            index=models.Index(fields=["agent"], name="prompt_ver_agent_idx"),
        ),
        migrations.AddIndex(
            model_name="promptversion",
            index=models.Index(fields=["status"], name="prompt_ver_status_idx"),
        ),
        # AgentBudget ledger.
        migrations.CreateModel(
            name="AgentBudget",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
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
                        unique=True,
                    ),
                ),
                (
                    "daily_budget_usd",
                    models.DecimalField(decimal_places=4, default=0, max_digits=10),
                ),
                (
                    "monthly_budget_usd",
                    models.DecimalField(decimal_places=4, default=0, max_digits=10),
                ),
                ("is_enforced", models.BooleanField(default=True)),
                ("alert_threshold_pct", models.IntegerField(default=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("agent",)},
        ),
        # SandboxState singleton.
        migrations.CreateModel(
            name="SandboxState",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, primary_key=True, serialize=False
                    ),
                ),
                ("is_enabled", models.BooleanField(default=False)),
                ("note", models.CharField(blank=True, default="", max_length=240)),
                ("updated_by", models.CharField(blank=True, default="", max_length=80)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        # AgentRun additions.
        migrations.AddField(
            model_name="agentrun",
            name="sandbox_mode",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="prompt_version_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="agent_runs",
                to="ai_governance.promptversion",
            ),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="budget_status",
            field=models.CharField(blank=True, default="", max_length=12),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="budget_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
