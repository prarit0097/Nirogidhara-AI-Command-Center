from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, LeadImportCsvView, LeadViewSet

router = DefaultRouter()
router.register("leads", LeadViewSet, basename="lead")
router.register("customers", CustomerViewSet, basename="customer")

# Phase 16B — explicit non-router endpoint for CSV lead import.
# IMPORTANT: this path MUST come BEFORE router.urls because the DRF
# DefaultRouter registers ``^leads/(?P<pk>[^/.]+)/$`` which would
# otherwise capture ``leads/import-csv/`` as a Lead detail lookup.
# Mounted at /api/leads/import-csv/ (parent urls.py mounts apps.crm.urls
# at /api/ — see backend/config/urls.py).
urlpatterns = [
    path(
        "leads/import-csv/",
        LeadImportCsvView.as_view(),
        name="lead-import-csv",
    ),
] + router.urls
