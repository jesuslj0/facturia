"""Informe de tokens y coste de la extracción."""
from datetime import date

from django.core.management.base import BaseCommand

from documents.services.usage import extraction_usage


class Command(BaseCommand):
    help = "Muestra tokens y coste (USD) de las extracciones, por modelo."

    def add_arguments(self, parser):
        parser.add_argument("--client", type=int)
        parser.add_argument("--from", dest="start", type=date.fromisoformat)
        parser.add_argument("--to", dest="end", type=date.fromisoformat)

    def handle(self, *args, client, start, end, **opts):
        from clients.models import Client

        c = Client.objects.get(pk=client) if client else None
        u = extraction_usage(c, start, end)
        w = self.stdout.write
        w(f"Intentos: {u['runs']} (fallidos {u['failed_runs']}, respaldo {u['fallback_runs']}) "
          f"en {u['documents']} documentos")
        w(f"Tokens: in={u['input_tokens']} out={u['output_tokens']} "
          f"cache_read={u['cache_read_tokens']} cache_write={u['cache_creation_tokens']}")
        w(f"Coste: {u['cost_usd']:.4f} USD ({u['cost_per_document']:.4f} USD/documento)")
        for m in u["by_model"]:
            w(f"  {m['model']}: {m['runs']} intentos, {m['cost_usd']:.4f} USD")
