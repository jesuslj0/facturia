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
            flow="in",
            document_type__in=["invoice", "corrected_invoice"],
        )

        # Expresión para extraer cantidad
        amount_expression = Case(
            When(document_type="corrected_invoice", then=-F("total_amount")),
            default=F("total_amount"),
            output_field=DecimalField()
        )
        
        financial_totals = billing_queryset.aggregate(
            total_amount=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("total_amount")),
                    default=F("total_amount"),
                    output_field=DecimalField()
                )
            ),
            total_tax=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("tax_amount")),
                    default=F("tax_amount"),
                    output_field=DecimalField()
                )
            ),
            total_base=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("base_amount")),
                    default=F("base_amount"),
                    output_field=DecimalField()
                )
            ),
        )

        # =========================
        # 📅 3. MÉTRICAS MES ACTUAL
        # =========================
        month_queryset = billing_queryset.filter(
            issue_date__gte=start_month
        )

        monthly_data = (
            queryset
            .filter(
                status="approved",
                document_type__in=["invoice", "corrected_invoice"],
            )
            .annotate(month=TruncMonth("issue_date"))
            .values("month", "flow")
            .annotate(total=Sum(amount_expression))
            .order_by("month")
        )

        # Gráfica de datos mensuales
        result = defaultdict(lambda: {"in": 0, "out": 0})

        for row in monthly_data:
            month_label = DateFormat(row["month"]).format("M Y")
            result[month_label][row["flow"]] = float(row["total"] or 0)

        labels = list(result.keys())
        income = [result[m]["out"] for m in labels]
        expense = [result[m]["in"] for m in labels]

        income_expense_chart = {
            "labels": labels,
            "income": income,
            "expense": expense,
        }

        month_totals = month_queryset.aggregate(
            total_amount=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("total_amount")),
                    default=F("total_amount"),
                    output_field=DecimalField()
                )
            ),
            total_tax=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("tax_amount")),
                    default=F("tax_amount"),
                    output_field=DecimalField()
                )
            ),
            total_base=Sum(
                Case(
                    When(document_type="corrected_invoice", then=-F("base_amount")),
                    default=F("base_amount"),
                    output_field=DecimalField()
                )
            ),
            documents_count=Sum(
                Case(
                    When(document_type="corrected_invoice", then=0),
                    default=1,
                    output_field=DecimalField()
                )
            ),
            approved_count=Sum(
                Case(
                    When(document_type="corrected_invoice", then=0),  # no sumas al aprobado
                    When(status="approved", then=1),
                    default=0,
                    output_field=DecimalField()
                )
            )
        )

        return {
            "documents": {
                **totals,
                "approval_rate": round(approval_rate, 2),
                "auto_approval_rate": round(auto_approval_rate, 2),
                "manual_approval_rate": round(manual_approval_rate, 2),
            },
            "financials": {
                "total_amount": financial_totals["total_amount"] or 0,
                "total_tax": financial_totals["total_tax"] or 0,
                "total_base": financial_totals["total_base"] or 0,
            },
            "current_month": {
                "documents": month_totals["documents_count"] or 0,
                "approved": month_totals["approved_count"] or 0,
                "total_amount": month_totals["total_amount"] or 0,
                "total_tax": month_totals["total_tax"] or 0,
                "month": date_format(timezone.now(), "F"),
                "year": date_format(timezone.now(), "Y"),
            },
            "income_expense_chart": income_expense_chart
        }
