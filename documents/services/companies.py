"""Alta/búsqueda de terceros (proveedores y clientes) sin duplicados.

Un tercero es el mismo si coincide el NIF en su forma canónica (sin espacios, guiones, barras ni
prefijo "ES") o, a falta de NIF que lo contradiga, si coincide la clave del nombre (sin
mayúsculas, tildes, puntuación ni forma jurídica).
"""
from django.db import IntegrityError, transaction

from documents.company_names import display_name, name_key
from documents.models import Company
from documents.validators import clean_tax_id


def normalize_tax_id(tax_id):
    return clean_tax_id(tax_id) or None


def normalize_name(name: str | None) -> str:
    return display_name(name)


def find_company(client, *, name: str, tax_id: str | None, lock: bool = False):
    """Busca un tercero ya existente: por NIF y, si no, por nombre sin NIF contradictorio."""
    tax_id = normalize_tax_id(tax_id)
    qs = Company.objects.select_for_update() if lock else Company.objects

    if tax_id:
        company = qs.filter(client=client, tax_id=tax_id).first()
        if company:
            return company

    key = name_key(name)
    if key:
        # Mismo nombre y sin NIF distinto: con NIF distinto es otra empresa que se llama igual.
        candidates = qs.filter(client=client, name_key=key).order_by("pk")
        for candidate in candidates:
            if not candidate.tax_id or not tax_id or candidate.tax_id == tax_id:
                return candidate
    return None


@transaction.atomic
def get_or_create_company(*, client, name: str, tax_id: str | None, is_provider: bool = False, is_customer: bool = False):
    tax_id = normalize_tax_id(tax_id)
    name = display_name(name)

    company = find_company(client, name=name, tax_id=tax_id, lock=True)

    if company:
        changed = []
        if is_provider and not company.is_provider:
            company.is_provider = True
            changed.append("is_provider")
        if is_customer and not company.is_customer:
            company.is_customer = True
            changed.append("is_customer")
        if tax_id and not company.tax_id:      # lo encontramos por nombre y ahora sabemos su NIF
            company.tax_id = tax_id
            changed.append("tax_id")
        if changed:
            company.save(update_fields=changed)
        return company

    try:
        with transaction.atomic():
            return Company.objects.create(
                client=client, name=name, tax_id=tax_id,
                is_provider=is_provider, is_customer=is_customer,
            )
    except IntegrityError:
        # Otro proceso la creó justo antes
        return find_company(client, name=name, tax_id=tax_id)
