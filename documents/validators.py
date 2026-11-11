"""Validadores de identificadores fiscales (sin acceso a BD)."""
import re
from dataclasses import dataclass

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_LETTERS = "JABCDEFGHI"           # letra de control equivalente al dígito 0-9
CIF_LETTER_ONLY = set("NPQRSW")      # el control debe ser letra
CIF_DIGIT_ONLY = set("ABEH")         # el control debe ser dígito

_DNI = re.compile(r"^\d{8}[A-Z]$")
_NIE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
_CIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
_OTHER_ES = re.compile(r"^[KLM]\d{7}[A-Z0-9]$")            # NIF especiales (menores, extranjeros)
_FOREIGN = re.compile(r"^(?!ES)[A-Z]{2}[A-Z0-9]{8,12}$")   # IVA intracomunitario / otros países
# Un identificador español siempre lleva alguna letra; solo dígitos puede ser de otro país.
_LOOKS_SPANISH = re.compile(r"^(?=.*[A-Z])[A-Z0-9]\d{6,9}[A-Z0-9]?$")


@dataclass(frozen=True)
class TaxIdCheck:
    kind: str            # dni | nie | cif | other_es | foreign | unknown
    valid: bool | None   # None = no se puede verificar (extranjero o formato desconocido)


_LABEL = re.compile(r"^\s*(?:N\.?\s?I\.?\s?F|C\.?\s?I\.?\s?F|N\.?\s?I\.?\s?E|V\.?\s?A\.?\s?T|I\.?\s?V\.?\s?A)\.?\s*[:\-]\s*", re.I)


def clean_tax_id(value: str | None) -> str:
    """Forma canónica de un NIF/CIF/NIE/IVA: mayúsculas, solo letras y dígitos, sin prefijo "ES".

    "b-96.148.028", "B/96148028", "ES B96148028" y "NIF: B96148028" dan "B96148028".
    """
    s = _LABEL.sub("", value or "")
    s = re.sub(r"[^A-Z0-9]", "", s.upper())
    if re.fullmatch(r"ES[A-Z0-9]{9}", s):
        s = s[2:]
    return s


def _dni_letter(number: str) -> str:
    return DNI_LETTERS[int(number) % 23]


def _cif_control_digit(digits7: str) -> int:
    odd = sum(sum(divmod(int(c) * 2, 10)) for c in digits7[0::2])   # posiciones 1,3,5,7 duplicadas
    even = sum(int(c) for c in digits7[1::2])
    return (10 - (odd + even) % 10) % 10


def check_tax_id(value: str | None) -> TaxIdCheck | None:
    """Clasifica y valida un NIF/NIE/CIF español. None si no hay valor."""
    s = clean_tax_id(value)
    if not s:
        return None
    if _DNI.match(s):
        return TaxIdCheck("dni", _dni_letter(s[:8]) == s[8])
    if _NIE.match(s):
        number = str("XYZ".index(s[0])) + s[1:8]
        return TaxIdCheck("nie", _dni_letter(number) == s[8])
    if _CIF.match(s):
        digit = _cif_control_digit(s[1:8])
        control = s[8]
        if s[0] in CIF_LETTER_ONLY:
            ok = control == CIF_LETTERS[digit]
        elif s[0] in CIF_DIGIT_ONLY:
            ok = control == str(digit)
        else:
            ok = control in (str(digit), CIF_LETTERS[digit])
        return TaxIdCheck("cif", ok)
    if _OTHER_ES.match(s):
        return TaxIdCheck("other_es", None)
    if _FOREIGN.match(s):
        return TaxIdCheck("foreign", None)
    # Parece español pero no cumple ningún formato → casi seguro una lectura errónea.
    return TaxIdCheck("unknown", False if _LOOKS_SPANISH.match(s) else None)


def is_valid_tax_id(value: str | None) -> bool:
    c = check_tax_id(value)
    return bool(c and c.valid)
