"""Datos de la pantalla de inicio: KPIs con tendencia, gráfico, embudo de documentos,
tarjeta de atención, top de gastos y actividad reciente.

Todo se filtra por cliente (multi-tenant). Sin dependencias de la vista.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone

from documents.models import DocumentAuditLog
from documents.selectors.document_selector import ACTIVE_PROCESSING, DocumentSelector
from finance.models import FinancialMovement

MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
ZERO = Decimal("0")

# acción de auditoría -> (verbo, icono del registro ui, tono)
ACTIVITY = {
    "created": ("Subiste", "upload", "info"),
    "extracted": ("Se extrajeron los datos de", "extract", "info"),
    "edited": ("Editaste", "edit", "neutral"),
    "approved": ("Aprobaste", "approve", "success"),
    "rejected": ("Rechazaste", "reject", "danger"),
    "archived": ("Archivaste", "archive", "neutral"),
    "unarchived": ("Desarchivaste", "unarchive", "neutral"),
    "rectified": ("Rectificaste", "rectify", "warning"),
}


def add_months(d: date, n: int) -> date:
    """Primer día del mes `n` meses después (n puede ser negativo)."""
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def greeting(now) -> str:
    h = now.hour
    return "Buenos días" if h < 13 else "Buenas tardes" if h < 21 else "Buenas noches"


def sparkline(values, width=100, height=28, pad=3) -> str:
    """Puntos de un <polyline> SVG para una serie (vacío si no hay variación que mostrar)."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = width / (len(vals) - 1)
    return " ".join(
        f"{i * step:.1f},{height - pad - (v - lo) / span * (height - 2 * pad):.1f}"
        for i, v in enumerate(vals)
    )


def delta(current: Decimal, previous: Decimal, *, higher_is_good: bool = True):
    """Variación porcentual frente al periodo anterior, con el tono que le corresponde."""
    if not previous:
        return None
    pct = float((current - previous) / abs(previous) * 100)
    if abs(pct) < 0.05:
        return {"pct": 0.0, "dir": "flat", "tone": "neutral", "label": "0 %"}
    up = pct > 0
    good = up == higher_is_good
    return {
        "pct": round(pct, 1), "dir": "up" if up else "down",
        "tone": "success" if good else "danger",
        "label": f"{abs(pct):.0f} %".replace(".", ","),
    }


