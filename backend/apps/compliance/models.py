from __future__ import annotations

from django.db import models


class Claim(models.Model):
    """Approved Claim Vault — Blueprint Section 5.10.

    AI may only speak from approved claims. The vault is doctor- and
    compliance-reviewed; this model captures the current snapshot per product.
    """

    product = models.CharField(primary_key=True, max_length=120)
    approved = models.JSONField(default=list, blank=True)
    disallowed = models.JSONField(default=list, blank=True)
    doctor = models.CharField(max_length=120, default="Pending review")
    compliance = models.CharField(max_length=120, default="Pending review")
    version = models.CharField(max_length=24, default="v1.0")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("product",)
