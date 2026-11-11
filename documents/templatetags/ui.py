"""Componentes de UI compartidos: iconos y badges de estado.

Un único registro: el mismo concepto usa siempre el mismo icono y el mismo tono
en todas las pantallas (listado, dashboard, detalle...).

    {% icon "approve" %}
    {% badge "status" doc.status %}
    {% badge "review" doc.review_key %}
    {% badge "processing" doc.processing_status %}
"""
from django import template
from django.utils.html import format_html

register = template.Library()

# --- Iconos de acciones / conceptos (Font Awesome 6) ---------------------------
ICONS = {
    "approve": "fa-solid fa-check",
    "reject": "fa-solid fa-xmark",
    "save": "fa-solid fa-floppy-disk",
    "archive": "fa-solid fa-box-archive",
    "unarchive": "fa-solid fa-box-open",
    "rectify": "fa-solid fa-pen-to-square",
    "retry": "fa-solid fa-rotate-right",
    "view": "fa-regular fa-eye",
    "upload": "fa-solid fa-cloud-arrow-up",
    "camera": "fa-solid fa-camera",
    "download": "fa-solid fa-download",
    "filter": "fa-solid fa-filter",
    "search": "fa-solid fa-magnifying-glass",
    "back": "fa-solid fa-arrow-left",
    "next": "fa-solid fa-arrow-right",
    "new": "fa-solid fa-plus",
    "edit": "fa-solid fa-pen",
    "delete": "fa-solid fa-trash",
    "list": "fa-solid fa-list",
    "document": "fa-regular fa-file-lines",
    "folder": "fa-regular fa-folder",
    "history": "fa-solid fa-clock-rotate-left",
    "extract": "fa-solid fa-wand-magic-sparkles",
    "income": "fa-solid fa-arrow-trend-up",
    "expense": "fa-solid fa-arrow-trend-down",
    "balance": "fa-solid fa-scale-balanced",
    "movements": "fa-solid fa-money-bill-transfer",
    "categories": "fa-solid fa-tags",
    "caret": "fa-solid fa-chevron-down",
    "home": "fa-solid fa-house",
    "finance": "fa-solid fa-coins",
    "metrics": "fa-solid fa-chart-line",
    "profile": "fa-solid fa-user",
    "menu": "fa-solid fa-bars",
    "collapse": "fa-solid fa-angles-left",
    "logout": "fa-solid fa-right-from-bracket",
}

# --- Badges: (icono, tono, etiqueta) -------------------------------------------
BADGES = {
    "status": {
        "pending": ("fa-solid fa-hourglass-half", "info", "Pendiente"),
        "approved": ("fa-solid fa-circle-check", "success", "Aprobado"),
        "rejected": ("fa-solid fa-circle-xmark", "danger", "Rechazado"),
        "archived": ("fa-solid fa-box-archive", "neutral", "Archivado"),
    },
    "review": {
        "auto": ("fa-solid fa-robot", "success", "Auto"),
        "manual": ("fa-solid fa-user-check", "info", "Manual"),
        "recommended": ("fa-solid fa-eye", "warning", "Recomendada"),
        "required": ("fa-solid fa-circle-exclamation", "danger", "Obligatoria"),
    },
    "reconcile": {
        "reconciled": ("fa-solid fa-link", "success", "Conciliado"),
        "pending": ("fa-solid fa-clock", "warning", "Sin conciliar"),
    },
    "processing": {
        "uploaded": ("fa-solid fa-cloud-arrow-up", "info", "Subido"),
        "queued": ("fa-solid fa-hourglass-start", "info", "En cola"),
        "processing": ("fa-solid fa-spinner fa-spin", "info", "Extrayendo"),
        "failed": ("fa-solid fa-triangle-exclamation", "danger", "Error"),
    },
}


@register.simple_tag
def icon(name, extra=""):
    classes = ICONS.get(name, "fa-solid fa-circle")
    return format_html('<i class="{} {}" aria-hidden="true"></i>', classes, extra)


@register.simple_tag
def badge(kind, value, label=None):
    spec = BADGES.get(kind, {}).get(value)
    if spec is None:
        return ""
    icon_cls, tone, default_label = spec
    return format_html(
        '<span class="badge-status tone-{}" data-{}="{}"><i class="{}" aria-hidden="true"></i><span>{}</span></span>',
        tone, kind, value, icon_cls, label or default_label,
    )


MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


@register.filter
def pretty_date(value):
    """date/datetime -> 'Feb. 05 de 2024' (mes abreviado de 3 letras, siempre igual)."""
    if not value:
        return ""
    return f"{MONTHS_ES[value.month - 1]}. {value.day:02d} de {value.year}"


@register.simple_tag
def badge_icon(spec, extra=""):
    """Icono de un badge a partir de «tipo:valor» (p. ej. 'review:required'); mismo icono que el badge."""
    kind, _, value = spec.partition(":")
    entry = BADGES.get(kind, {}).get(value)
    return format_html('<i class="{} {}" aria-hidden="true"></i>', entry[0] if entry else "fa-solid fa-circle", extra)
