"""Cálculo determinista de IVA, recargo y retenciones (sin acceso a BD).

Convención: todos los importes son `Decimal` con 2 decimales (redondeo
half-up, como en facturación). La retención (IRPF) se resta del total.

    total = base + IVA + recargo − retención
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENT = Decimal("0.01")
DEFAULT_TOLERANCE = Decimal("0.02")  # céntimos de diferencia admitidos por redondeos


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(value) -> Decimal:
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def percentage_of(base, rate) -> Decimal:
    """`rate`% de `base`, redondeado a céntimos."""
    return quantize(to_decimal(base) * to_decimal(rate) / Decimal("100"))


def expected_total(base, vat=0, surcharge=0, withholding=0) -> Decimal:
    return quantize(to_decimal(base) + to_decimal(vat) + to_decimal(surcharge) - to_decimal(withholding))


def totals_match(declared, expected, tolerance=DEFAULT_TOLERANCE) -> bool:
    """¿Coincide el total declarado con el esperado dentro de la tolerancia?"""
    return abs(to_decimal(declared) - to_decimal(expected)) <= to_decimal(tolerance)


def summarize(tax_lines: Iterable) -> dict:
    """Suma importes por tipo. Acepta objetos con `.kind` y `.amount` (p. ej. TaxBreakdown)."""
    out = {"vat": Decimal("0.00"), "surcharge": Decimal("0.00"), "withholding": Decimal("0.00")}
    for line in tax_lines:
        out[line.kind] = out[line.kind] + to_decimal(line.amount)
    return {k: quantize(v) for k, v in out.items()}


def expected_total_from_lines(base, tax_lines: Iterable) -> Decimal:
    s = summarize(tax_lines)
    return expected_total(base, s["vat"], s["surcharge"], s["withholding"])
