"""Phase 16D — Uploaded data → campaign → queue → order read/write API.

Internal-only, no external side effects. Upload + create-campaign require
director/admin; outcome + create-order also allow operations (calling agent);
all reads require authentication. CSV blobs + raw phones are never logged.
"""
from __future__ import annotations

from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import (
    ImportedCallingCampaign,
    ImportedCallQueueItem,
    ImportedDataRow,
    ImportedDataset,
)
from .permissions import AuthedReadAdminWrite, AuthedReadAgentWrite
from .serializers import (
    serialize_campaign,
    serialize_dataset,
    serialize_queue_item,
    serialize_row,
)

_MAX_CSV_CHARS = 5_000_000  # ~5 MB of text; bounded request body.


def _parse_int(raw, default: int, *, lo: int = 1, hi: int = 1000) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


class ImportsOverviewView(APIView):
    """``GET /api/v1/imports/overview/`` — read-only KPI dashboard."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request):
        return Response(services.get_imports_overview())


class DatasetsView(APIView):
    """``GET`` list datasets / (upload is the dedicated endpoint below)."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request):
        qs = ImportedDataset.objects.all().order_by("-created_at")
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=500)
        items = [serialize_dataset(d) for d in qs[:limit]]
        return Response({"items": items, "total": qs.count()})


class DatasetUploadView(APIView):
    """``POST /api/v1/imports/datasets/upload/`` — admin/director only.

    Body: ``{name, csv, sourceLabel?, problemCategory?, originalFilename?}``.
    Parses + validates the CSV into dataset + row rows. Creates NO Lead /
    Customer / Order. Returns the dataset + error samples + problem breakdown.
    """

    permission_classes = [AuthedReadAdminWrite]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        raw_csv = data.get("csv", "")
        if not isinstance(raw_csv, str) or not raw_csv.strip():
            return Response(
                {"detail": "csv_required", "field": "csv"}, status=400
            )
        if len(raw_csv) > _MAX_CSV_CHARS:
            return Response(
                {"detail": "csv_too_large", "field": "csv"}, status=400
            )
        name = str(data.get("name", "") or "").strip()
        if not name:
            return Response(
                {"detail": "name_required", "field": "name"}, status=400
            )

        dataset = services.parse_and_validate_dataset(
            raw_csv=raw_csv,
            name=name,
            by_user=request.user,
            source_label=str(data.get("sourceLabel", "") or ""),
            problem_category=str(data.get("problemCategory", "") or ""),
            original_filename=str(data.get("originalFilename", "") or ""),
        )
        body = serialize_dataset(dataset)
        body["errorSamples"] = services.dataset_error_samples(dataset, limit=20)
        body["problemBreakdown"] = services.problem_breakdown(dataset)
        return Response(body, status=201)


class DatasetDetailView(APIView):
    """``GET /api/v1/imports/datasets/<id>/`` — detail + samples + breakdown."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request, pk: int):
        dataset = ImportedDataset.objects.filter(pk=pk).first()
        if dataset is None:
            return Response({"detail": "not_found"}, status=404)
        body = serialize_dataset(dataset)
        body["errorSamples"] = services.dataset_error_samples(dataset, limit=20)
        body["problemBreakdown"] = services.problem_breakdown(dataset)
        body["campaignIds"] = list(
            dataset.campaigns.values_list("id", flat=True)
        )
        return Response(body)


class DatasetRowsView(APIView):
    """``GET /api/v1/imports/datasets/<id>/rows/?status=&limit=`` (masked phones)."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request, pk: int):
        dataset = ImportedDataset.objects.filter(pk=pk).first()
        if dataset is None:
            return Response({"detail": "not_found"}, status=404)
        qs = dataset.rows.all().order_by("row_number")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(validation_status=status_filter)
        limit = _parse_int(request.query_params.get("limit"), 200, lo=1, hi=1000)
        items = [serialize_row(r) for r in qs[:limit]]
        return Response({"items": items, "total": qs.count()})


