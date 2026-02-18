from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import datetime
from documents.models import Document


class MetricsService:

    @staticmethod
    def get_user_metrics(user):
        queryset = Document.objects.filter(
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
            manual_review_count=Count("id", filter=Q(review_level="manual")),
        )

        total_documents = totals["total_documents"] or 0
        approved_documents = totals["approved_documents"] or 0

        approval_rate = (
            (approved_documents / total_documents) * 100
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

        financial_totals = billing_queryset.aggregate(
            total_amount=Sum("total_amount"),
            total_tax=Sum("tax_amount"),
            total_base=Sum("base_amount"),
        )

        # =========================
        # 📅 3. MÉTRICAS MES ACTUAL
        # =========================
        month_queryset = billing_queryset.filter(
            issue_date__gte=start_month
        )

        month_totals = month_queryset.aggregate(
            month_documents=Count("id"),
            month_approved=Count("id", filter=Q(status="approved")),
            month_total_amount=Sum("total_amount"),
            month_total_tax=Sum("tax_amount"),
        )

        return {
            "documents": {
                **totals,
                "approval_rate": round(approval_rate, 2),
            },
            "financials": {
                "total_amount": financial_totals["total_amount"] or 0,
                "total_tax": financial_totals["total_tax"] or 0,
                "total_base": financial_totals["total_base"] or 0,
            },
            "current_month": {
                "documents": month_totals["month_documents"] or 0,
                "approved": month_totals["month_approved"] or 0,
                "total_amount": month_totals["month_total_amount"] or 0,
                "total_tax": month_totals["month_total_tax"] or 0,
            }
        }
