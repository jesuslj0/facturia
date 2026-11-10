"""Recoge los lotes terminados de la Batch API y aplica los resultados."""
from django.core.management.base import BaseCommand

from documents.services.extraction.batch import collect_batches


class Command(BaseCommand):
    help = "Recoge lotes terminados (idempotente; se puede lanzar periódicamente, p. ej. cada 10 min)."

    def handle(self, *args, **opts):
        r = collect_batches()
        self.stdout.write(self.style.SUCCESS(
            f"Lotes recogidos: {r.collected_batches}; pendientes: {r.pending_batches}; "
            f"aplicados: {r.applied}; reencolados por el flujo normal: {r.requeued}"
        ))
