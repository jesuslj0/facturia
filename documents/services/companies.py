"""Alta/búsqueda de terceros (proveedores y clientes) sin duplicados por NIF."""
from django.db import IntegrityError, transaction

from documents.models import Company


def normalize_tax_id(tax_id):
    if not tax_id:
        return None
    return tax_id.replace(" ", "").replace("-", "").upper()

def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return name.strip()

@transaction.atomic
def get_or_create_company(*, client, name: str, tax_id: str | None, is_provider: bool = False, is_customer: bool = False):
    tax_id = normalize_tax_id(tax_id)
    name = normalize_name(name)
    company = None

    # 1️⃣ Buscar por CIF
    if tax_id:
        company = (
            Company.objects
            .select_for_update()
            .filter(client=client, tax_id=tax_id)
            .first()
        )

    # 2️⃣ Buscar por nombre
    if not company and name:
        company = (
            Company.objects
            .select_for_update()
            .filter(client=client, name__iexact=name)
            .first()
        )

    if company:
        # 🔥 Actualizar roles si hace falta
        updated = False

        if is_provider and not company.is_provider:
            company.is_provider = True
            updated = True

        if is_customer and not company.is_customer:
            company.is_customer = True
            updated = True

        if updated:
            company.save(update_fields=["is_provider", "is_customer"])

        return company

    # 3️⃣ Crear con protección contra race condition
    try:
        company = Company.objects.create(
            client=client,
            name=name,
            tax_id=tax_id,
            is_provider=is_provider,
            is_customer=is_customer
        )
    except IntegrityError:
        # Otro proceso la creó justo antes
        if tax_id:
            company = Company.objects.filter(client=client, tax_id=tax_id).first()
        if not company and name:
            company = Company.objects.filter(client=client, name__iexact=name).first()

    return company
