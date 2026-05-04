# Phase 2D — Vapi integration fields on Call + dual-parent CallTranscriptLine
# (ActiveCall for live pane, Call for Vapi post-call transcripts) + per-app
# webhook idempotency table.
#
# 2026-05-04 hotfix: a fresh-Postgres ``migrate`` previously failed with
#
#     django.db.utils.ProgrammingError:
#         relation "calls_calltranscriptline_call_id_5bc33dc3" already exists
#
# Root cause: 0001 created an auto-named FK index
# ``calls_calltranscriptline_call_id_5bc33dc3`` for the original
# ``CallTranscriptLine.call`` FK (-> ActiveCall). The ``RenameField call ->
# active_call`` below changes the column name but, depending on Django
# version + Postgres backend, the auto-named index is left behind on
# the renamed ``active_call_id`` column. The subsequent
# ``AddField call -> Call`` then asks Django to create the FK index for the
# new ``call_id`` column, which hashes to the SAME name ``...call_id_5bc33dc3``,
# and Postgres rejects "relation already exists".
#
# Fix: between the rename and the add, drop the legacy index iff it still
# exists. The drop is:
#   - Postgres-only (skipped on SQLite / other vendors so dev tests stay green),
#   - Idempotent on a fresh Postgres DB (``DROP INDEX IF EXISTS``),
#   - A no-op on production where this migration has already been applied
#     (Django never re-runs an applied migration).
# After the drop, ``AddField call`` is free to create its own
# ``calls_calltranscriptline_call_id_5bc33dc3`` index without colliding.
import django.db.models.deletion
from django.db import migrations, models


_LEGACY_CALL_ID_INDEX_SQL_DROP = (
    'DROP INDEX IF EXISTS "calls_calltranscriptline_call_id_5bc33dc3";'
    # Postgres also creates a `_like` companion index for
    # varchar_pattern_ops on FK columns when the FK target uses a CHAR
    # primary key (``Call.id`` / ``ActiveCall.id`` are CharField PKs).
    # Drop both halves here so a fresh ``migrate`` cannot fail on either.
    ' DROP INDEX IF EXISTS "calls_calltranscriptline_call_id_5bc33dc3_like";'
)


def _phase2d_drop_legacy_calltranscriptline_call_id_index(apps, schema_editor):
    """Drop the legacy ``call_id`` auto-named index on Postgres only.

    Idempotent. See the file-level comment for the full root cause.
    """
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(_LEGACY_CALL_ID_INDEX_SQL_DROP)


def _phase2d_drop_legacy_calltranscriptline_call_id_index_reverse(apps, schema_editor):
    """Reverse intentionally noop.

    The reverse path of the surrounding ``AddField`` / ``RenameField``
    operations is already responsible for restoring the original
    ``call_id`` column + index. Re-creating the index here would
    conflict with that path.
    """
    return None


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
        # Hotfix step (2026-05-04): drop the legacy auto-named call_id index
        # left behind by the RenameField above so the AddField below can
        # safely re-create the same auto-name on the NEW call_id column.
        # See the file-level comment for the full reasoning.
        migrations.RunPython(
            _phase2d_drop_legacy_calltranscriptline_call_id_index,
            _phase2d_drop_legacy_calltranscriptline_call_id_index_reverse,
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
