"""Ingesta de documentos ya extraídos por un sistema externo (contrato de n8n).

La comparten el endpoint `POST /api/v1/documents/ingest/` y el comando `import_n8n`.
Los datos llegan validados por `DocumentIngestSerializer`. Un archivo con el mismo
contenido que otro del mismo cliente se rechaza (`DuplicateFileError`): así la
convivencia n8n + app no duplica facturas.
"""
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from billing_ai.storage import sha256_of
from documents.models import Document, DocumentAuditLog, DocumentFile
from documents.services.companies import get_or_create_company
from documents.services.duplicates import find_duplicate_by_hash
from documents.services.preprocess import detect_mime
from documents.services.review import get_review_level, get_status
from documents.utils import normalize_tax, round_decimal

FLOW_ROLE_MAP = {"in": {"is_customer": True}, "out": {"is_provider": True}}


class DuplicateFileError(Exception):
    def __init__(self, document):
        super().__init__("Ya existe un documento con el mismo contenido.")
        self.document = document


def ingest_document(client, data, *, source="n8n", origin="n8n") -> Document:
    flow = (data.get("flow") or "").strip().lower()
    if flow not in FLOW_ROLE_MAP:
        raise ValidationError("Flow inválido")

    upload = data["file"]
    sha = sha256_of(upload)
    if sha is not None:
        existing = find_duplicate_by_hash(client, sha)
        if existing is not None:
            raise DuplicateFileError(existing)

    review_level = get_review_level(
        confidence=data.get("confidence", {}), document_type=data["document_type"]
    )
    amounts = normalize_tax(
        data["base_amount"], data["tax_amount"], data["tax_percentage"], data["total_amount"]
    )
    confidence = data.get("confidence") or {}

    try:
        with transaction.atomic():
            company = get_or_create_company(
                client=client, name=data["provider_name"], tax_id=data["provider_tax_id"],
                **FLOW_ROLE_MAP[flow],
            )
            document = Document.objects.create(
                client=client,
                company=company,
                external_id=data["external_id"],
                file=upload,
                original_name=data["original_name"],
                document_type=data["document_type"],
                document_number=data.get("document_number"),
                issue_date=data.get("issue_date"),
                base_amount=amounts.get("base") or 0,
                tax_amount=amounts.get("tax_amount") or 0,
                tax_percentage=amounts.get("tax_percentage") or 0,
                total_amount=amounts.get("total") or 0,
                confidence=data.get("confidence", {}),
                status=get_status(review_level),
                review_level=review_level,
                is_auto_approved=review_level == "auto",
                confidence_global=round_decimal(confidence.get("confianza_extraccion", 0.0), 4),
                flow=flow,
                source=source,
                processing_status="processed",   # ya viene extraído: no pasa por la cola
            )
            if sha is not None:
                upload.seek(0)
                DocumentFile.objects.create(
                    document=document, client=client, sha256=sha,
                    mime_type=detect_mime(upload.read(16)) or "", size_bytes=upload.size, origin=origin,
                )
                upload.seek(0)
            DocumentAuditLog(document=document, action="created", changes={"source": source}).save()
    except IntegrityError:
        # Ingesta simultánea del mismo contenido: gana la primera.
        existing = find_duplicate_by_hash(client, sha) if sha else None
        if existing is not None:
            raise DuplicateFileError(existing) from None
        raise
    return document
