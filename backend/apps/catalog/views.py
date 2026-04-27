"""Phase 3E — Catalog read/write endpoints.

Read endpoints are public (consistent with the rest of the API). Write
endpoints (create / update / delete) gate on ``ADMIN_AND_UP`` so only
admin or director can mutate the catalog. Operations and Viewer roles
are blocked from writes.

Audit ledger entries are written via :func:`apps.audit.signals.write_event`
in a service helper kept inline here for now — the catalog is a small
surface and the writes are simple.
"""
from __future__ import annotations

from rest_framework import mixins, viewsets

from apps.accounts.permissions import ADMIN_AND_UP, RoleBasedPermission
from apps.audit.models import AuditEvent
from apps.audit.signals import write_event

from .models import Product, ProductCategory, ProductSKU
from .serializers import (
    ProductCategorySerializer,
    ProductSerializer,
    ProductSKUSerializer,
)


class _CatalogWritePermission(RoleBasedPermission):
    """Reads stay public; writes require admin/director."""

    allowed_roles = ADMIN_AND_UP


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all().order_by("sort_order", "name")
    serializer_class = ProductCategorySerializer
    pagination_class = None
    permission_classes = [_CatalogWritePermission]

    def perform_create(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.category.created",
            text=f"Catalog category '{instance.name}' created",
            tone=AuditEvent.Tone.INFO,
            payload={
                "category_id": instance.id,
                "by": getattr(self.request.user, "username", ""),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.category.updated",
            text=f"Catalog category '{instance.name}' updated",
            tone=AuditEvent.Tone.INFO,
            payload={
                "category_id": instance.id,
                "by": getattr(self.request.user, "username", ""),
            },
        )


class ProductViewSet(viewsets.ModelViewSet):
    queryset = (
        Product.objects.all()
        .select_related("category")
        .prefetch_related("skus")
        .order_by("category__sort_order", "name")
    )
    serializer_class = ProductSerializer
    pagination_class = None
    permission_classes = [_CatalogWritePermission]

    def perform_create(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.product.created",
            text=(
                f"Product '{instance.name}' added to catalog "
                f"(category={instance.category_id})"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "product_id": instance.id,
                "category_id": instance.category_id,
                "by": getattr(self.request.user, "username", ""),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.product.updated",
            text=f"Product '{instance.name}' updated",
            tone=AuditEvent.Tone.INFO,
            payload={
                "product_id": instance.id,
                "by": getattr(self.request.user, "username", ""),
            },
        )


class ProductSKUViewSet(viewsets.ModelViewSet):
    queryset = (
        ProductSKU.objects.all()
        .select_related("product")
        .order_by("product__name", "selling_price_inr")
    )
    serializer_class = ProductSKUSerializer
    pagination_class = None
    permission_classes = [_CatalogWritePermission]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get("productId")
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.sku.created",
            text=(
                f"SKU '{instance.sku_code}' added "
                f"({instance.quantity_label} · ₹{instance.selling_price_inr})"
            ),
            tone=AuditEvent.Tone.SUCCESS,
            payload={
                "sku_id": instance.id,
                "product_id": instance.product_id,
                "by": getattr(self.request.user, "username", ""),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        write_event(
            kind="catalog.sku.updated",
            text=f"SKU '{instance.sku_code}' updated",
            tone=AuditEvent.Tone.INFO,
            payload={
                "sku_id": instance.id,
                "by": getattr(self.request.user, "username", ""),
            },
        )
