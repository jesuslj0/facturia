from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status

class DocumentIngestAPIView(APIView):
    permission_classes = [HasApiKey]

    def post(self, request):
        serializer = DocumentIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        confidence = data["confidence"]
        status = (
            "approved" if confidence >= 0.9
            else "pending" if confidence >= 0.7
            else "needs_review"
        )

        extracted = data["extracted_data"]

        document = Document.objects.create(
            client=request.client,
            external_id=data["external_id"],
            file=data["file"],
            original_name=data["original_name"],
            document_type=data["document_type"],
            confidence=confidence,
            status=status,
            extracted_data=extracted,
            provider_name=extracted.get("proveedor"),
            provider_tax_id=extracted.get("cif_nif"),
            total_amount=extracted.get("total"),
            issue_date=extracted.get("fecha"),
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
    