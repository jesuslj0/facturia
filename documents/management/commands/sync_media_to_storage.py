"""Copia los archivos de MEDIA_ROOT al almacenamiento por defecto (p. ej. R2).

Las claves se conservan, por lo que no hay que tocar la base de datos.
Idempotente: omite lo que ya existe. Usa --dry-run para ver qué se copiaría.
"""
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sube a default_storage los archivos existentes en MEDIA_ROOT."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **options):
        root = Path(settings.MEDIA_ROOT)
        if not root.is_dir():
            self.stdout.write("MEDIA_ROOT no existe; nada que copiar.")
            return
        copied = skipped = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            key = path.relative_to(root).as_posix()
            try:
                exists = default_storage.exists(key)
            except Exception as exc:  # p. ej. botocore ClientError 403 (credenciales/permisos)
                code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
                raise CommandError(
                    f"No se pudo consultar el almacenamiento ({code}). "
                    "Revisa R2_ENDPOINT_URL, R2_BUCKET_NAME y los permisos del token."
                ) from None
            if exists:
                skipped += 1
                continue
            self.stdout.write(f"{'[dry-run] ' if dry_run else ''}{key}")
            if not dry_run:
                with path.open("rb") as fh:
                    # save() puede renombrar si existe; aquí sabemos que no existe.
                    saved = default_storage.save(key, File(fh))
                if saved != key:
                    self.stderr.write(f"Clave distinta a la original: {key} -> {saved}")
            copied += 1
        self.stdout.write(self.style.SUCCESS(f"Copiados: {copied}, ya existentes: {skipped}"))
