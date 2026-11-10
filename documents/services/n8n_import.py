"""Importación de lo ya procesado por n8n (H10).

Formato de la carpeta de entrada: por cada documento, el archivo (`X.pdf`, `X.jpg`…) y
un `X.json` con los mismos campos que el endpoint de ingesta (provider_name,
provider_tax_id, document_type, base_amount, …). Si falta `external_id` se genera uno
estable a partir del contenido. Es idempotente: lo ya importado (mismo contenido o mismo
`external_id`) se cuenta como duplicado y no se vuelve a crear.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from api.serializers import DocumentIngestSerializer
from billing_ai.storage import sha256_of
from documents.services.ingest import DuplicateFileError, ingest_document

FILE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}


@dataclass
class ImportReport:
    imported: int = 0
    duplicates: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return json.dumps(exc.detail, ensure_ascii=False, default=str)[:300]
    return f"{type(exc).__name__}: {exc}"[:300]


def import_directory(client, directory, *, dry_run: bool = False) -> ImportReport:
    report = ImportReport()
    root = Path(directory)
    for meta_path in sorted(root.glob("*.json")):
        name = meta_path.stem
        file_path = next(
            (p for p in sorted(root.glob(f"{name}.*")) if p.suffix.lower() in FILE_SUFFIXES), None
        )
        if file_path is None:
            report.errors.append((meta_path.name, "no hay archivo asociado"))
            continue
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("el JSON debe ser un objeto")
            upload = SimpleUploadedFile(file_path.name, file_path.read_bytes())
            payload.setdefault("original_name", file_path.name)
            payload.setdefault("external_id", f"n8n-{sha256_of(upload)[:16]}")
            payload["file"] = upload
            serializer = DocumentIngestSerializer(data=payload, context={"client": client})
            serializer.is_valid(raise_exception=True)
            if dry_run:
                report.imported += 1
                continue
            ingest_document(client, serializer.validated_data, source="import", origin="import")
            report.imported += 1
        except DuplicateFileError:
            report.duplicates += 1
        except ValidationError as exc:
            # external_id repetido = ya importado en una pasada anterior
            if "external_id" in getattr(exc, "detail", {}) and "already ingested" in str(exc.detail["external_id"]):
                report.duplicates += 1
            else:
                report.errors.append((meta_path.name, _describe(exc)))
        except Exception as exc:  # noqa: BLE001  (un archivo malo no detiene la importación)
            report.errors.append((meta_path.name, _describe(exc)))
    return report
