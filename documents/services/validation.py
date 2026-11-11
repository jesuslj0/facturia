"""Validación determinista del resultado de una extracción.

Separa tres cosas:
  - `validate()`: lista de incidencias (puro salvo la búsqueda de duplicados).
  - `decide()`: política de revisión/auto-aprobación a partir de las incidencias.
  - `fallback_problems()`: incidencias que justifican reintentar con el modelo de respaldo.

Gravedad:
  ERROR   → el documento NO se aprueba solo; revisión obligatoria.
  WARNING → sospechoso; revisión recomendada, nunca auto-aprobado.
  INFO    → solo informativo.
`model_fixable`: otro modelo podría leerlo mejor (p. ej. un dígito mal leído). Solo
esas incidencias disparan el respaldo (Sonnet); un duplicado o un cliente sin NIF no.
"""
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from documents.services import taxes
from documents.services.duplicates import find_duplicate_by_number
from documents.services.review import get_review_level
from documents.validators import check_tax_id

ERROR, WARNING, INFO = "error", "warning", "info"

TOTAL_TOLERANCE = Decimal("0.02")
LINE_TOLERANCE = Decimal("0.05")
MIN_PLAUSIBLE_DATE = date(2000, 1, 1)
OLD_AFTER_DAYS = 5 * 366

VAT_RATES = {Decimal(x) for x in ("0", "2", "3", "4", "5", "7", "7.5", "9.5", "10", "15", "20", "21")}
WITHHOLDING_RATES = {Decimal(x) for x in ("1", "2", "7", "15", "19", "21", "24", "35")}
SURCHARGE_RATES = {Decimal(x) for x in ("0.5", "0.62", "1.4", "1.75", "5.2")}
INVOICE_LIKE = {"invoice", "corrected_invoice"}


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    field: str = ""
    model_fixable: bool = False


def issues_to_json(issues) -> list[dict]:
    return [asdict(i) for i in issues]


def validate(n, *, client, document=None, today: date | None = None) -> list[Issue]:
    """`n` es un NormalizedExtraction. `document` (opcional) se excluye de la búsqueda de duplicados."""
    today = today or timezone.localdate()
    out: list[Issue] = []
    kind = n.document_type or n.kind
    invoice_like = (n.document_type in INVOICE_LIKE)

    if n.document_type is None:
        out.append(Issue("unsupported_type", ERROR, "Tipo de documento no reconocido o no soportado.", "document_type"))

    # --- importes -----------------------------------------------------------
    if n.total_amount is None:
        sev = WARNING if kind == "delivery" else ERROR
        out.append(Issue("missing_total", sev, "No se ha podido leer el importe total.", "total_amount", True))
    if n.currency != "EUR":
        out.append(Issue("non_eur_currency", WARNING, f"Moneda {n.currency}: la aplicación trabaja en euros.", "currency"))
    _check_amounts(n, out, invoice_like)
    _check_rates(n, out)

    # --- fecha --------------------------------------------------------------
    if n.issue_date is None:
        out.append(Issue("missing_date", ERROR, "No se ha podido leer la fecha de emisión.", "issue_date", True))
    elif n.issue_date > today + timedelta(days=1):
        out.append(Issue("future_date", ERROR, f"La fecha de emisión ({n.issue_date}) es futura.", "issue_date", True))
    elif n.issue_date < MIN_PLAUSIBLE_DATE:
        out.append(Issue("implausible_date", ERROR, f"La fecha de emisión ({n.issue_date}) no es plausible.", "issue_date", True))
    elif (today - n.issue_date).days > OLD_AFTER_DAYS:
        out.append(Issue("old_date", WARNING, f"La fecha de emisión ({n.issue_date}) tiene más de 5 años.", "issue_date"))

    # --- número -------------------------------------------------------------
    if not n.document_number and kind in INVOICE_LIKE:
        out.append(Issue("missing_document_number", WARNING, "No se ha podido leer el número de factura.", "document_number"))

    # --- NIF ----------------------------------------------------------------
    _check_tax_ids(n, out, invoice_like)
    _check_flow(n, client, out)

    # --- duplicados ---------------------------------------------------------
    dup = find_duplicate_by_number(
        client, flow=n.flow, issuer_tax_id=n.issuer_tax_id, document_number=n.document_number,
        exclude_pk=getattr(document, "pk", None),
    )
    if dup is not None:
        out.append(Issue(
            "duplicate_document", ERROR,
            f"Posible duplicado del documento #{dup.pk} (mismo emisor y número «{n.document_number}»).",
            "document_number",
        ))
    return out


