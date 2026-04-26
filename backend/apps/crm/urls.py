from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, LeadViewSet

router = DefaultRouter()
router.register("leads", LeadViewSet, basename="lead")
router.register("customers", CustomerViewSet, basename="customer")

urlpatterns = router.urls
