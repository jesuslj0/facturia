"""Datos de presentación de la página de Métricas (derivados de MetricsService).

Defensivo a propósito: acepta diccionarios incompletos (tests con servicio simulado,
cuentas sin datos) y nunca divide por cero.
"""
from datetime import date, timedelta

from django.urls import reverse

from documents.services.dashboard_service import add_months, delta


def g(data, *path, default=0):
    """Acceso seguro a data[a][b]... con valor por defecto."""
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return default if data is None else data


def pct(part, whole) -> float:
    return round(float(part) / float(whole) * 100, 1) if whole else 0.0


def previous_period(start: date, end: date) -> tuple[date, date]:
    """Periodo inmediatamente anterior y de la misma duración."""
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


def presets(today: date, start: date, end: date) -> list[dict]:
    month_start = today.replace(day=1)
    prev_month = add_months(month_start, -1)
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    options = [
        ("Este mes", month_start, today),
        ("Mes anterior", prev_month, month_start - timedelta(days=1)),
        ("Trimestre", quarter_start, today),
        ("Este año", date(today.year, 1, 1), today),
        ("12 meses", add_months(month_start, -11), today),
    ]
    return [
        {"label": label, "start": s, "end": e, "active": (s, e) == (start, end),
         "query": f"?start={s:%Y-%m-%d}&end={e:%Y-%m-%d}"}
        for label, s, e in options
    ]


def _source(key, label, block, extra_label="", extra_value=None):
    income, expense = g(block, "income"), g(block, "expense")
    return {
        "key": key, "label": label, "income": income, "expense": expense,
        "profit": g(block, "profit", default=income - expense), "margin": g(block, "profit_margin"),
        "extra_label": extra_label, "extra_value": extra_value,
    }


def build_page(metrics: dict, historical: dict, period: dict, previous: dict | None = None) -> dict:
    fin = g(metrics, "financials", default={})
    docs = g(metrics, "documents", default={})
    comb = g(fin, "combined", default={})
    prev_comb = g(previous or {}, "financials", "combined", default={})

    income, expense, profit = g(comb, "income"), g(comb, "expense"), g(comb, "profit")
    total_flow = income + expense
    hero = {
        "income": income, "expense": expense, "profit": profit, "margin": g(comb, "profit_margin"),
        "tone": "success" if profit >= 0 else "danger",
        "delta_profit": delta(profit, g(prev_comb, "profit")) if prev_comb else None,
        "delta_income": delta(income, g(prev_comb, "income")) if prev_comb else None,
        "delta_expense": delta(expense, g(prev_comb, "expense"), higher_is_good=False) if prev_comb else None,
        "income_pct": pct(income, total_flow), "expense_pct": pct(expense, total_flow),
    }

    sources = [
        _source("combined", "Combinado", comb),
        _source("documents", "Facturas", g(fin, "documents", default={}), "Facturas aprobadas", g(docs, "approved")),
        _source("movements", "Movimientos", g(fin, "movements", default={}), "Movimientos", g(fin, "movements", "count")),
    ]

    vat = g(fin, "documents", "vat", default={})
    collected, paid = g(vat, "collected"), g(vat, "paid")
    balance = g(vat, "balance", default=collected - paid)
    top = max(abs(collected), abs(paid))
    withholding = g(fin, "documents", "withholding", default={})
    surcharge = g(fin, "documents", "surcharge", default={})
    vat_panel = {
        "collected": collected, "paid": paid, "balance": balance, "abs_balance": abs(balance),
        "collected_pct": pct(abs(collected), top), "paid_pct": pct(abs(paid), top),
        "to_pay": balance >= 0, "tone": "warning" if balance >= 0 else "info",
        "withholding_suffered": g(withholding, "suffered"), "withholding_applied": g(withholding, "applied"),
        "surcharge_collected": g(surcharge, "collected"), "surcharge_paid": g(surcharge, "paid"),
        "has_extras": any(g(withholding, k) or g(surcharge, k2) for k, k2 in (("suffered", "collected"), ("applied", "paid"))),
    }

    q = f"date_from={period['start']:%Y-%m-%d}&date_to={period['end']:%Y-%m-%d}" if isinstance(period.get("start"), date) else ""
    list_url = reverse("documents:list")
    approved, pending, rejected = g(docs, "approved"), g(docs, "pending"), g(docs, "rejected")
    total_docs = g(docs, "total", default=approved + pending + rejected)
    funnel = [
        {"key": k, "label": label, "count": n, "tone": tone, "icon": icon, "pct": pct(n, total_docs),
         "url": f"{list_url}?status={k}&{q}"}
        for k, label, n, tone, icon in (
            ("approved", "Aprobados", approved, "success", "status:approved"),
            ("pending", "Pendientes", pending, "warning", "status:pending"),
            ("rejected", "Rechazados", rejected, "danger", "status:rejected"),
        )
    ]

    companies_raw = g(metrics, "charts", "by_company", default=[])
    scale = max([c["income"] + c["expense"] for c in companies_raw] or [0])
    companies = [
        {"name": c["name"], "income": c["income"], "expense": c["expense"], "count": c.get("count", 0),
         "net": c["income"] - c["expense"], "pct": pct(c["income"] + c["expense"], scale),
         "tone": "success" if c["income"] >= c["expense"] else "danger"}
        for c in companies_raw[:6]
    ]

    status = g(metrics, "status_distribution", default={})
    chart_data = {
        "monthly": g(metrics, "charts", "income_expense_monthly", default=[]),
        "quarters": g(metrics, "charts", "by_quarter", default=[]),
        "status": [
            {"label": label, "value": status.get(key, 0), "tone": tone}
            for key, label, tone in (
                ("auto_approved", "Aprobados (auto)", "success"),
                ("manual_approved", "Aprobados (manual)", "info"),
                ("pending", "Pendientes", "warning"),
                ("rejected", "Rechazados", "danger"),
            )
        ],
    }
    extraction = g(metrics, "extraction", default={})

    return {
        "hero": hero, "sources": sources, "vat": vat_panel,
        "funnel": funnel, "funnel_total": total_docs,
        "historical": historical or {},
        "automation": {
            "confidence": g(docs, "confidence_average"),
            "auto_rate": g(docs, "auto_approval_rate"),
            "manual_rate": g(docs, "manual_approval_rate"),
            "has_decisions": any(s["value"] for s in chart_data["status"]),
            "extraction": extraction if g(extraction, "runs") else None,
        },
        "companies": companies,
        "has_quarters": bool(chart_data["quarters"]),
        "has_monthly": bool(chart_data["monthly"]),
        "chart_data": chart_data,
        "presets": [],
    }
