from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import ProductCategoryViewSet, ProductSKUViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", ProductCategoryViewSet, basename="catalog-category")
router.register("products", ProductViewSet, basename="catalog-product")
router.register("skus", ProductSKUViewSet, basename="catalog-sku")

urlpatterns = router.urls
