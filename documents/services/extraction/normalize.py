"""Convierte la salida del modelo (texto) en valores tipados y deterministas.

No valida cuadres ni plausibilidad (eso es H5); solo parsea y calcula el flujo
(`in`/`out`) comparando NIF, sin fiarse del modelo para ese dato.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from documents.validators import clean_tax_id

from .schemas import ExtractionResult

# Tipo de la extracción -> Document.document_type (None = sin equivalente)
DOCUMENT_TYPE_MAP = {
    "invoice": "invoice",
    "credit_note": "corrected_invoice",
    "delivery_note": "delivery",
    "receipt": "receipt",
    "quote": "quote",
    "other": None,
}


def normalize_tax_id(value: str | None) -> str | None:
    # Forma canónica única (documents.validators.clean_tax_id): sin separadores ni prefijo "ES".
    return clean_tax_id(value) or None


def parse_amount(value: str | None) -> Decimal | None:
    """'1.234,56' | '1,234.56' | '€ 12,5' | '(12.00)' -> Decimal; None si no es un importe."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^\d.,]", "", s)
    if not s or not re.search(r"\d", s):
        return None
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    if last_dot != -1 and last_comma != -1:
        # El último separador es el decimal.
        dec, thou = ("." , ",") if last_dot > last_comma else (",", ".")
        s = s.replace(thou, "").replace(dec, ".")
    elif last_comma != -1:
        s = _single_separator(s, ",")
    elif last_dot != -1:
        s = _single_separator(s, ".")
    try:
        amount = Decimal(s)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def _single_separator(s: str, sep: str) -> str:
    """Un solo tipo de separador: decimal si hay uno y le siguen 1-2 dígitos; si no, miles."""
    parts = s.split(sep)
    if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
        return parts[0] + "." + parts[1]
    if len(parts) == 2 and len(parts[1]) != 3:
        return parts[0] + "." + parts[1]
    return "".join(parts)  # 1.234 | 1.234.567 -> miles


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", value)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def clamp01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


@dataclass
class NormalizedTaxLine:
    kind: str
    rate: Decimal | None
    base: Decimal | None
    amount: Decimal | None


@dataclass
class NormalizedLine:
    position: int
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    tax_rate: Decimal | None
    amount: Decimal | None
    page: int | None = None


@dataclass
class NormalizedExtraction:
    kind: str                       # tipo según el modelo (invoice, receipt, ...)
    document_type: str | None       # Document.document_type, o None si no aplica
    flow: str                       # in | out | unknown
    issuer_name: str | None
    issuer_tax_id: str | None
    recipient_name: str | None
    recipient_tax_id: str | None
    counterparty_name: str | None   # el tercero (cliente si flow=in, proveedor si flow=out)
    counterparty_tax_id: str | None
    document_number: str | None
    issue_date: date | None
    currency: str
    base_amount: Decimal | None
    total_amount: Decimal | None
    tax_lines: list[NormalizedTaxLine] = field(default_factory=list)
    lines: list[NormalizedLine] = field(default_factory=list)
    iban: str = ""
    confidence: dict = field(default_factory=dict)
    confidence_global: float = 0.0
    notes: str = ""

    def legacy_confidence(self) -> dict:
        """Formato que ya usa la ingesta actual (`get_review_level`)."""
        return {
            "confianza_extraccion": self.confidence.get("overall", 0.0),
            "fecha": self.confidence.get("date", 0.0),
            "total": self.confidence.get("total", 0.0),
        }


def compute_flow(issuer_tax_id, recipient_tax_id, client_tax_id) -> str:
    me = normalize_tax_id(client_tax_id)
    if not me:
        return "unknown"
    if normalize_tax_id(issuer_tax_id) == me:
        return "in"      # el cliente emite → ingreso (venta)
    if normalize_tax_id(recipient_tax_id) == me:
        return "out"     # el cliente recibe → gasto (compra)
    return "unknown"


def normalize(result: ExtractionResult, *, client_tax_id: str | None = None) -> NormalizedExtraction:
    issuer_tax = normalize_tax_id(result.issuer.tax_id)
    recipient_tax = normalize_tax_id(result.recipient.tax_id)
    flow = compute_flow(issuer_tax, recipient_tax, client_tax_id)
    if flow == "in":
        cp_name, cp_tax = result.recipient.name, recipient_tax
    else:  # out o unknown: por defecto el tercero es el emisor
        cp_name, cp_tax = result.issuer.name, issuer_tax

    currency = (result.currency or "EUR").strip().upper()[:3] or "EUR"
    conf = {k: clamp01(v) for k, v in result.confidence.model_dump().items()}
    return NormalizedExtraction(
        kind=result.document_type,
        document_type=DOCUMENT_TYPE_MAP.get(result.document_type),
        flow=flow,
        issuer_name=(result.issuer.name or "").strip() or None,
        issuer_tax_id=issuer_tax,
        recipient_name=(result.recipient.name or "").strip() or None,
        recipient_tax_id=recipient_tax,
        counterparty_name=(cp_name or "").strip() or None,
        counterparty_tax_id=cp_tax,
        document_number=(result.document_number or "").strip() or None,
        issue_date=parse_date(result.issue_date),
        currency=currency,
        base_amount=parse_amount(result.base_amount),
        total_amount=parse_amount(result.total_amount),
        tax_lines=[
            NormalizedTaxLine(t.kind, parse_amount(t.rate), parse_amount(t.base), parse_amount(t.amount))
            for t in result.tax_lines
        ],
        lines=[
            NormalizedLine(i, (l.description or "").strip()[:500], parse_amount(l.quantity),
                           parse_amount(l.unit_price), parse_amount(l.tax_rate), parse_amount(l.amount),
                           l.page if isinstance(l.page, int) and 1 <= l.page <= 9999 else None)
            for i, l in enumerate(result.lines, start=1)
        ],
        iban=re.sub(r"\s", "", result.iban or "").upper()[:34],
        confidence=conf,
        confidence_global=conf.get("overall", 0.0),
        notes=(result.notes or "").strip(),
    )
