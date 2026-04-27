# Phase 2C — add Delhivery integration fields to Shipment.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipments", "0002_rescueattempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="delhivery_status",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="shipment",
            name="tracking_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="shipment",
            name="risk_flag",
            field=models.CharField(blank=True, default="", max_length=24),
        ),
        migrations.AddField(
            model_name="shipment",
            name="raw_response",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="shipment",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
