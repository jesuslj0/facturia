"""Importa documentos ya procesados por n8n desde una carpeta (archivo + JSON)."""
from django.core.management.base import BaseCommand, CommandError

from documents.services.n8n_import import import_directory


class Command(BaseCommand):
    help = "Importa X.pdf + X.json (campos del contrato de ingesta) con source=import. Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("directory")
        parser.add_argument("--client", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true", help="Valida sin crear nada")

    def handle(self, *args, directory, client, dry_run, **opts):
        from pathlib import Path

        from clients.models import Client

        if not Path(directory).is_dir():
            raise CommandError(f"No existe la carpeta: {directory}")
        try:
            c = Client.objects.get(pk=client)
        except Client.DoesNotExist:
            raise CommandError(f"No existe el cliente {client}") from None
        r = import_directory(c, directory, dry_run=dry_run)
        verb = "Se importarían" if dry_run else "Importados"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {r.imported}; duplicados: {r.duplicates}; con error: {len(r.errors)}"))
        for name, msg in r.errors:
            self.stderr.write(f"  {name}: {msg}")
