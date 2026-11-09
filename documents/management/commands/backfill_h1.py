"""Rellena los datos de H1 para documentos existentes. Idempotente y por lotes.

- DocumentFile (hash, mime, tamaño) para documentos originales con archivo legible.
  Duplicados por (client, sha256) y archivos ausentes se informan y se omiten.
- TaxBreakdown de IVA a partir de base/tax_percentage/tax_amount.
- DocumentAuditLog inicial ("created" + aprobado/rechazado/archivado según campos *_at).

No modifica ni borra datos existentes. Usa --dry-run para ver qué haría.
"""
import mimetypes

from django.core.management.base import BaseCommand
from django.db import transaction

from billing_ai.storage import sha256_of
from documents.models import Document, DocumentAuditLog, DocumentFile, TaxBreakdown


class Command(BaseCommand):
    help = "Backfill de DocumentFile, TaxBreakdown y DocumentAuditLog."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, dry_run=False, batch_size=200, **options):
        stats = {"files": 0, "dup": 0, "missing": 0, "tax": 0, "audit": 0}
        qs = Document.all_objects.order_by("pk")
        for doc in qs.iterator(chunk_size=batch_size):
            with transaction.atomic():
                self._file(doc, stats, dry_run)
                self._tax(doc, stats, dry_run)
                self._audit(doc, stats, dry_run)
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}DocumentFile: {stats['files']} (duplicados omitidos: {stats['dup']}, "
            f"archivos ausentes: {stats['missing']}); TaxBreakdown: {stats['tax']}; "
            f"AuditLog: {stats['audit']}"
        ))

    def _file(self, doc, stats, dry_run):
        # Las rectificaciones reutilizan el archivo del original.
        if doc.parent_document_id is not None or not doc.file:
            return
        if DocumentFile.objects.filter(document=doc).exists():
            return
        try:
            with doc.file.open("rb") as fh:
                digest = sha256_of(fh)
                size = doc.file.size
        except Exception:
            stats["missing"] += 1
            self.stderr.write(f"Archivo ausente/ilegible: documento {doc.pk} ({doc.file.name})")
            return
        if DocumentFile.objects.filter(client_id=doc.client_id, sha256=digest).exists():
            stats["dup"] += 1
            self.stderr.write(f"Contenido duplicado: documento {doc.pk} (sha256 {digest[:12]})")
            return
        stats["files"] += 1
        if dry_run:
            return
        DocumentFile.objects.create(
            document=doc, client_id=doc.client_id, sha256=digest, size_bytes=size,
            mime_type=mimetypes.guess_type(doc.file.name)[0] or "",
            origin="n8n" if doc.source == "n8n" else "upload",
        )

    def _tax(self, doc, stats, dry_run):
        if doc.base_amount is None or doc.tax_percentage is None or doc.tax_amount is None:
            return
        if TaxBreakdown.objects.filter(document=doc).exists():
            return
        stats["tax"] += 1
        if dry_run:
            return
        TaxBreakdown.objects.create(
            document=doc, kind=TaxBreakdown.VAT, rate=doc.tax_percentage,
            base=doc.base_amount, amount=doc.tax_amount,
        )

    def _audit(self, doc, stats, dry_run):
        if DocumentAuditLog.objects.filter(document=doc).exists():
            return
        events = [("created", doc.created_at, None)]
        if doc.approved_at:
            events.append(("approved", doc.approved_at, doc.approved_by_id))
        if doc.rejected_at:
            events.append(("rejected", doc.rejected_at, doc.rejected_by_id))
        if doc.archived_at:
            events.append(("archived", doc.archived_at, doc.archived_by_id))
        if doc.rectified_at:
            events.append(("rectified", doc.rectified_at, doc.rectified_by_id))
        stats["audit"] += len(events)
        if dry_run:
            return
        for action, when, user_id in events:
            log = DocumentAuditLog(document=doc, user_id=user_id, action=action,
                                   changes={"backfill": True})
            log.save()
            # created_at es auto_now_add: se ajusta a la fecha real del evento.
            DocumentAuditLog.objects.filter(pk=log.pk).update(created_at=when)
