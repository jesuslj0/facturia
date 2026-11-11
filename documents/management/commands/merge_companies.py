"""Fusiona terceros duplicados (mismo NIF con otro formato o mismo nombre con distinta grafía).

Por defecto solo simula. Con --apply reasigna los documentos (y cualquier otra relación) al tercero
que se conserva y borra los duplicados.

    python manage.py merge_companies                 # simula
    python manage.py merge_companies --client 1 --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from documents.company_names import name_key
from documents.models import Company
from documents.validators import clean_tax_id


def _groups(companies):
    """Agrupa terceros de un mismo cliente que son el mismo. Un grupo nunca mezcla dos NIF distintos."""
    groups: list[dict] = []
    for c in sorted(companies, key=lambda c: c.pk):
        tax, key = clean_tax_id(c.tax_id) or None, name_key(c.name)
        target = None
        for g in groups:
            same_tax = tax and g["tax"] == tax
            same_name = key and key == g["key"] and (not tax or not g["tax"] or tax == g["tax"])
            if same_tax or same_name:
                target = g
                break
        if target is None:
            groups.append({"tax": tax, "key": key, "members": [c]})
        else:
            target["members"].append(c)
            target["tax"] = target["tax"] or tax
    return [g for g in groups if len(g["members"]) > 1]


def _survivor(members):
    # Preferimos el que ya tiene NIF; a igualdad, el más antiguo.
    return sorted(members, key=lambda c: (not c.tax_id, c.pk))[0]


class Command(BaseCommand):
    help = "Detecta y fusiona terceros duplicados (simula salvo --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--client", type=int, help="Solo este cliente")
        parser.add_argument("--apply", action="store_true", help="Aplicar la fusión (por defecto solo simula)")

    def handle(self, *args, client, apply, **opts):
        qs = Company.objects.all()
        if client:
            qs = qs.filter(client_id=client)
        by_client: dict[int, list] = {}
        for c in qs:
            by_client.setdefault(c.client_id, []).append(c)

        merged = 0
        for client_id, companies in sorted(by_client.items()):
            for g in _groups(companies):
                keep = _survivor(g["members"])
                dups = [m for m in g["members"] if m.pk != keep.pk]
                self.stdout.write(f"[cliente {client_id}] conservar #{keep.pk} «{keep.name}» ({keep.tax_id or 'sin NIF'})")
                for d in dups:
                    docs = d.documents.count() if hasattr(d, "documents") else "?"
                    self.stdout.write(f"    fusionar #{d.pk} «{d.name}» ({d.tax_id or 'sin NIF'}) · {docs} doc.")
                if apply:
                    self._merge(keep, dups, g["tax"])
                merged += len(dups)

        verb = "Fusionados" if apply else "Se fusionarían"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {merged} terceros duplicados."))
        if merged and not apply:
            self.stdout.write("Vuelve a ejecutar con --apply para aplicar los cambios.")

    @transaction.atomic
    def _merge(self, keep, dups, tax):
        for d in dups:
            # Reasigna cualquier relación que apunte al duplicado (documentos, movimientos...).
            for rel in Company._meta.related_objects:
                if rel.one_to_many or rel.one_to_one:
                    rel.related_model._base_manager.filter(**{rel.field.name: d}).update(**{rel.field.name: keep})
            keep.is_provider = keep.is_provider or d.is_provider
            keep.is_customer = keep.is_customer or d.is_customer
            for f in ("address", "postal_code", "city"):
                if not getattr(keep, f) and getattr(d, f):
                    setattr(keep, f, getattr(d, f))
            d.delete()
        keep.tax_id = tax or keep.tax_id    # tras borrar los duplicados: sin choque de unicidad
        keep.save()
