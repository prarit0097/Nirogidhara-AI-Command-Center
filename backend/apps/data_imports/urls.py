"""Phase 16D — data-imports URLs (mounted at /api/v1/imports/)."""
from __future__ import annotations

from django.urls import path

from .views import (
    CampaignDetailView,
    CampaignQueueView,
    CampaignsView,
    DatasetCreateCampaignView,
    DatasetDetailView,
    DatasetRowsView,
    DatasetUploadView,
    DatasetsView,
    ImportsOverviewView,
    QueueCreateOrderView,
    QueueOutcomeView,
)

app_name = "data_imports"

urlpatterns = [
    path("overview/", ImportsOverviewView.as_view(), name="overview"),
    path("datasets/", DatasetsView.as_view(), name="datasets"),
    path("datasets/upload/", DatasetUploadView.as_view(), name="datasets-upload"),
    path("datasets/<int:pk>/", DatasetDetailView.as_view(), name="datasets-detail"),
    path("datasets/<int:pk>/rows/", DatasetRowsView.as_view(), name="datasets-rows"),
    path(
        "datasets/<int:pk>/create-campaign/",
        DatasetCreateCampaignView.as_view(),
        name="datasets-create-campaign",
    ),
    path("campaigns/", CampaignsView.as_view(), name="campaigns"),
    path("campaigns/<int:pk>/", CampaignDetailView.as_view(), name="campaigns-detail"),
    path(
        "campaigns/<int:pk>/queue/",
        CampaignQueueView.as_view(),
        name="campaigns-queue",
    ),
    path("queue/<int:pk>/outcome/", QueueOutcomeView.as_view(), name="queue-outcome"),
    path(
        "queue/<int:pk>/create-order/",
        QueueCreateOrderView.as_view(),
        name="queue-create-order",
    ),
]
