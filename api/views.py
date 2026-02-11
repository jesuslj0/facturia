from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document, Company
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status
from documents.utils import normalize_tax

def get_review_level(confidence: dict, document_type):
    extraction_confidence = confidence.get("confianza_extraccion", 0)
    fecha_conf = confidence.get("fecha", 0)
    total_conf = confidence.get("total", 0)

    if extraction_confidence >= 0.9:
        return "auto"

    if extraction_confidence < 0.75:
        return "required"

    if fecha_conf < 0.7 or total_conf < 0.8:
        return "required"

    if document_type.lower() not in ["invoice", "delivery"]:
        return "required"

    return "recommended"


def get_status(review_level):
    return "approved" if review_level == "auto" else "pending"
class DocumentIngestAPIView(APIView):
    permission_classes = [HasApiKey]

    def post(self, request):
        serializer = DocumentIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data


        # Revisión y status
        review_level = get_review_level(
            confidence=data.get("confidence", {}),
            document_type=data["document_type"]
        )
        status = get_status(review_level)

        # Normalización de cantidades
        normalized_amounts = normalize_tax(
            data["base_amount"], 
            data["tax_amount"], 
            data["tax_percentage"], 
            data["total_amount"]
        )

        # Obtener o crear Company
        company, _created = Company.objects.get_or_create(
            client=request.client,
            tax_id=data["provider_tax_id"],
            defaults={
                "name": data["provider_name"],
                "type": data.get("provider_type", "provider"),
            }
        )

        document = Document.objects.create(
            client=request.client,
            company=company,
            external_id=data["external_id"],
            file=data["file"],
            original_name=data["original_name"],
            document_type=data["document_type"],
            invoice_number=data.get("invoice_number"),
            issue_date=data.get("issue_date"),
            base_amount = float(normalized_amounts.get("base") or 0),
            tax_amount = float(normalized_amounts.get("tax_amount") or 0),
            tax_percentage = float(normalized_amounts.get("tax_percentage") or 0),
            total_amount=float(normalized_amounts.get("total") or 0),
            confidence=data.get("confidence", {}),
            status=status,
            review_level=review_level,
            provider_name=company.name,
            provider_tax_id=company.tax_id,
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
            Document.objects.filter(client__clientuser__user=self.request.user)
            .order_by("-created_at")
        )
    