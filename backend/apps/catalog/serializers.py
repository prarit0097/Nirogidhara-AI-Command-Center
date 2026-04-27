"""Phase 3E — DRF serializers for the product catalog.

Backend snake_case → frontend camelCase via ``source=`` mapping, mirroring
the convention used across the rest of the codebase.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Product, ProductCategory, ProductSKU


class ProductCategorySerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active")
    sortOrder = serializers.IntegerField(source="sort_order")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = ProductCategory
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "isActive",
            "sortOrder",
            "createdAt",
            "updatedAt",
        )


class ProductSKUSerializer(serializers.ModelSerializer):
    productId = serializers.CharField(source="product_id")
    skuCode = serializers.CharField(source="sku_code")
    quantityLabel = serializers.CharField(source="quantity_label")
    mrpInr = serializers.IntegerField(source="mrp_inr")
    sellingPriceInr = serializers.IntegerField(source="selling_price_inr")
    productCostInr = serializers.IntegerField(
        source="product_cost_inr", allow_null=True, required=False
    )
    stockQuantity = serializers.IntegerField(
        source="stock_quantity", allow_null=True, required=False
    )
    isActive = serializers.BooleanField(source="is_active")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = ProductSKU
        fields = (
            "id",
            "productId",
            "skuCode",
            "title",
            "quantityLabel",
            "mrpInr",
            "sellingPriceInr",
            "productCostInr",
            "stockQuantity",
            "isActive",
            "metadata",
            "createdAt",
            "updatedAt",
        )


class ProductSerializer(serializers.ModelSerializer):
    categoryId = serializers.CharField(source="category_id")
    defaultPriceInr = serializers.IntegerField(source="default_price_inr")
    defaultQuantityLabel = serializers.CharField(source="default_quantity_label")
    productCostInr = serializers.IntegerField(
        source="product_cost_inr", allow_null=True, required=False
    )
    defaultUsageInstructions = serializers.CharField(
        source="default_usage_instructions", required=False, allow_blank=True
    )
    activeClaimProducts = serializers.JSONField(source="active_claim_products")
    isActive = serializers.BooleanField(source="is_active")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    skus = ProductSKUSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "categoryId",
            "name",
            "slug",
            "description",
            "defaultPriceInr",
            "defaultQuantityLabel",
            "productCostInr",
            "defaultUsageInstructions",
            "activeClaimProducts",
            "isActive",
            "metadata",
            "createdAt",
            "updatedAt",
            "skus",
        )