def _check_amounts(n, out, invoice_like):
    base, total = n.base_amount, n.total_amount
    vat = [t for t in n.tax_lines if t.kind == "vat"]
    if base is not None and total is not None:
        lines = [t for t in n.tax_lines if t.amount is not None]
        sign = -1 if base < 0 else 1   # en una rectificativa todo va en negativo
        expected = taxes.expected_total_from_lines(base, [_L(t, sign) for t in lines])
        if not taxes.totals_match(total, expected, TOTAL_TOLERANCE):
            out.append(Issue(
                "totals_mismatch", ERROR,
                f"El total ({total}) no cuadra con base + impuestos − retenciones ({expected}).",
                "total_amount", True,
            ))
    for t in n.tax_lines:
        if t.base is None or t.rate is None or t.amount is None:
            continue
        expected_amount = abs(taxes.percentage_of(t.base, t.rate))
        if abs(abs(t.amount) - expected_amount) > LINE_TOLERANCE:
            out.append(Issue(
                "tax_line_mismatch", ERROR,
                f"{_KIND_ES[t.kind]} {t.rate}%: {t.amount} no corresponde al {t.rate}% de {t.base} ({expected_amount}).",
                "tax_lines", True,
            ))
    with_base = [t for t in vat if t.base is not None]
    if base is not None and with_base and len(with_base) == len(vat):
        s = sum((t.base for t in with_base), Decimal(0))
        if abs(s - base) > LINE_TOLERANCE:
            out.append(Issue("base_split_mismatch", WARNING, f"La suma de bases por tipo de IVA ({s}) no coincide con la base ({base}).", "base_amount"))
    if n.document_type != "corrected_invoice":
        negatives = [x for x in (base, total) if x is not None and x < 0]
        if negatives:
            out.append(Issue("negative_amount", WARNING, "Importe negativo en un documento que no es rectificativo.", "total_amount"))


def _check_rates(n, out):
    for t in n.tax_lines:
        if t.rate is None:
            continue
        allowed, label = {
            "vat": (VAT_RATES, "IVA/IGIC"),
            "withholding": (WITHHOLDING_RATES, "retención"),
            "surcharge": (SURCHARGE_RATES, "recargo de equivalencia"),
        }[t.kind]
        if t.rate.normalize() not in {r.normalize() for r in allowed}:
            out.append(Issue("unusual_rate", WARNING, f"Tipo de {label} poco habitual: {t.rate}%.", "tax_lines"))


def _check_tax_ids(n, out, invoice_like):
    for who, value in (("emisor", n.issuer_tax_id), ("destinatario", n.recipient_tax_id)):
        chk = check_tax_id(value)
        if chk is None:
            continue
        if chk.valid is False:
            out.append(Issue("invalid_tax_id", ERROR, f"El NIF/CIF del {who} ({value}) no es válido (dígito de control).", f"{who}_tax_id", True))
        elif chk.kind == "foreign":
            out.append(Issue("foreign_tax_id", INFO, f"El {who} tiene un identificador fiscal extranjero ({value}); no se puede verificar.", f"{who}_tax_id"))
    if not n.issuer_tax_id:
        sev = ERROR if invoice_like else WARNING
        out.append(Issue("missing_issuer_tax_id", sev, "No se ha podido leer el NIF/CIF del emisor.", "issuer_tax_id", True))


def _check_flow(n, client, out):
    if n.flow != "unknown":
        return
    if not (client.tax_id or "").strip():
        msg = "El cliente no tiene NIF configurado: no se puede saber si es ingreso o gasto."
    else:
        msg = "El NIF del cliente no figura como emisor ni como destinatario: no se puede clasificar como ingreso o gasto."
    out.append(Issue("flow_unknown", ERROR, msg, "flow"))


_KIND_ES = {"vat": "IVA", "withholding": "Retención", "surcharge": "Recargo"}


class _L:
    """Adaptador para taxes.summarize (.kind/.amount): importes con el signo de la base.

    El modelo puede devolver la retención en positivo o en negativo; lo que cuenta es
    la magnitud, y el signo lo marca la base (negativa en una rectificativa).
    """
    def __init__(self, t, sign=1):
        self.kind, self.amount = t.kind, abs(t.amount) * sign


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewDecision:
    review_level: str       # auto | recommended | required
    auto_approve: bool


_ORDER = {"auto": 0, "recommended": 1, "required": 2}


def decide(issues, n) -> ReviewDecision:
    """Nivel de revisión y si se auto-aprueba.

    ERROR → required. WARNING → al menos recommended. Sin incidencias se aplica el
    umbral de confianza (`get_review_level`); la auto-aprobación solo ocurre si
    `settings.EXTRACTION_AUTO_APPROVE` está activo (por defecto NO).
    """
    if any(i.severity == ERROR for i in issues):
        return ReviewDecision("required", False)
    by_confidence = get_review_level(n.legacy_confidence(), n.document_type or "other")
    level = by_confidence
    if any(i.severity == WARNING for i in issues):
        level = max(level, "recommended", key=_ORDER.get)
    if level == "auto":
        if (settings.EXTRACTION_AUTO_APPROVE
                and n.confidence_global >= settings.EXTRACTION_AUTO_APPROVE_MIN_CONFIDENCE):
            return ReviewDecision("auto", True)
        return ReviewDecision("recommended", False)
    return ReviewDecision(level, False)


def fallback_problems(issues) -> list[Issue]:
    """Incidencias que justifican reintentar con el modelo de respaldo."""
    return [i for i in issues if i.severity == ERROR and i.model_fixable]
