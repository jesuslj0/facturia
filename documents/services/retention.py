"""Retención de documentos (RGPD / obligación legal de conservar facturas).

`DOCUMENT_RETENTION_YEARS` (por defecto 10) marca cuánto se conserva un documento
desde su fecha de emisión (o de alta si no tiene fecha). Una cadena de rectificaciones
se conserva entera hasta que **todas** sus versiones han caducado.
"""
import logging
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from documents.models import Document

logger = logging.getLogger(__name__)


def retention_years() -> int:
    return int(getattr(settings, "DOCUMENT_RETENTION_YEARS", 10))


def cutoff_date(today=None, years=None) -> date:
    today = today or timezone.now().date()
    years = retention_years() if years is None else years
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 de febrero
        return today.replace(year=today.year - years, day=28)


def _reference_date(doc) -> date:
    return doc.issue_date or doc.created_at.date()


def _chain_root_id(doc):
    return doc.parent_document_id or doc.pk


def expired_chains(*, client=None, today=None, years=None):
    """Cadenas de versiones caducadas: lista de listas de `Document` (raíz primero)."""
    cutoff = cutoff_date(today, years)
    qs = Document.all_objects.select_related("stored_file")
    if client is not None:
        qs = qs.filter(client=client)
    chains = {}
    for doc in qs.order_by("version", "pk"):
        chains.setdefault((doc.client_id, _chain_root_id(doc)), []).append(doc)
    return [
        docs for docs in chains.values()
        if all(_reference_date(d) < cutoff for d in docs)
    ]


def purge_expired(*, apply=False, client=None, today=None, years=None) -> dict:
    """Borra documentos caducados y sus archivos. Sin `apply` solo cuenta (simulacro)."""
    chains = expired_chains(client=client, today=today, years=years)
    result = {"chains": len(chains), "documents": sum(len(c) for c in chains), "files": 0, "applied": apply}
    if not apply:
        return result
    for docs in chains:
        names = {d.file.name for d in docs if d.file and d.file.name}
        storage = docs[0].file.storage
        ids = [d.pk for d in docs]
        with transaction.atomic():
            # hijos antes que el padre (parent_document es PROTECT)
            for d in sorted(docs, key=lambda d: d.version, reverse=True):
                d.delete()
        for name in names:
            try:
                storage.delete(name)
                result["files"] += 1
            except Exception:  # noqa: BLE001  (el borrado en BD ya está hecho; se informa)
                logger.exception("retention: no se pudo borrar el archivo de los documentos %s", ids)
        logger.info("retention: purgados documentos %s (client=%s)", ids, docs[0].client_id)
    return result
