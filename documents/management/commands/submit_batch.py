"""Envía documentos pendientes a la Batch API (extracción diferida, ~50 % más barata)."""
from django.core.management.base import BaseCommand

from documents.services.extraction.batch import eligible_documents, submit_batches


class Command(BaseCommand):
    help = "Envía documentos uploaded/failed a la Batch API. Recoger después con collect_batch."

    def add_arguments(self, parser):
        parser.add_argument("--client", type=int)
        parser.add_argument("--limit", type=int, help="Máximo de documentos a enviar")
        parser.add_argument("--dry-run", action="store_true", help="Solo cuenta, no envía")

    def handle(self, *args, client, limit, dry_run, **opts):
        from clients.models import Client

        c = Client.objects.get(pk=client) if client else None
        if dry_run:
            n = len(list(eligible_documents(client=c, limit=limit)))
            self.stdout.write(f"Se enviarían {n} documentos (simulacro)")
            return
        r = submit_batches(client=c, limit=limit)
        self.stdout.write(self.style.SUCCESS(
            f"Lotes: {r.batches}; documentos enviados: {r.submitted}; omitidos: {r.skipped}; con error: {r.failed}"
        ))