class DatasetCreateCampaignView(APIView):
    """``POST /api/v1/imports/datasets/<id>/create-campaign/`` — admin/director."""

    permission_classes = [AuthedReadAdminWrite]

    def post(self, request, pk: int):
        dataset = ImportedDataset.objects.filter(pk=pk).first()
        if dataset is None:
            return Response({"detail": "not_found"}, status=404)
        if dataset.valid_rows <= 0:
            return Response(
                {"detail": "no_valid_rows", "field": "dataset"}, status=400
            )
        data = request.data if isinstance(request.data, dict) else {}
        campaign = services.create_campaign_from_dataset(
            dataset=dataset,
            by_user=request.user,
            name=str(data.get("name", "") or ""),
            problem_category=str(data.get("problemCategory", "") or ""),
            assigned_team=str(data.get("assignedTeam", "") or ""),
        )
        return Response(serialize_campaign(campaign), status=201)


class CampaignsView(APIView):
    """``GET /api/v1/imports/campaigns/?status=&limit=``."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request):
        qs = ImportedCallingCampaign.objects.all().order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit = _parse_int(request.query_params.get("limit"), 100, lo=1, hi=500)
        items = [serialize_campaign(c) for c in qs[:limit]]
        return Response({"items": items, "total": qs.count()})


class CampaignDetailView(APIView):
    """``GET /api/v1/imports/campaigns/<id>/``."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request, pk: int):
        campaign = ImportedCallingCampaign.objects.filter(pk=pk).first()
        if campaign is None:
            return Response({"detail": "not_found"}, status=404)
        return Response(serialize_campaign(campaign))


class CampaignQueueView(APIView):
    """``GET /api/v1/imports/campaigns/<id>/queue/?status=&limit=``."""

    permission_classes = [AuthedReadAdminWrite]

    def get(self, request, pk: int):
        campaign = ImportedCallingCampaign.objects.filter(pk=pk).first()
        if campaign is None:
            return Response({"detail": "not_found"}, status=404)
        qs = campaign.queue_items.select_related("data_row").order_by("id")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit = _parse_int(request.query_params.get("limit"), 200, lo=1, hi=1000)
        items = [serialize_queue_item(q) for q in qs[:limit]]
        return Response({"items": items, "total": qs.count()})


class QueueOutcomeView(APIView):
    """``POST /api/v1/imports/queue/<id>/outcome/`` — admin/director/operations."""

    permission_classes = [AuthedReadAgentWrite]

    def post(self, request, pk: int):
        item = (
            ImportedCallQueueItem.objects.select_related("data_row", "campaign")
            .filter(pk=pk)
            .first()
        )
        if item is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        outcome = str(data.get("outcome", "") or "")
        follow_up_raw = data.get("nextFollowUpAt")
        follow_up = parse_datetime(follow_up_raw) if follow_up_raw else None
        try:
            item = services.record_queue_outcome(
                queue_item=item,
                outcome=outcome,
                by_user=request.user,
                notes=str(data.get("notes", "") or ""),
                next_follow_up_at=follow_up,
            )
        except services.QueueOutcomeError as exc:
            return Response(
                {"detail": "invalid_outcome", "field": "outcome", "message": str(exc)},
                status=400,
            )
        return Response(serialize_queue_item(item), status=200)


class QueueCreateOrderView(APIView):
    """``POST /api/v1/imports/queue/<id>/create-order/`` — admin/director/operations.

    Creates an internal Order from an INTERESTED queue item via the existing
    safe order service. No payment / courier / WhatsApp side effect.
    """

    permission_classes = [AuthedReadAgentWrite]

    def post(self, request, pk: int):
        item = (
            ImportedCallQueueItem.objects.select_related("data_row", "campaign")
            .filter(pk=pk)
            .first()
        )
        if item is None:
            return Response({"detail": "not_found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            order = services.create_order_from_queue_item(
                queue_item=item,
                by_user=request.user,
                product=str(data.get("product", "") or ""),
                amount=_parse_int(data.get("amount"), 3000, lo=0, hi=10_000_000),
                quantity=_parse_int(data.get("quantity"), 1, lo=1, hi=100),
            )
        except services.QueueOrderError as exc:
            return Response(
                {"detail": "order_not_allowed", "message": str(exc)}, status=400
            )
        item.refresh_from_db()
        return Response(
            {
                "queueItem": serialize_queue_item(item),
                "orderId": order.id,
                "orderStage": order.stage,
            },
            status=201,
        )
