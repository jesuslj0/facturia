"""Extracción diferida con la Message Batches API de Anthropic (H9).

Pensada para cargas masivas (importación histórica): ~50 % más barata y sin límites de
tasa por petición, a cambio de latencia (hasta 24 h). Dos pasos:

  submit_batches()  → preprocesa los documentos, los envía en lotes y los deja `batched`.
  collect_batches() → recoge los lotes terminados y aplica cada resultado con el mismo
                      pipeline que el flujo normal (normalizar → validar → apply_extraction).

Un documento `batched` no lo toca la cola de Celery. Si una petición del lote falla
(error, caducada, respuesta inválida), el documento vuelve a `uploaded` y se encola por el
flujo normal, que sí tiene reintentos y respaldo a Sonnet.
"""
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .base import ExtractionError, ExtractionInput, ExtractionOutput, InvalidResponseError, Usage
from .normalize import normalize
from .pricing import estimate_cost
from .prompts import PROMPT_VERSION
from .runner import ExtractionOutcome
from .schemas import ExtractionResult

logger = logging.getLogger(__name__)

MAX_REQUESTS_PER_BATCH = 1000
MAX_BYTES_PER_BATCH = 150 * 1024 * 1024   # la API admite 256 MB; margen por el base64


@dataclass
class SubmitReport:
    batches: int = 0
    submitted: int = 0
    skipped: int = 0      # no reclamados (otro proceso) o ya no procede
    failed: int = 0       # fallo de preprocesado (archivo dañado, demasiadas páginas…)


@dataclass
class CollectReport:
    pending_batches: int = 0
    collected_batches: int = 0
    applied: int = 0
    requeued: int = 0


