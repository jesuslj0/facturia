"""Utilidades de almacenamiento de archivos privados (multi-tenant)."""
import hashlib
import os
import uuid

from django.db import models
from django.db.models.fields.files import FieldFile, ImageFieldFile
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


def _content_hash(instance, field_name: str) -> str | None:
    """SHA-256 del archivo que se está guardando, o None si no se puede saber.

    Dos casos (Django llama a `upload_to` sin pasar el contenido):
      1. `FieldFile.save(nombre, contenido)`: lo captura `HashedFieldFile.save`.
      2. Archivo asignado y aún no guardado (constructor, formularios, API):
         se lee del propio campo (`_committed` es False).
    Un archivo ya guardado NUNCA se usa: sería el contenido antiguo.
    """
    pending = getattr(instance, "_pending_upload_sha256", {})
    if field_name in pending:
        return pending[field_name]
    field_file = getattr(instance, field_name, None)
    if field_file is not None and getattr(field_file, "_committed", True) is False:
        try:
            return sha256_of(field_file.file)
        except Exception:
            return None
    return None


def _tenant_path(kind: str, instance, filename: str, field_name: str) -> str:
    """`<client_id>/<kind>/<AAAA>/<MM>/<sha256><ext>`.

    La clave se basa en el contenido (nunca en el nombre original). Si no se puede
    leer el contenido se usa un UUID.
    """
    ext = os.path.splitext(filename)[1].lower()[:10]
    now = timezone.now()
    client_id = getattr(instance, "client_id", None) or getattr(instance, "pk", None) or "unassigned"
    name = _content_hash(instance, field_name)
    return f"{client_id}/{kind}/{now:%Y}/{now:%m}/{name or uuid.uuid4().hex}{ext}"


class _HashingSaveMixin:
    def save(self, name, content, save=True):
        pending = self.instance.__dict__.setdefault("_pending_upload_sha256", {})
        pending[self.field.attname] = sha256_of(content)
        try:
            return super().save(name, content, save=save)
        finally:
            pending.pop(self.field.attname, None)


class HashedFieldFile(_HashingSaveMixin, FieldFile):
    pass


class HashedImageFieldFile(_HashingSaveMixin, ImageFieldFile):
    pass


class HashedFileField(models.FileField):
    attr_class = HashedFieldFile


class HashedImageField(models.ImageField):
    attr_class = HashedImageFieldFile


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
