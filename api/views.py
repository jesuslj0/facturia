from .serializers import DocumentIngestSerializer, DocumentSerializer, DocumentListSerializer
from documents.models import Document, Company
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .permissions import HasApiKey
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as rst_status
from documents.utils import normalize_tax
from rest_framework.exceptions import ValidationError

def get_review_level(confidence: dict, document_type):
    extraction_confidence = confidence.get("confianza_extraccion", 0.0)
    fecha_conf = confidence.get("fecha", 0.0)
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

def normalize_tax_id(tax_id):
    if not tax_id:
        return None
    return tax_id.replace(" ", "").replace("-", "").upper()

def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return name.strip()

from django.db import transaction, IntegrityError

@transaction.atomic
def get_or_create_company(*, client, name: str, tax_id: str | None, is_provider: bool = False, is_customer: bool = False):
    tax_id = normalize_tax_id(tax_id)
    name = normalize_name(name)
    company = None

    # 1️⃣ Buscar por CIF
    if tax_id:
        company = (
            Company.objects
            .select_for_update()
            .filter(client=client, tax_id=tax_id)
            .first()
        )

    # 2️⃣ Buscar por nombre
    if not company and name:
        company = (
            Company.objects
            .select_for_update()
            .filter(client=client, name__iexact=name)
            .first()
        )

    if company:
        # 🔥 Actualizar roles si hace falta
        updated = False

        if is_provider and not company.is_provider:
            company.is_supplier = True
            updated = True

        if is_customer and not company.is_customer:
            company.is_customer = True
            updated = True

        if updated:
            company.save(update_fields=["is_provider", "is_customer"])

        return company

    # 3️⃣ Crear con protección contra race condition
    try:
        company = Company.objects.create(
            client=client,
            name=name,
            tax_id=tax_id,
            is_provider=is_provider,
            is_customer=is_customer
        )
    except IntegrityError:
        # Otro proceso la creó justo antes
        if tax_id:
            company = Company.objects.filter(client=client, tax_id=tax_id).first()
        if not company and name:
            company = Company.objects.filter(client=client, name__iexact=name).first()

    return company


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
            "in": {"is_provider": True},
            "out": {"is_customer": True},
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
            base_amount = float(normalized_amounts.get("base") or 0),
            tax_amount = float(normalized_amounts.get("tax_amount") or 0),
            tax_percentage = float(normalized_amounts.get("tax_percentage") or 0),
            total_amount=float(normalized_amounts.get("total") or 0),
            confidence=data.get("confidence", {}),
            status=status,
            review_level=review_level,
            is_auto_approved=is_auto_approved,
            confidence_global=confidence_global,
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
            Document.objects.filter(client__clientuser__user=self.request.user)
            .order_by("-created_at")
        )
    