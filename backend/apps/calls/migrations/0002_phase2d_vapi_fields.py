# Phase 2D — Vapi integration fields on Call + dual-parent CallTranscriptLine
# (ActiveCall for live pane, Call for Vapi post-call transcripts) + per-app
# webhook idempotency table.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calls", "0001_initial"),
    ]

    operations = [
        # Call: new integration fields.
        migrations.AddField(
            model_name="call",
            name="provider",
            field=models.CharField(
                choices=[("manual", "manual"), ("vapi", "vapi")],
                default="manual",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="call",
            name="provider_call_id",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=64
            ),
        ),
        migrations.AddField(
            model_name="call",
            name="summary",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="call",
            name="recording_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="call",
            name="handoff_flags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="call",
            name="ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="call",
            name="error_message",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="call",
            name="raw_response",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="call",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="call",
            name="status",
            field=models.CharField(
                choices=[
                    ("Live", "Live"),
                    ("Queued", "Queued"),
                    ("Completed", "Completed"),
                    ("Missed", "Missed"),
                    ("Failed", "Failed"),
                ],
                default="Queued",
                max_length=12,
            ),
        ),
        # CallTranscriptLine: rename legacy `call` FK -> `active_call`, add new
        # `call` FK pointing to the Call model.
        migrations.RenameField(
            model_name="calltranscriptline",
            old_name="call",
            new_name="active_call",
        ),
        migrations.AlterField(
            model_name="calltranscriptline",
            name="active_call",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="transcript_lines",
                to="calls.activecall",
            ),
        ),
        migrations.AddField(
            model_name="calltranscriptline",
            name="call",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="transcript_lines",
                to="calls.call",
            ),
        ),
        # Per-app webhook idempotency log (Vapi).
        migrations.CreateModel(
            name="WebhookEvent",
            fields=[
                (
                    "event_id",
                    models.CharField(max_length=128, primary_key=True, serialize=False),
                ),
                ("provider", models.CharField(default="vapi", max_length=16)),
                ("event_type", models.CharField(max_length=64)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-received_at",),
            },
        ),
    ]
