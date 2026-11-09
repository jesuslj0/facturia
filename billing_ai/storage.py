"""Utilidades de almacenamiento de archivos privados (multi-tenant)."""
import hashlib
import os
import uuid

from django.http import FileResponse, Http404
from django.utils import timezone


def sha256_of(uploaded) -> str | None:
    """SHA-256 hex del contenido de un archivo subido; deja el puntero al inicio."""
    try:
        uploaded.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: uploaded.read(1024 * 1024), b""):
            digest.update(chunk)
        uploaded.seek(0)
        return digest.hexdigest()
    except Exception:
        return None


def _tenant_path(kind: str, instance, filename: str, field_name: str) -> str:
    """`<client_id>/<kind>/<AAAA>/<MM>/<sha256><ext>`.

    La clave se basa en el contenido (nunca en el nombre original). Si no se puede
    leer el contenido se usa un UUID.
    """
    ext = os.path.splitext(filename)[1].lower()[:10]
    now = timezone.now()
    client_id = getattr(instance, "client_id", None) or getattr(instance, "pk", None) or "unassigned"
    field_file = getattr(instance, field_name, None)
    name = sha256_of(field_file.file) if field_file is not None and hasattr(field_file, "file") else None
    return f"{client_id}/{kind}/{now:%Y}/{now:%m}/{name or uuid.uuid4().hex}{ext}"


def document_upload_to(instance, filename):
    return _tenant_path("documents", instance, filename, "file")


def receipt_upload_to(instance, filename):
    return _tenant_path("receipts", instance, filename, "receipt")


def logo_upload_to(instance, filename):
    # Client no tiene client_id: su propia pk es el tenant.
    return _tenant_path("logos", instance, filename, "logo")


def private_file_response(field_file, *, download_name=None):
    """Entrega un FieldFile desde el almacenamiento (misma origin, sin URL pública)."""
    import mimetypes

    if not field_file:
        raise Http404("Archivo no encontrado")
    try:
        handle = field_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Archivo no encontrado")
    name = download_name or os.path.basename(field_file.name)
    content_type = mimetypes.guess_type(field_file.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{name}"'.replace("\r", "").replace("\n", "")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
