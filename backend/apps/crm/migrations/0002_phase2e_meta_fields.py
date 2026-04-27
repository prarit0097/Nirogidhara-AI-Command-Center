# Phase 2E — Meta Lead Ads provenance fields on Lead + idempotency table.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="meta_leadgen_id",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=64
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="meta_page_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="meta_form_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="meta_ad_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="meta_campaign_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="source_detail",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="lead",
            name="raw_source_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="MetaLeadEvent",
            fields=[
                (
                    "leadgen_id",
                    models.CharField(max_length=128, primary_key=True, serialize=False),
                ),
                ("page_id", models.CharField(blank=True, default="", max_length=64)),
                ("form_id", models.CharField(blank=True, default="", max_length=64)),
                ("ad_id", models.CharField(blank=True, default="", max_length=64)),
                ("campaign_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "lead_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("ok", "ok"), ("error", "error")],
                        default="ok",
                        max_length=8,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-received_at",)},
        ),
    ]
