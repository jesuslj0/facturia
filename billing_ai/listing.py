"""Piezas comunes de las pantallas de listado: chips de filtros activos, pestañas de estado
y paginación compacta. Solo trabajan con `request.GET`; no tocan la base de datos."""
from datetime import date

from django.utils.dateparse import parse_date

NON_FILTER_PARAMS = {"page", "sort", "order"}


def qs_without(request, *drop: str) -> str:
    """Querystring actual sin `page` ni los parámetros indicados (conserva orden y el resto)."""
    params = request.GET.copy()
    for key in ("page", *drop):
        params.pop(key, None)
    return params.urlencode()


def qs_with(request, **changes) -> str:
    """Querystring actual con `changes` aplicados (valor vacío/None = quitar) y sin `page`."""
    params = request.GET.copy()
    params.pop("page", None)
    for key, value in changes.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


def pretty(value: str) -> str:
    """'2026-02-05' -> 'Feb. 05 de 2026'; cualquier otra cosa se devuelve igual."""
    parsed = parse_date(value) if isinstance(value, str) else None
    if not isinstance(parsed, date):
        return value
    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    return f"{months[parsed.month - 1]}. {parsed.day:02d} de {parsed.year}"


def active_filters(request, spec) -> list[dict]:
    """Filtros aplicados, listos para pintarlos como chips con su enlace para quitarlos.

    `spec`: [(parámetro, etiqueta, mostrar, en_panel)] donde `mostrar` es un dict
    {valor: texto}, una función valor -> texto, o None (se muestra el valor tal cual).
    `en_panel` indica si el control vive dentro del panel desplegable de filtros.
    """
    items = []
    for param, label, show, in_panel in spec:
        value = request.GET.get(param)
        if not value:
            continue
        if callable(show):
            text = show(value)
        elif isinstance(show, dict):
            text = show.get(value, value)
        else:
            text = value
        query = qs_without(request, param)
        items.append({
            "param": param, "label": label, "text": text, "in_panel": in_panel,
            "remove_url": f"?{query}" if query else "?",
        })
    return items


def status_tabs(request, choices, param: str = "status") -> list[dict]:
    """Pestañas rápidas: [("", "Todos"), ("pending", "Pendientes"), ...] -> enlaces que conservan el resto."""
    current = request.GET.get(param, "")
    tabs = []
    for value, label in choices:
        query = qs_with(request, **{param: value})
        tabs.append({"value": value, "label": label, "active": current == value, "url": f"?{query}" if query else "?"})
    return tabs


def page_window(page_obj, around: int = 1) -> list:
    """Números de página a mostrar: [1, '…', 4, 5, 6, '…', 20]."""
    total, number = page_obj.paginator.num_pages, page_obj.number
    pages = sorted({1, total, *range(max(1, number - around), min(total, number + around) + 1)})
    out, prev = [], 0
    for p in pages:
        if p - prev > 1:
            out.append("…")
        out.append(p)
        prev = p
    return out
