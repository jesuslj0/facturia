"""Detección de duplicados: por contenido (hash) y por emisor + número de factura."""
from documents.models import Document, DocumentFile


def find_duplicate_by_hash(client, sha256: str):
    """Documento ya subido con el mismo contenido (mismo cliente), o None.

    Pensado para la vista de subida (H6): avisar antes de crear otro documento.
    """
    row = DocumentFile.objects.filter(client=client, sha256=sha256).select_related("document").first()
    return row.document if row else None


def find_duplicate_by_number(client, *, flow, issuer_tax_id, document_number, exclude_pk=None):
    """Otro documento vigente con el mismo emisor y número, o None.

    - flow `in`  (el cliente emite): el número es único en la serie propia del cliente.
    - flow `out`/`unknown`: emisor (NIF del tercero) + número.
    Se ignoran rectificaciones antiguas (`is_current=False`) y documentos rechazados.
    """
    number = (document_number or "").strip()
    if not number:
        return None
    qs = Document.all_objects.filter(
        client=client, is_current=True, document_number__iexact=number,
    ).exclude(status="rejected")
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if flow == "in":
        qs = qs.filter(flow="in")
    elif issuer_tax_id:
        qs = qs.filter(company__tax_id=issuer_tax_id).exclude(flow="in")
    else:
        return None  # sin NIF de emisor no hay forma fiable de comparar
    return qs.order_by("pk").first()
