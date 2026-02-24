from django.db.models import Sum, Count, Q, Avg, Case, When, DecimalField, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.formats import date_format
from documents.models import Document
from collections import defaultdict
from django.utils.dateformat import DateFormat


class MetricsService:

    @staticmethod
    def get_user_metrics(user):
        queryset = Document.all_objects.filter(
            client__clientuser__user=user
        )

        now = timezone.now()
        start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # =========================
        # 📊 1. MÉTRICAS GLOBALES
        # =========================
        totals = queryset.aggregate(
            total_documents=Count("id"),
            approved_documents=Count("id", filter=Q(status="approved")),
            rejected_documents=Count("id", filter=Q(status="rejected")),
            pending_documents=Count("id", filter=Q(status="pending")),
            manual_approved_count=Count("id", filter=Q(review_level="manual", status="approved")),
            auto_approved_count=Count("id", filter=Q(review_level="auto", status="approved", is_auto_approved=True)),
            confidence_average=Avg("confidence_global", filter=Q(status="approved"))*100,
        )

        total_documents = totals["total_documents"] or 0
        approved_documents = totals["approved_documents"] or 0

        approval_rate = (
            (approved_documents / total_documents) * 100
            if total_documents > 0 else 0
        )

        auto_approval_rate = (
            (totals["auto_approved_count"] / total_documents) * 100
            if total_documents > 0 else 0
        )

        manual_approval_rate = (
            (totals["manual_approved_count"] / total_documents) * 100
            if total_documents > 0 else 0
        )

        # =========================
        # 💰 2. FINANCIERAS GLOBALES
        # =========================

        # Quitar Albaranes de Facturación Real
        billing_queryset = queryset.filter(
            status="approved",
            document_type__in=["invoice", "corrected_invoice"],
        )

        income_queryset = billing_queryset.filter(flow="in")
        expense_queryset = billing_queryset.filter(flow="out")

        # Expresión para extraer cantidad con signo
        def signed(field):
            return Case(
                When(document_type="corrected_invoice", then=-F(field)),
                default=F(field),
                output_field=DecimalField()
            )

        # Totales facturacion 
        income_totals = income_queryset.aggregate(
            total_amount=Sum(signed("total_amount")),
            total_tax=Sum(signed("tax_amount")),
            total_base=Sum(signed("base_amount")),
        )

        expense_totals = expense_queryset.aggregate(
            total_amount=Sum(signed("total_amount")),
            total_tax=Sum(signed("tax_amount")),
            total_base=Sum(signed("base_amount")),
        )

        total_income = income_totals["total_amount"] or 0
        total_expense = expense_totals["total_amount"] or 0
        profit = total_income - total_expense
        profit_margin = (profit / total_income * 100) if total_income > 0 else 0    

        # Datos mensuales
        monthly_data = (
            queryset
            .filter(
                status="approved",
                document_type__in=["invoice", "corrected_invoice"],
            )
            .annotate(month=TruncMonth("issue_date"))
            .values("month", "flow")
            .annotate(total=Sum(signed("total_amount")))
            .order_by("month")
        )

        # Gráfica de datos mensuales
        result = defaultdict(lambda: {"in": 0, "out": 0})

        for row in monthly_data:
            month_label = DateFormat(row["month"]).format("M Y")
            result[month_label][row["flow"]] = float(row["total"] or 0)

        labels = list(result.keys())
        income = [result[m]["in"] for m in labels]
        expense = [result[m]["out"] for m in labels]

        income_expense_chart = {
            "labels": labels,
            "income": income,
            "expense": expense,
        }

        # Totales mensuales
        month_queryset = queryset.filter(
            issue_date__gte=start_month
        )

        month_totals = month_queryset.aggregate(
            documents_count=Count("id"),
            approved_count = Count("id", filter=Q(status="approved")),
        )

        month_income_qs = month_queryset.filter(flow="in")
        month_expense_qs = month_queryset.filter(flow="out")

        month_income = month_income_qs.aggregate(
            total_amount=Sum(signed("total_amount")),
            total_tax=Sum(signed("tax_amount")),
        )

        month_expense = month_expense_qs.aggregate(
            total_amount=Sum(signed("total_amount")),
            total_tax=Sum(signed("tax_amount")),
        )

        month_profit = (month_income["total_amount"] or 0) - (month_expense["total_amount"] or 0)

        return {
            "documents": {
                **totals,
                "approval_rate": round(approval_rate, 2),
                "auto_approval_rate": round(auto_approval_rate, 2),
                "manual_approval_rate": round(manual_approval_rate, 2),
            },
            "financials": {
                "income": {
                    "total_amount": total_income,
                    "total_tax": income_totals["total_tax"] or 0,
                    "total_base": income_totals["total_base"] or 0,
                },
                "expense": {
                    "total_amount": total_expense,
                    "total_tax": expense_totals["total_tax"] or 0,
                    "total_base": expense_totals["total_base"] or 0,
                },
                "profit": profit,
                "profit_margin": profit_margin,
            },
            "current_month": {
                "income": month_income["total_amount"] or 0,
                "expense": month_expense["total_amount"] or 0,
                "profit": month_profit,
                "documents": month_totals["documents_count"] or 0,
                "approved": month_totals["approved_count"] or 0,
                "month": date_format(timezone.now(), "F"),
                "year": date_format(timezone.now(), "Y"),
            },
            "income_expense_chart": income_expense_chart
        }