def _api_client(api_client=None):
    if api_client is not None:
        return api_client
    import anthropic

    if not settings.ANTHROPIC_API_KEY:
        from .base import ConfigurationError
        raise ConfigurationError("Falta ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=settings.EXTRACTION_TIMEOUT_SECONDS)


def _extractor():
    from .claude import ClaudeExtractor

    return ClaudeExtractor(
        settings.EXTRACTION_MODEL, effort=settings.EXTRACTION_EFFORT,
        max_tokens=settings.EXTRACTION_MAX_TOKENS, api_key=settings.ANTHROPIC_API_KEY,
    )


def custom_id(document_id) -> str:
    return f"doc-{document_id}"


def _document_id(cid: str):
    try:
        return int(cid.removeprefix("doc-"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- envío

def eligible_documents(*, client=None, limit=None):
    from documents.models import Document

    qs = Document.all_objects.filter(
        processing_status__in=("uploaded", "failed"), status="pending", is_archived=False,
    ).select_related("client").order_by("pk")
    if client is not None:
        qs = qs.filter(client=client)
    return qs[:limit] if limit else qs


def _claim_for_batch(doc) -> bool:
    """UPDATE condicional (como `claim_document`): solo uno gana."""
    from documents.models import Document

    return bool(Document.all_objects.filter(
        pk=doc.pk, status="pending", is_archived=False, processing_status__in=("uploaded", "failed"),
    ).update(processing_status="batched", processing_started_at=timezone.now()))


def submit_batches(*, client=None, limit=None, api_client=None, extractor=None) -> SubmitReport:
    from documents.services.preprocess import PreprocessError, load_and_preprocess, record_file_metadata
    from documents.services.processing import _fail

    report = SubmitReport()
    extractor = extractor or _extractor()
    api = None
    items: list[tuple] = []     # (document, request dict)
    size = 0

    def flush():
        nonlocal items, size, api
        if not items:
            return
        api = api or _api_client(api_client)
        _send(api, extractor.model, items)
        report.batches += 1
        report.submitted += len(items)
        items, size = [], 0

    for doc in eligible_documents(client=client, limit=limit):
        if not _claim_for_batch(doc):
            report.skipped += 1
            continue
        try:
            pre = load_and_preprocess(doc)
            record_file_metadata(doc, pre)
            params = extractor.batch_params(ExtractionInput(
                content=pre.content, mime_type=pre.mime_type,
                client_name=doc.client.name or "", client_tax_id=doc.client.tax_id or "",
            ))
        except PreprocessError as exc:
            _fail(doc, exc.code, str(exc))
            report.failed += 1
            continue
        except ExtractionError as exc:
            _fail(doc, exc.code, str(exc))
            report.failed += 1
            continue
        except Exception:
            _release([doc])
            raise
        weight = len(pre.content) * 4 // 3
        if items and (len(items) >= MAX_REQUESTS_PER_BATCH or size + weight > MAX_BYTES_PER_BATCH):
            flush()
        items.append((doc, {"custom_id": custom_id(doc.pk), "params": params}))
        size += weight

    flush()
    return report


def _release(docs) -> None:
    from documents.models import Document

    Document.all_objects.filter(pk__in=[d.pk for d in docs], processing_status="batched").update(
        processing_status="uploaded", processing_started_at=None
    )


def _send(api, model: str, items) -> None:
    from documents.models import ExtractionBatch, ExtractionRun

    docs = [d for d, _ in items]
    try:
        remote = api.messages.batches.create(requests=[r for _, r in items])
    except Exception:
        _release(docs)    # nada se envió: que se puedan reintentar
        raise
    now = timezone.now()
    with transaction.atomic():
        batch = ExtractionBatch.objects.create(
            provider_batch_id=remote.id, model=model, request_count=len(items),
        )
        for doc in docs:
            ExtractionRun.objects.create(
                client=doc.client, document=doc, batch=batch, status="running", model=model,
                attempt=doc.extraction_runs.count() + 1, started_at=now,
            )
    logger.info("batch=%s enviado: %s documentos", remote.id, len(items))


# --------------------------------------------------------------------- recogida

def collect_batches(*, api_client=None) -> CollectReport:
    from documents.models import ExtractionBatch

    report = CollectReport()
    batches = list(ExtractionBatch.objects.filter(status="submitted").order_by("pk"))
    if not batches:
        return report
    api = _api_client(api_client)
    for batch in batches:
        remote = api.messages.batches.retrieve(batch.provider_batch_id)
        if remote.processing_status != "ended":
            report.pending_batches += 1
            continue
        _collect_one(api, batch, report)
        report.collected_batches += 1
    return report


def _collect_one(api, batch, report: CollectReport) -> None:
    from documents.models import Document

    runs = {r.document_id: r for r in batch.runs.select_related("document", "client").filter(status="running")}
    for entry in api.messages.batches.results(batch.provider_batch_id):
        doc_id = _document_id(entry.custom_id)
        run = runs.pop(doc_id, None)
        if run is None:
            continue    # ya recogido antes (idempotente) o ajeno
        doc = Document.all_objects.get(pk=run.document_id)
        outcome = _outcome(run, entry.result)
        if outcome is not None and doc.processing_status == "batched":
            _apply(doc, outcome)
            report.applied += 1
        elif doc.processing_status == "batched":
            _requeue(doc)
            report.requeued += 1
    # peticiones que no aparecen en los resultados: vuelven al flujo normal
    for run in runs.values():
        _finish_run_failed(run, "missing_result", "El lote no devolvió resultado")
        doc = Document.all_objects.get(pk=run.document_id)
        if doc.processing_status == "batched":
            _requeue(doc)
            report.requeued += 1
    batch.status = "collected"
    batch.collected_at = timezone.now()
    batch.save(update_fields=["status", "collected_at"])
    logger.info("batch=%s recogido", batch.provider_batch_id)


def _outcome(run, result):
    """Cierra el `ExtractionRun` con el resultado; devuelve el `ExtractionOutcome` o None si falló."""
    kind = result.type
    if kind != "succeeded":
        error = getattr(result, "error", None)
        code = getattr(getattr(error, "error", None), "type", None) or kind
        _finish_run_failed(run, f"batch_{kind}", str(code))
        return None
    message = result.message
    usage = _usage(message)
    stop = getattr(message, "stop_reason", None)
    try:
        if stop in ("refusal", "max_tokens"):
            raise InvalidResponseError(f"Respuesta no válida ({stop})")
        text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), "")
        parsed = ExtractionResult.model_validate_json(text)
    except Exception as exc:  # noqa: BLE001  (JSON inválido o esquema incumplido)
        _finish_run_failed(run, "invalid_response", type(exc).__name__, usage=usage, model=message.model)
        return None
    norm = normalize(parsed, client_tax_id=run.client.tax_id or "")
    model = getattr(message, "model", None) or run.model
    run.status = "succeeded"
    run.model = model
    run.prompt_version = PROMPT_VERSION
    run.raw_response = {"parsed": parsed.model_dump(mode="json"), "stop_reason": stop, "batch": True}
    run.confidence = round(norm.confidence_global, 4)
    _set_usage(run, usage, model)
    run.finished_at = timezone.now()
    run.save()
    output = ExtractionOutput(
        result=parsed, model=model, prompt_version=PROMPT_VERSION, usage=usage, stop_reason=stop,
    )
    return ExtractionOutcome(run, norm, output, used_fallback=False)


def _apply(doc, outcome) -> None:
    from documents.services.apply import apply_extraction
    from documents.services.processing import _fail

    try:
        apply_extraction(doc, outcome)
    except Exception as exc:  # noqa: BLE001
        logger.exception("document %s: no se pudo aplicar el resultado del lote", doc.pk)
        _fail(doc, "apply_failed", type(exc).__name__)


def _requeue(doc) -> None:
    from documents.models import Document
    from documents.services.processing import enqueue_processing

    Document.all_objects.filter(pk=doc.pk, processing_status="batched").update(
        processing_status="uploaded", processing_started_at=None
    )
    enqueue_processing(Document.all_objects.get(pk=doc.pk))


def _usage(message) -> Usage:
    u = getattr(message, "usage", None)
    g = lambda name: int(getattr(u, name, 0) or 0)  # noqa: E731
    return Usage(
        input_tokens=g("input_tokens"), output_tokens=g("output_tokens"),
        cache_read_tokens=g("cache_read_input_tokens"), cache_creation_tokens=g("cache_creation_input_tokens"),
    )


def _set_usage(run, usage: Usage, model: str) -> None:
    run.input_tokens = usage.input_tokens
    run.output_tokens = usage.output_tokens
    run.cache_read_tokens = usage.cache_read_tokens
    run.cache_creation_tokens = usage.cache_creation_tokens
    run.cost_usd = estimate_cost(model, usage, batch=True)


def _finish_run_failed(run, code: str, message: str, *, usage: Usage | None = None, model: str | None = None) -> None:
    run.status = "failed"
    run.error_code = code
    run.error_message = message[:1000]
    if usage is not None:
        _set_usage(run, usage, model or run.model)
    run.finished_at = timezone.now()
    run.save()
