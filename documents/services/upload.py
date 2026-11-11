"""Subida de documentos desde la app (H6): validar, deduplicar por hash, crear y encolar.

El documento nace `pending` / `uploaded` / flujo `unknown` y sin datos: los rellena
la extracción asíncrona (`documents.services.processing`).
"""
import os
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction

from billing_ai.storage import sha256_of
from documents.models import Document, DocumentAuditLog, DocumentFile
from documents.services.duplicates import find_duplicate_by_hash
from documents.services.preprocess import detect_mime
from documents.services.processing import enqueue_processing

CREATED, DUPLICATE, REJECTED = "created", "duplicate", "rejected"
ORIGINS = ("upload", "mobile")


@dataclass
class UploadResult:
    name: str
    status: str                      # created | duplicate | rejected
    message: str = ""
    document: Document | None = None  # el creado o, si es duplicado, el existente


def upload_document(*, client, user, uploaded, origin: str = "upload") -> UploadResult:
    """Crea un documento a partir de un archivo subido. Nunca lanza por datos del usuario."""
    name = os.path.basename(getattr(uploaded, "name", "") or "documento")[:255]
    origin = origin if origin in ORIGINS else "upload"

    max_mb = settings.UPLOAD_MAX_FILE_MB
    if uploaded.size > max_mb * 1024 * 1024:
        return UploadResult(name, REJECTED, f"supera el máximo de {max_mb} MB.")
    if uploaded.size == 0:
        return UploadResult(name, REJECTED, "el archivo está vacío.")

    uploaded.seek(0)
    mime = detect_mime(uploaded.read(16))
    uploaded.seek(0)
    if mime is None:
        return UploadResult(name, REJECTED, "tipo no permitido (PDF, JPG, PNG, WEBP, GIF o HEIC).")

    sha = sha256_of(uploaded)
    if sha is None:
        return UploadResult(name, REJECTED, "no se ha podido leer el archivo.")

    existing = find_duplicate_by_hash(client, sha)
    if existing is not None:
        return UploadResult(name, DUPLICATE, "ya estaba subido.", existing)

    try:
        with transaction.atomic():
            doc = Document.objects.create(
                client=client,
                original_name=name,
                file=uploaded,
                document_type="invoice",   # provisional; la extracción lo clasifica
                confidence={"estado": "sin_extraer"},   # el campo no admite {}; apply_extraction lo sustituye
                status="pending",
                review_level="required",
                flow="unknown",
                source="upload",
                processing_status="uploaded",
            )
            DocumentFile.objects.create(
                document=doc, client=client, sha256=sha, mime_type=mime,
                size_bytes=uploaded.size, origin=origin, uploaded_by=user,
            )
            DocumentAuditLog(
                document=doc, user=user, action="created", changes={"origin": origin},
            ).save()
            enqueue_processing(doc)
            doc.refresh_from_db(fields=["processing_status"])
    except IntegrityError:
        # Subida simultánea del mismo contenido: gana la primera.
        existing = find_duplicate_by_hash(client, sha)
        if existing is not None:
            return UploadResult(name, DUPLICATE, "ya estaba subido.", existing)
        raise
    return UploadResult(name, CREATED, "en cola para su extracción.", doc)


def upload_many(*, client, user, files, origin: str = "upload") -> list[UploadResult]:
    return [upload_document(client=client, user=user, uploaded=f, origin=origin) for f in files]


def retry_processing(document) -> bool:
    """Relanza un documento fallido (False si no procede)."""
    if document.processing_status != "failed" or document.status != "pending" or document.is_archived:
        return False
    return enqueue_processing(document)
