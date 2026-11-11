"""Estimación de coste por extracción (USD).

Precios por millón de tokens, en `PRICES`. Son una estimación: se pueden
sobrescribir con `settings.EXTRACTION_PRICING` ({modelo: {...}}). Última revisión
de la tabla: 2026-10 (comprobar contra la tarifa vigente antes de facturar).
"""
from decimal import Decimal

from django.conf import settings

from .base import Usage

MILLION = Decimal(1_000_000)

PRICES = {
    # in/out en USD por MTok. `long_*`: tarifa para prompts > `long_threshold` tokens.
    "claude-haiku-5-5": {
        "in": Decimal("0.10"), "out": Decimal("0.50"),
        "long_threshold": 100_000, "long_in": Decimal("0.50"), "long_out": Decimal("2.50"),
    },
    "claude-sonnet-5-5": {"in": Decimal("2.00"), "out": Decimal("10.00")},
    "claude-opus-5-5": {"in": Decimal("4.00"), "out": Decimal("20.00")},
}
CACHE_READ_FACTOR = Decimal("0.1")    # lectura de caché ≈ 0,1 × entrada
CACHE_WRITE_FACTOR = Decimal("1.25")  # escritura de caché (TTL 5 min) ≈ 1,25 × entrada


BATCH_DISCOUNT = Decimal("0.5")       # la Batch API cuesta el 50 % del precio estándar


def estimate_cost(model: str, usage: Usage, *, batch: bool = False) -> Decimal | None:
    """Coste estimado en USD, o None si no se conoce el precio del modelo."""
    table = {**PRICES, **getattr(settings, "EXTRACTION_PRICING", {})}
    p = table.get(model)
    if not p:
        return None
    prompt_tokens = usage.input_tokens + usage.cache_read_tokens + usage.cache_creation_tokens
    price_in, price_out = p["in"], p["out"]
    if p.get("long_threshold") and prompt_tokens > p["long_threshold"]:
        price_in, price_out = p["long_in"], p["long_out"]
    cost = (
        Decimal(usage.input_tokens) * price_in
        + Decimal(usage.output_tokens) * price_out
        + Decimal(usage.cache_read_tokens) * price_in * CACHE_READ_FACTOR
        + Decimal(usage.cache_creation_tokens) * price_in * CACHE_WRITE_FACTOR
    ) / MILLION
    if batch:
        cost *= BATCH_DISCOUNT
    return cost.quantize(Decimal("0.000001"))
