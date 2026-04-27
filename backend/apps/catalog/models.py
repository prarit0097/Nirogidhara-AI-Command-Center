"""Phase 3E — Product Catalog (Master Blueprint §5 / §24 #1).

Three tables: ``ProductCategory``, ``Product``, ``ProductSKU``. The catalog is
admin/director-managed via Django admin + read endpoints under
``/api/catalog/``.

COMPLIANCE HARD STOP (Master Blueprint §26 #4):
    A Product / ProductSKU row is metadata only. AI must NOT speak medical
    benefits from this catalog — those still come from
    ``apps.compliance.Claim`` (the Approved Claim Vault). The optional
    ``Product.active_claims`` link points at Claim rows only as a join
    aid; it does not authorize the AI to invent text.
"""
from __future__ import annotations

from django.db import models


class ProductCategory(models.Model):
    """Top-level wellness category (Weight Management, Joint Care, etc.)."""

    id = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Product Category"
        verbose_name_plural = "Product Categories"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class Product(models.Model):
    """A sellable Ayurvedic product. SKUs are variants of the product."""

    id = models.CharField(primary_key=True, max_length=40)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="products",
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True, default="")
    default_price_inr = models.PositiveIntegerField(default=3000)
    default_quantity_label = models.CharField(
        max_length=80, default="30 capsules"
    )
    product_cost_inr = models.PositiveIntegerField(blank=True, null=True)
    default_usage_instructions = models.TextField(blank=True, default="")
    # Optional join to Claim Vault entries that already cover this product.
    # NOT a permission grant — AI still consults apps.compliance.Claim only.
    active_claim_products = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of `Claim.product` keys (strings) covering this product. "
            "Display-only join aid — AI generation still goes through the "
            "Approved Claim Vault."
        ),
    )
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category__sort_order", "name")
        indexes = (models.Index(fields=("is_active",)),)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


class ProductSKU(models.Model):
    """A purchasable variant of a Product (specific size / pricing tier)."""

    id = models.CharField(primary_key=True, max_length=48)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="skus",
    )
    sku_code = models.CharField(max_length=80, unique=True)
    title = models.CharField(max_length=160, blank=True, default="")
    quantity_label = models.CharField(max_length=80, default="30 capsules")
    mrp_inr = models.PositiveIntegerField(default=0)
    selling_price_inr = models.PositiveIntegerField(default=0)
    product_cost_inr = models.PositiveIntegerField(blank=True, null=True)
    stock_quantity = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("product__name", "selling_price_inr")
        indexes = (
            models.Index(fields=("product",)),
            models.Index(fields=("is_active",)),
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.sku_code} · {self.title or self.product.name}"
