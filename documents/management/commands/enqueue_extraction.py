"""Encola (o ejecuta en el momento con --sync) el procesado de documentos pendientes."""
from django.core.management.base import BaseCommand

from documents.models import Document
from documents.services.processing import enqueue_processing, run_processing


class Command(BaseCommand):
    help = "Encola la extracción de documentos en estado uploaded/failed."

    def add_arguments(self, parser):
        parser.add_argument("--status", default="uploaded,failed")
        parser.add_argument("--client", type=int)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--sync", action="store_true", help="Ejecutar aquí, sin cola (depuración)")

    def handle(self, *args, status, client, limit, sync, **opts):
        qs = Document.all_objects.filter(
            processing_status__in=status.split(","), status="pending", is_archived=False
        ).order_by("pk")
        if client:
            qs = qs.filter(client_id=client)
        n = 0
        for doc in qs[:limit]:
            if sync:
                self.stdout.write(f"{doc.pk}: {run_processing(doc.pk)}")
                n += 1
            elif enqueue_processing(doc):
                n += 1
        self.stdout.write(self.style.SUCCESS(f"{'Procesados' if sync else 'Encolados'}: {n}"))
