"""Normalización de nombres de terceros para detectar duplicados (sin acceso a BD).

`display_name` limpia lo que se muestra; `name_key` da la clave de comparación: dos nombres que
solo difieren en mayúsculas, tildes, comas, puntos o forma jurídica (S.L., SL, S.L.U....) tienen
la misma clave. No reordena palabras: "García Juan" y "Juan García" siguen siendo distintos.
"""
import re
import unicodedata

# Formas jurídicas habituales, escritas sin puntos ni espacios.
LEGAL_FORMS = {
    "sl", "slu", "sa", "sau", "sll", "slp", "sal", "slne", "scoop", "scoopand", "sccl",
    "cb", "sc", "scp", "srl", "ltd", "llc", "gmbh", "inc", "sociedadlimitada",
    "sociedadanonima", "sociedadcooperativa", "comunidaddebienes", "sociedadcivil",
}
_WRAP = " \t\r\n,;:-–—_\"'«»“”"      # sin "." para no romper "S.L." al final


def display_name(name: str | None) -> str:
    """Nombre limpio para mostrar: espacios colapsados y sin signos sobrantes en los extremos."""
    s = unicodedata.normalize("NFC", name or "")
    s = re.sub(r"\s+", " ", s).strip(_WRAP).lstrip(".").strip(_WRAP)
    s = re.sub(r"\s+,", ",", s)             # "Empresa , S.L." -> "Empresa, S.L."
    s = re.sub(r",(?=\S)", ", ", s)         # "Empresa,S.L." -> "Empresa, S.L."
    return s


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def name_key(name: str | None) -> str:
    """Clave de comparación: minúsculas, sin tildes ni puntuación y sin la forma jurídica final."""
    s = _strip_accents(unicodedata.normalize("NFKC", name or "")).lower().replace("&", " y ")
    tokens = re.findall(r"[a-z0-9]+", s)
    for n in (3, 2, 1):                      # "s l u" -> "slu"; "s.coop.and" -> "scoopand"
        if len(tokens) > n and "".join(tokens[-n:]) in LEGAL_FORMS:
            tokens = tokens[:-n]
            break
    return " ".join(tokens)
