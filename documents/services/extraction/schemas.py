"""Esquema de salida de la extracción (lo que Claude devuelve).

Se mantiene deliberadamente simple (importes como texto, sin restricciones
numéricas) para que sea compatible con la salida estructurada de la API. La
conversión a `Decimal`/fechas y la validación real se hacen en `normalize.py`.
"""
from typing import Literal

from pydantic import BaseModel

DocumentKind = Literal["invoice", "receipt", "quote", "delivery_note", "credit_note", "other"]


class Party(BaseModel):
    name: str | None
    tax_id: str | None
    address: str | None


class TaxLine(BaseModel):
    kind: Literal["vat", "surcharge", "withholding"]
    rate: str
    base: str | None
    amount: str


class Line(BaseModel):
    description: str | None
    quantity: str | None
    unit_price: str | None
    tax_rate: str | None
    amount: str | None


class Confidence(BaseModel):
    """Confianza de 0 a 1 (honesta: baja si el texto es ilegible o hay que inferir)."""
    overall: float
    issuer: float
    document_number: float
    date: float
    amounts: float
    total: float


class ExtractionResult(BaseModel):
    document_type: DocumentKind
    issuer: Party
    recipient: Party
    document_number: str | None
    issue_date: str | None
    currency: str | None
    base_amount: str | None
    tax_lines: list[TaxLine]
    total_amount: str | None
    iban: str | None
    lines: list[Line]
    confidence: Confidence
    notes: str | None
