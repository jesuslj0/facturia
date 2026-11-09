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
    authentication_classes = []
    permission_classes = [HasApiKey]

    def post(self, request):
        serializer = DocumentIngestSerializer(
            data=request.data,
            context={"client": request.client},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Revisión y status
        review_level = get_review_level(
            confidence=data.get("confidence", {}),
            document_type=data["document_type"]
        )
        status = get_status(review_level)

        is_auto_approved = review_level == "auto"

        # Normalización de cantidades
        normalized_amounts = normalize_tax(
            data["base_amount"], 
            data["tax_amount"], 
            data["tax_percentage"], 
            data["total_amount"]
        )

        #Inferir tipo de company
        FLOW_ROLE_MAP = {
            "in": {"is_customer": True},
            "out": {"is_provider": True},
        }

        flow = (data.get("flow") or "").strip().lower()

        if flow not in FLOW_ROLE_MAP:
            raise ValidationError("Flow inválido")

        roles = FLOW_ROLE_MAP[flow]

        company = get_or_create_company(
            client=request.client,
            name=data["provider_name"],
            tax_id=data["provider_tax_id"],
            **roles
        )

        confidence_dict = data.get("confidence") or {}
        confidence_global = confidence_dict.get("confianza_extraccion", 0.0)

        document = Document.objects.create(
            client=request.client,
            company=company,
            external_id=data["external_id"],
            file=data["file"],
            original_name=data["original_name"],
            document_type=data["document_type"],
            document_number=data.get("document_number"),
            issue_date=data.get("issue_date"),
            base_amount = normalized_amounts.get("base") or 0,
            tax_amount = normalized_amounts.get("tax_amount") or 0,
            tax_percentage = normalized_amounts.get("tax_percentage") or 0,
            total_amount=normalized_amounts.get("total") or 0,
            confidence=data.get("confidence", {}),
            status=status,
            review_level=review_level,
            is_auto_approved=is_auto_approved,
            confidence_global=round_decimal(confidence_global, 4),
            flow=flow
        )

        return Response(
            DocumentSerializer(document).data,
            status=rst_status.HTTP_201_CREATED,
        )



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