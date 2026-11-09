"""Procesado asíncrono de documentos: encolar, reclamar (idempotencia) y ejecutar.

Estados (`Document.processing_status`):
    uploaded -> queued -> processing -> processed
                              ^   \\-> queued (error reintentable, espera backoff)
                              \\-----> failed   (error definitivo; se puede relanzar)
"""
import logging
import random
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from documents.models import Document, DocumentAuditLog, ExtractionRun
from documents.services import validation
from documents.services.apply import apply_extraction
from documents.services.extraction import (
    ExtractionError, RateLimitedError, build_extractors, run_extraction,
)
from documents.services.preprocess import (
    PreprocessError, load_and_preprocess, record_file_metadata,
)

logger = logging.getLogger(__name__)

CLAIMABLE = ("uploaded", "queued", "failed")


def enqueue_processing(document, *, force: bool = False) -> bool:
    """Marca como `queued` y encola la tarea al confirmarse la transacción.

    Devuelve False si no procede (ya procesado/en curso y sin `force`).
    """
    from documents.tasks import process_document

    allowed = ("uploaded", "failed", "queued") + (("processed", "processing") if force else ())
    updated = Document.all_objects.filter(pk=document.pk, processing_status__in=allowed).update(
        processing_status="queued"
    )
    if not updated:
        return False
    transaction.on_commit(lambda: process_document.delay(document.pk))
    return True


def claim_document(document_id) -> Document | None:
    """Reserva el documento para este worker; None si otro lo tiene o ya no procede.

    Atómico: un único UPDATE condicional. Un documento `processing` sin actividad
    reciente (worker caído) se puede reclamar de nuevo.
    """
    now = timezone.now()
    qs = Document.all_objects.filter(pk=document_id, status="pending", is_archived=False)
    if qs.filter(processing_status__in=CLAIMABLE).update(
        processing_status="processing", processing_started_at=now
    ):
        return Document.all_objects.get(pk=document_id)
    stale_before = now - timedelta(minutes=settings.EXTRACTION_STALE_MINUTES)
    stale = qs.filter(processing_status="processing").filter(
        Q(processing_started_at__lt=stale_before) | Q(processing_started_at__isnull=True)
    )
    if stale.update(processing_started_at=now):
        logger.warning("document %s: reclamado tras inactividad", document_id)
        return Document.all_objects.get(pk=document_id)
    return None


def run_processing(document_id, *, extractor=None, fallback=None, validator=None) -> str:
    """Ejecuta el pipeline completo. Devuelve 'processed' | 'failed' | 'skipped'.

    Lanza el `ExtractionError` original si es reintentable (la tarea reintenta);
    en ese caso el documento queda `queued`.
    """
    doc = claim_document(document_id)
    if doc is None:
        return "skipped"
    try:
        pre = load_and_preprocess(doc)
    except PreprocessError as exc:
        _fail(doc, exc.code, str(exc))
        return "failed"

    if validator is None:
        validator = fallback_validator(doc)
    try:
        outcome = run_extraction(
            doc, pre.content, pre.mime_type, extractor=extractor, fallback=fallback, validator=validator,
        )
    except ExtractionError as exc:
        if exc.retryable:
            Document.all_objects.filter(pk=doc.pk).update(processing_status="queued")
            raise
        _mark_failed(doc, exc.code)
        return "failed"
    except Exception as exc:  # noqa: BLE001  (error inesperado: no dejar el documento colgado)
        logger.exception("document %s: error inesperado en la extracción", doc.pk)
        closed = doc.extraction_runs.filter(status="running").update(
            status="failed", error_code="unexpected_error",
            error_message=type(exc).__name__, finished_at=timezone.now(),
        )
        if closed:
            _mark_failed(doc, "unexpected_error")
        else:
            _fail(doc, "unexpected_error", type(exc).__name__)
        return "failed"

    try:
        apply_extraction(doc, outcome)
        record_file_metadata(doc, pre)
    except Exception as exc:  # noqa: BLE001  (p. ej. ValidationError al guardar)
        logger.exception("document %s: no se pudo aplicar la extracción", doc.pk)
        _fail(doc, "apply_failed", f"{type(exc).__name__}")
        return "failed"
    return "processed"


def fallback_validator(doc):
    """Incidencias que otro modelo podría resolver: si las hay, se prueba el respaldo."""
    def check(normalized):
        return validation.fallback_problems(
            validation.validate(normalized, client=doc.client, document=doc)
        )
    return check


def mark_failed_after_retries(document_id, exc: ExtractionError) -> None:
    doc = Document.all_objects.filter(pk=document_id).first()
    if doc is not None:
        _mark_failed(doc, f"{exc.code}_retries_exhausted")


def retry_delay(retries: int, exc: Exception | None = None) -> int:
    """Backoff exponencial con jitter; respeta `retry-after` del proveedor como mínimo."""
    base = settings.EXTRACTION_RETRY_BASE_SECONDS * (2 ** retries)
    delay = min(base, settings.EXTRACTION_RETRY_MAX_SECONDS)
    delay = delay * random.uniform(0.8, 1.2)
    if isinstance(exc, RateLimitedError) and exc.retry_after:
        delay = max(delay, exc.retry_after)
    return int(delay)


def _fail(doc, code: str, message: str) -> None:
    """Fallo definitivo sin intento de extracción registrado (preprocesado/aplicación)."""
    ExtractionRun.objects.create(
        client=doc.client, document=doc, status="failed", model="", error_code=code,
        error_message=message[:1000], attempt=doc.extraction_runs.count() + 1,
        started_at=timezone.now(), finished_at=timezone.now(),
    )
    _mark_failed(doc, code)


def _mark_failed(doc, code: str) -> None:
    Document.all_objects.filter(pk=doc.pk).update(processing_status="failed")
    DocumentAuditLog(document=doc, action="extracted", changes={"failed": True, "error": code}).save()
    logger.warning("document %s: procesado fallido (%s)", doc.pk, code)