class DashboardService:
    MONTHS = 6

    @classmethod
    def build(cls, user, today: date | None = None) -> dict:
        client = user.client
        now = timezone.localtime()
        today = today or now.date()
        ctx = {
            "client": client,
            "greeting": greeting(now),
            "first_name": user.first_name or user.get_username(),
        }
        ctx.update(cls.finance(client, today))
        ctx.update(cls.documents(client))
        ctx["top_expenses"] = cls.top_expenses(client, today)
        ctx["activity"] = cls.activity(client)
        ctx["recent_movements"] = (
            FinancialMovement.objects.filter(client=client, is_active=True, date__lte=today)
            .select_related("category")[:5]
        )
        return ctx

    # ---- finanzas ---------------------------------------------------------------
    @classmethod
    def finance(cls, client, today: date) -> dict:
        first = add_months(today.replace(day=1), -(cls.MONTHS - 1))
        rows = (
            FinancialMovement.objects.filter(client=client, is_active=True, date__gte=first, date__lte=today)
            .annotate(m=TruncMonth("date"))
            .values("m", "movement_type")
            .annotate(total=Sum("amount"))
        )
        totals: dict[tuple[date, str], Decimal] = {}
        for r in rows:
            m = r["m"].date() if hasattr(r["m"], "date") else r["m"]
            totals[(m, r["movement_type"])] = r["total"] or ZERO

        months = [add_months(first, i) for i in range(cls.MONTHS)]
        income = [totals.get((m, "income"), ZERO) for m in months]
        expense = [totals.get((m, "expense"), ZERO) for m in months]
        balance = [i - e for i, e in zip(income, expense)]

        # Comparación honesta: el mes en curso frente al MISMO tramo del mes anterior
        prev_start = add_months(today.replace(day=1), -1)
        prev_end = min(prev_start + timedelta(days=today.day - 1), today.replace(day=1) - timedelta(days=1))
        prev = FinancialMovement.objects.filter(
            client=client, is_active=True, date__gte=prev_start, date__lte=prev_end
        ).aggregate(
            income=Sum("amount", filter=Q(movement_type="income")),
            expense=Sum("amount", filter=Q(movement_type="expense")),
        )
        p_inc, p_exp = prev["income"] or ZERO, prev["expense"] or ZERO
        c_inc, c_exp = income[-1], expense[-1]
        c_bal = c_inc - c_exp

        def kpi(key, label, icon, value, series, d, tone):
            return {"key": key, "label": label, "icon": icon, "value": value,
                    "spark": sparkline(series), "delta": d, "tone": tone}

        return {
            "kpis": [
                kpi("income", "Ingresos", "income", c_inc, income, delta(c_inc, p_inc), "success"),
                kpi("expense", "Gastos", "expense", c_exp, expense, delta(c_exp, p_exp, higher_is_good=False), "danger"),
                kpi("balance", "Balance", "balance", c_bal, balance, delta(c_bal, p_inc - p_exp),
                    "success" if c_bal >= 0 else "danger"),
            ],
            # totales del mes (también los consume el resto de la app y los tests)
            "finance_income_total": c_inc,
            "finance_expense_total": c_exp,
            "finance_balance": c_bal,
            "period_label": f"{MONTHS_ES[today.month - 1]}. {today.year} · vs. mismo periodo del mes anterior",
            "chart": {
                "labels": [MONTHS_ES[m.month - 1] for m in months],
                "income": [float(v) for v in income],
                "expense": [float(v) for v in expense],
                "balance": [float(v) for v in balance],
            },
        }

    # ---- documentos --------------------------------------------------------------
    @classmethod
    def documents(cls, client) -> dict:
        qs = DocumentSelector.for_client(client).filter(is_archived=False)
        c = qs.aggregate(
            processing=Count("pk", filter=Q(processing_status__in=ACTIVE_PROCESSING)),
            failed=Count("pk", filter=Q(processing_status="failed")),
            review=Count("pk", filter=Q(status="pending", processing_status="processed")),
            required=Count("pk", filter=Q(status="pending", processing_status="processed", review_level="required")),
            recommended=Count("pk", filter=Q(status="pending", processing_status="processed", review_level="recommended")),
            approved=Count("pk", filter=Q(status="approved")),
            rejected=Count("pk", filter=Q(status="rejected")),
        )
        list_url = reverse("documents:list")
        stages = [
            ("processing", "Procesando", c["processing"], "info", f"{list_url}?processing=active", "processing:processing"),
            ("failed", "Con error", c["failed"], "danger", f"{list_url}?processing=failed", "processing:failed"),
            ("review", "Por revisar", c["review"], "warning", f"{list_url}?status=pending", "review:recommended"),
            ("approved", "Aprobados", c["approved"], "success", f"{list_url}?status=approved", "status:approved"),
            ("rejected", "Rechazados", c["rejected"], "neutral", f"{list_url}?status=rejected", "status:rejected"),
        ]
        total = sum(s[2] for s in stages)
        funnel = [
            {"key": k, "label": label, "count": n, "tone": tone, "url": url, "icon": icon,
             "pct": round(n / total * 100, 1) if total else 0}
            for k, label, n, tone, url, icon in stages
        ]

        unreconciled = FinancialMovement.objects.filter(client=client, is_active=True, is_reconciled=False).count()
        attention = [a for a in [
            {"label": "Documentos con revisión obligatoria", "count": c["required"], "tone": "danger",
             "icon": "review:required", "url": f"{list_url}?status=pending&review_level=required", "cta": "Revisar"},
            {"label": "Extracciones con error", "count": c["failed"], "tone": "danger",
             "icon": "processing:failed", "url": f"{list_url}?processing=failed", "cta": "Ver"},
            {"label": "Revisión recomendada", "count": c["recommended"], "tone": "warning",
             "icon": "review:recommended", "url": f"{list_url}?status=pending&review_level=recommended", "cta": "Revisar"},
            {"label": "Movimientos sin conciliar", "count": unreconciled, "tone": "warning",
             "icon": "reconcile:pending", "url": reverse("finance:movements"), "cta": "Conciliar"},
        ] if a["count"]]

        pending = qs.filter(status="pending").select_related("company").order_by("-created_at")
        return {
            "funnel": funnel, "funnel_total": total,
            "processing_count": c["processing"],
            "pending_count": c["review"],
            "attention": attention,
            "pending_documents": pending[:8],
        }

    # ---- gastos y actividad -------------------------------------------------------
    @classmethod
    def top_expenses(cls, client, today: date, limit: int = 5) -> list[dict]:
        rows = list(
            FinancialMovement.objects.filter(
                client=client, is_active=True, movement_type="expense",
                date__gte=today.replace(day=1), date__lte=today,
            )
            .values("category__name", "category__icon", "category__color")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:limit]
        )
        top = rows[0]["total"] if rows else ZERO
        return [
            {"name": r["category__name"], "icon": r["category__icon"], "color": r["category__color"],
             "total": r["total"], "pct": round(float(r["total"] / top * 100), 1) if top else 0}
            for r in rows
        ]

    @classmethod
    def activity(cls, client, limit: int = 8) -> list[dict]:
        logs = (
            DocumentAuditLog.objects.filter(document__client=client)
            .select_related("document", "user")
            .order_by("-created_at", "-id")[:limit]
        )
        out = []
        for log in logs:
            verb, icon, tone = ACTIVITY.get(log.action, (log.get_action_display(), "document", "neutral"))
            failed = log.action == "extracted" and log.changes.get("failed")
            if failed:
                verb, icon, tone = "Falló la extracción de", "retry", "danger"
            auto = log.action == "approved" and log.user_id is None
            if auto:
                verb = "Se aprobó automáticamente"
            out.append({
                "verb": verb, "icon": icon, "tone": tone, "created_at": log.created_at,
                "document": log.document,
                "label": log.document.document_number or log.document.original_name,
                "who": log.user.get_username() if log.user_id else "Sistema",
            })
        return out
