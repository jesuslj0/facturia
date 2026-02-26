from django.db.models import Sum, Count, Q, Avg, Case, When, DecimalField, F
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from django.utils.formats import date_format
from documents.models import Document
from collections import defaultdict
from django.utils.dateformat import DateFormat
from decimal import Decimal


class MetricsService:

    @staticmethod
    def get_user_metrics(user, start=None, end=None):
        queryset = Document.all_objects.filter(
            client__clientuser__user=user
        )

        if start and end:
            queryset = queryset.filter(issue_date__range=[start, end])


        # 1. Metricas de documentos
        totals = queryset.aggregate(
            total_documents=Count("id"),
            approved_documents=Count("id", filter=Q(status="approved")),
            rejected_documents=Count("id", filter=Q(status="rejected")),
            pending_documents=Count("id", filter=Q(status="pending")),
            auto_approved_count=Count(
                "id",
                filter=Q(status="approved", review_level="auto", is_auto_approved=True)
            ),
            manual_approved_count=Count(
                "id",
                filter=Q(status="approved", review_level="manual")
            ),
            confidence_average=Avg(
                "confidence_global",
                filter=Q(status="approved")
            ),
        )

        total_documents = totals["total_documents"] or 0
        approved = totals["approved_documents"] or 0
        auto_approved = totals["auto_approved_count"] or 0
        manual_approved = totals["manual_approved_count"] or 0

        approval_rate = (approved / total_documents * 100) if total_documents else 0
        auto_rate = (auto_approved / total_documents * 100) if total_documents else 0
        manual_rate = (manual_approved / total_documents * 100) if total_documents else 0

        confidence_avg = (totals["confidence_average"] or 0) * 100


        # Financial metrics
        billing_queryset = queryset.filter(
            status="approved",
            document_type__in=["invoice", "corrected_invoice"],
        )

        income_queryset = billing_queryset.filter(flow="in")
        expense_queryset = billing_queryset.filter(flow="out")

        def signed(field):
            return Case(
                When(document_type="corrected_invoice", then=-F(field)),
                default=F(field),
                output_field=DecimalField()
            )
        
        def get_granularity(start, end):
            delta = (end - start).days
            if delta <= 31:
                return TruncDay, "%d %b"  # etiquetas tipo 1 Feb
            return TruncMonth, "%b %Y"  # etiquetas tipo Feb 2026

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

        total_income = income_totals["total_amount"] or Decimal("0")
        total_expense = expense_totals["total_amount"] or Decimal("0")
        profit = total_income - total_expense
        profit_margin = (profit / total_income * 100) if total_income > 0 else 0    

        # Datos mensuales (dentro del rango)
        trunc_func, date_format_str = get_granularity(start, end)

        monthly_data = (
            queryset
            .filter(issue_date__range=(start, end))
            .annotate(period=trunc_func("issue_date"))
            .values("period", "flow")
            .annotate(total=Sum(signed("total_amount")))
            .order_by("period")
        )

        chart_result = defaultdict(lambda: {"income": 0, "expense": 0})

        for row in monthly_data:
            key = row["period"].strftime(date_format_str)
            if row["flow"] == "in":
                chart_result[key]["income"] += float(row["total"] or 0)
            elif row["flow"] == "out":
                chart_result[key]["expense"] += float(row["total"] or 0)

        chart = [
            {
                "period": k, 
                "income": v["income"], 
                "expense": v["expense"], 
                "profit": v["income"] - v["expense"]
            }
            for k, v in chart_result.items()
        ]

        status_distribution = {
            "auto_approved": totals["auto_approved_count"] or 0,
            "rejected": totals["rejected_documents"] or 0,
            "pending": totals["pending_documents"] or 0,
            "manual_approved": totals["manual_approved_count"] or 0,
        }

        return {
            "period": {
                "start": start,
                "end": end,
            },
            "documents": {
                "total": total_documents,
                "approved": approved,
                "rejected": totals["rejected_documents"] or 0,
                "pending": totals["pending_documents"] or 0,
                "approval_rate": round(approval_rate, 2),
                "auto_approval_rate": round(auto_rate, 2),
                "manual_approval_rate": round(manual_rate, 2),
                "confidence_average": round(confidence_avg, 2),
            },
            "financials": {
                "income": float(total_income),
                "expense": float(total_expense),
                "profit": float(profit),
                "profit_margin": round(float(profit_margin), 2),
            },
            "charts": {
                "income_expense_monthly": chart,
            },
            "status_distribution": status_distribution,
        }