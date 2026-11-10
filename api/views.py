from django.conf import settings
from documents.services.ingest import DuplicateFileError, ingest_document
from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document, Company
from documents.services.companies import get_or_create_company, normalize_name, normalize_tax_id  # noqa: F401
from documents.services.review import get_review_level, get_status  # noqa: F401
from documents.selectors.document_selector import DocumentSelector
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status
from documents.utils import normalize_tax, round_decimal  
from rest_framework.exceptions import ValidationError

class DocumentIngestAPIView(APIView):
    """Ingesta del contrato de n8n. Se mantiene mientras `N8N_INGEST_ENABLED` sea True (H10)."""
    authentication_classes = []
    permission_classes = [HasApiKey]

    def post(self, request):
        if not settings.N8N_INGEST_ENABLED:
            return Response(
                {"detail": "La ingesta externa está desactivada. Sube los documentos desde la aplicación."},
                status=rst_status.HTTP_410_GONE,
            )
        serializer = DocumentIngestSerializer(
            data=request.data,
            context={"client": request.client},
        )
        serializer.is_valid(raise_exception=True)
        try:
            document = ingest_document(request.client, serializer.validated_data, source="n8n", origin="n8n")
        except DuplicateFileError as dup:
            return Response(
                {"detail": "Ya existe un documento con el mismo contenido.", "document_id": dup.document.pk},
                status=rst_status.HTTP_409_CONFLICT,
            )
        return Response(DocumentSerializer(document).data, status=rst_status.HTTP_201_CREATED)


class DocumentListAPIView(ListAPIView):
    serializer_class = DocumentListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            DocumentSelector.for_client(self.request.user.client)
            .order_by("-created_at")
        )

from rest_framework.views import APIView
from documents.services import MetricsService
from django.utils.dateparse import parse_date

class MetricsDashboardView(APIView):

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        if not start or not end:
            raise ValidationError("Fechas inválidas. Formato requerido: YYYY-MM-DD")
        metrics = MetricsService.get_user_metrics(
            user=request.user,
            start=start,
            end=end
        )
        return Response(metrics)