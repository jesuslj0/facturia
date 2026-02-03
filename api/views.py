from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status

def get_review_level(confidence, document_type, extracted, total_amount):
    if confidence >= 0.9:
        return "auto"

    if confidence < 0.75:
        return "required"

    if document_type == "Otro":
        return "required"

    if not total_amount or not extracted.get("fecha"):
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

        extracted = data["extracted_data"]
        confidence = data["confidence"]

        review_level = get_review_level(
            confidence=confidence,
            document_type=data["document_type"],
            extracted=extracted,
            total_amount=data["total_amount"],
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
            base_amount=data["base_amount"],
            tax_amount=data["tax_amount"],
            tax_percentage=data["tax_percentage"],
            total_amount=data["total_amount"],
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
    