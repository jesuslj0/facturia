"""Orquesta extractor principal + respaldo y registra cada intento en ExtractionRun.

No modifica el `Document`: devuelve el resultado normalizado y deja la decisión
de aplicarlo (y la política de revisión) a la capa superior (tarea H4 / validación H5).

Política de respaldo (Sonnet):
  - el principal devuelve una respuesta inválida o es rechazado, o
  - la confianza global < settings.EXTRACTION_FALLBACK_CONFIDENCE, o
  - el `validator` opcional (H5) devuelve problemas.
Los errores reintentables (límite de peticiones, timeout, caída) NO activan el
respaldo: se registran y se relanzan para que la cola reintente con backoff.
"""
import logging
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.utils import timezone

from .base import ExtractionError, ExtractionInput, ExtractionOutput, Extractor
from .normalize import NormalizedExtraction, normalize
from .pricing import estimate_cost

logger = logging.getLogger(__name__)

Validator = Callable[[NormalizedExtraction], list]


@dataclass
class ExtractionOutcome:
    run: "object"                       # ExtractionRun elegido
    normalized: NormalizedExtraction
    output: ExtractionOutput
    used_fallback: bool


def build_extractors() -> tuple[Extractor, Extractor | None]:
    """Crea (principal, respaldo) desde settings. Importa aquí para no exigir `anthropic` al importar el módulo."""
    from .claude import ClaudeExtractor

    common = dict(
        max_tokens=settings.EXTRACTION_MAX_TOKENS,
        timeout=settings.EXTRACTION_TIMEOUT_SECONDS,
        api_key=settings.ANTHROPIC_API_KEY,
    )
    primary = ClaudeExtractor(settings.EXTRACTION_MODEL, effort=settings.EXTRACTION_EFFORT, **common)
    fb_model = settings.EXTRACTION_FALLBACK_MODEL
    fallback = (
        ClaudeExtractor(fb_model, effort=settings.EXTRACTION_FALLBACK_EFFORT, **common)
        if fb_model and fb_model != settings.EXTRACTION_MODEL else None
    )
    return primary, fallback


def run_extraction(
    document,
    content: bytes,
    mime_type: str,
    *,
    extractor: Extractor | None = None,
    fallback: Extractor | None = None,
    validator: Validator | None = None,
) -> ExtractionOutcome:
    if extractor is None:
        extractor, built_fb = build_extractors()
        fallback = fallback if fallback is not None else built_fb

    client = document.client
    inp = ExtractionInput(
        content=content, mime_type=mime_type,
        client_name=client.name or "", client_tax_id=client.tax_id or "",
    )

    primary_run, primary_out, primary_norm = _attempt(document, extractor, inp, is_fallback=False, raise_on=None)
    # `primary_run` None => el principal falló pero es elegible para respaldo.
    problems: list = []
    if primary_norm is not None and validator is not None:
        problems = list(validator(primary_norm))
    low_conf = (
        primary_norm is not None
        and primary_norm.confidence_global < settings.EXTRACTION_FALLBACK_CONFIDENCE
    )
    need_fallback = fallback is not None and (primary_norm is None or low_conf or bool(problems))

    if not need_fallback:
        if primary_norm is None:
            raise primary_run  # type: ignore[misc]  (excepción guardada)
        return ExtractionOutcome(primary_run, primary_norm, primary_out, used_fallback=False)

    try:
        fb_run, fb_out, fb_norm = _attempt(document, fallback, inp, is_fallback=True, raise_on="all")
    except ExtractionError:
        if primary_norm is not None:  # el respaldo falló pero el principal sirve
            return ExtractionOutcome(primary_run, primary_norm, primary_out, used_fallback=False)
        raise
    return ExtractionOutcome(fb_run, fb_norm, fb_out, used_fallback=True)


def _attempt(document, extractor: Extractor, inp: ExtractionInput, *, is_fallback: bool, raise_on):
    """Ejecuta un intento y lo registra.

    Devuelve (run, output, normalized). Si el intento falla:
      - retryable -> se relanza siempre;
      - fallback_eligible y no es el respaldo -> devuelve (excepción, None, None);
      - resto -> se relanza.
    """
    from documents.models import ExtractionRun

    attempt_no = document.extraction_runs.count() + 1
    run = ExtractionRun.objects.create(
        client=document.client, document=document, status="running",
        model=extractor.model, is_fallback=is_fallback, attempt=attempt_no,
        prompt_version="", started_at=timezone.now(),
    )
    try:
        out = extractor.extract(inp)
    except ExtractionError as exc:
        _finish_failed(run, exc, extractor.model)
        if exc.retryable or is_fallback or not exc.fallback_eligible:
            raise
        return exc, None, None  # el llamador decide pasar al respaldo
    norm = normalize(out.result, client_tax_id=inp.client_tax_id)
    run.status = "succeeded"
    run.model = out.model
    run.prompt_version = out.prompt_version
    run.raw_response = {
        "parsed": out.result.model_dump(mode="json"),
        "stop_reason": out.stop_reason, "request_id": out.request_id,
    }
    run.confidence = round(norm.confidence_global, 4)
    run.input_tokens = out.usage.input_tokens
    run.output_tokens = out.usage.output_tokens
    run.cache_read_tokens = out.usage.cache_read_tokens
    run.cache_creation_tokens = out.usage.cache_creation_tokens
    run.cost_usd = estimate_cost(out.model, out.usage)
    run.finished_at = timezone.now()
    run.save()
    return run, out, norm


def _finish_failed(run, exc: ExtractionError, model: str) -> None:
    run.status = "failed"
    run.error_code = exc.code
    run.error_message = str(exc)[:1000]   # sin contenido del documento
    run.input_tokens = exc.usage.input_tokens
    run.output_tokens = exc.usage.output_tokens
    run.cache_read_tokens = exc.usage.cache_read_tokens
    run.cache_creation_tokens = exc.usage.cache_creation_tokens
    run.cost_usd = estimate_cost(model, exc.usage)
    run.finished_at = timezone.now()
    run.save()
    logger.warning("extraction failed run=%s code=%s retryable=%s", run.pk, exc.code, exc.retryable)
