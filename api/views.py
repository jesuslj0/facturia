from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status

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

        extracted = data["extracted_data"] or {}
        confidence = data["confidence"] or {}

        review_level = get_review_level(
            confidence=confidence,
            document_type=data["document_type"]
        )

        status = get_status(review_level)

        document = Document.objects.create(
            client=request.client,
            external_id=data["external_id"],
            file=data["file"],
            original_name=data["original_name"],
            document_type=data["document_type"],
            confidence=confidence,
            status=status,
            review_level=review_level,
            extracted_data=extracted,
            provider_name=extracted.get("proveedor"),
            provider_tax_id=extracted.get("cif_nif"),
            issue_date=extracted.get("fecha"),
            base_amount = float(data.get("base_amount") or 0),
            tax_amount = float(data.get("tax_amount") or 0),
            tax_percentage = float(data.get("tax_percentage") or 0),
            total_amount=float(data.get("total_amount") or extracted.get("total") or 0),
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
    