# Phase 3C — token usage + cost tracking + provider fallback fields on AgentRun.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_governance", "0002_agentrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="prompt_tokens",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="completion_tokens",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="total_tokens",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="provider_attempts",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="fallback_used",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="pricing_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
