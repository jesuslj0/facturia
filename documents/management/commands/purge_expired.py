"""Borra los documentos cuya retención ha caducado (simulacro salvo --apply)."""
from django.core.management.base import BaseCommand

from documents.services import retention


class Command(BaseCommand):
    help = "Elimina documentos y archivos tras DOCUMENT_RETENTION_YEARS. Sin --apply solo simula."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Borrar de verdad (irreversible)")
        parser.add_argument("--client", type=int)
        parser.add_argument("--years", type=int, help="Sobrescribe DOCUMENT_RETENTION_YEARS")

    def handle(self, *args, apply, client, years, **opts):
        from clients.models import Client

        c = Client.objects.get(pk=client) if client else None
        r = retention.purge_expired(apply=apply, client=c, years=years)
        years = years if years is not None else retention.retention_years()
        verb = "Purgados" if apply else "Se purgarían (simulacro)"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {r['documents']} documentos en {r['chains']} cadenas; "
            f"retención {years} años{'; archivos borrados: ' + str(r['files']) if apply else ''}"
        ))
