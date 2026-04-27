"""Phase 3E — Django admin for the product catalog.

Admin/director can manage categories, products, and SKUs from the Django
admin UI without needing the React frontend (which currently does not have
a catalog page yet — Phase 4+ adds it).
"""
from __future__ import annotations

from django.contrib import admin

from .models import Product, ProductCategory, ProductSKU


class ProductSKUInline(admin.TabularInline):
    model = ProductSKU
    extra = 0
    fields = (
        "id",
        "sku_code",
        "title",
        "quantity_label",
        "mrp_inr",
        "selling_price_inr",
        "product_cost_inr",
        "stock_quantity",
        "is_active",
    )


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("id", "name", "slug")
    ordering = ("sort_order", "name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
        "default_price_inr",
        "default_quantity_label",
        "is_active",
        "updated_at",
    )
    list_filter = ("category", "is_active")
    search_fields = ("id", "name", "slug")
    ordering = ("category__sort_order", "name")
    inlines = [ProductSKUInline]


@admin.register(ProductSKU)
class ProductSKUAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sku_code",
        "product",
        "quantity_label",
        "mrp_inr",
        "selling_price_inr",
        "stock_quantity",
        "is_active",
    )
    list_filter = ("is_active", "product__category")
    search_fields = ("id", "sku_code", "title", "product__name")
    ordering = ("product__name", "selling_price_inr")
