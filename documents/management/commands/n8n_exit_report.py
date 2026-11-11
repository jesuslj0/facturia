"""Informe del criterio de apagado de n8n."""
from django.core.management.base import BaseCommand

from documents.services.n8n_exit import (
    MIN_APP_SHARE, MIN_FIELD_ACCURACY, WINDOW_DAYS, build_report,
)


def _pct(v):
    return "sin datos" if v is None else f"{v * 100:.1f} %"


class Command(BaseCommand):
    help = "Evalúa si se puede apagar n8n (volumen en la app, exactitud tras revisión, incidencias)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=WINDOW_DAYS)
        parser.add_argument("--client", type=int)

    def handle(self, *args, days, client, **opts):
        from clients.models import Client

        c = Client.objects.get(pk=client) if client else None
        r = build_report(days=days, client=c)
        mark = lambda ok: "OK " if ok else "NO "  # noqa: E731
        w = self.stdout.write
        w(f"Ventana: {r.days} días (la app lleva {r.days_in_use} días en uso)")
        w(f"{mark(r.checks['app_share'])} Volumen en la app: {_pct(r.app_share)} "
          f"({r.app_documents} app / {r.n8n_documents} n8n; objetivo > {MIN_APP_SHARE:.0%})")
        w(f"{mark(r.checks['field_accuracy'])} Campos correctos: {_pct(r.field_accuracy)} "
          f"({r.fields_correct}/{r.fields_compared} en {r.reviewed_documents} documentos revisados; objetivo ≥ {MIN_FIELD_ACCURACY:.0%})")
        if r.errors_by_field:
            w("     Errores por campo: " + ", ".join(f"{k}={v}" for k, v in sorted(r.errors_by_field.items(), key=lambda x: -x[1])))
        w(f"{mark(r.checks['no_critical_incidents'])} Incidencias críticas de extracción: {r.critical_incidents}")
        w(f"{mark(r.checks['enough_history'])} Historial suficiente")
        if r.ready:
            self.stdout.write(self.style.SUCCESS("LISTO para apagar n8n (N8N_INGEST_ENABLED=False)."))
        else:
            self.stdout.write(self.style.WARNING("Aún NO se cumple el criterio de apagado."))
