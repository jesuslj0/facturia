"""Signo contable de los documentos (única fuente de verdad para métricas y exports).

Convención: las cifras de una rectificativa (`corrected_invoice`) **restan** siempre,
con independencia de cómo vengan guardadas (n8n las guardaba en positivo; la
extracción con IA, en negativo). En ingresos reducen lo facturado; en gastos
reducen lo gastado. Se usa la magnitud (`abs`) y el signo lo decide el tipo.
"""
from decimal import Decimal

from django.db.models import Case, DecimalField, F, When
from django.db.models.functions import Abs

CORRECTED = "corrected_invoice"


def document_sign(document_type) -> int:
    return -1 if document_type == CORRECTED else 1


def signed_value(document_type, value):
    """Valor con el signo contable aplicado (None se respeta)."""
    if value is None:
        return None
    return document_sign(document_type) * abs(Decimal(value))


def signed_amount(field, type_field="document_type"):
    """Expresión ORM: `field` con signo contable (rectificativas restan).

    `type_field` es la ruta al tipo de documento (p. ej. `document__document_type`
    cuando `field` pertenece a un modelo relacionado como `TaxBreakdown`).
    """
    return Case(
        When(**{type_field: CORRECTED}, then=-Abs(F(field))),
        default=F(field),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
