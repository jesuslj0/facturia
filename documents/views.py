from django.shortcuts import redirect, get_object_or_404
from .models import Document
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, ListView, DetailView, TemplateView
from django.contrib import messages
from django.utils import timezone
from django.db.models.functions import Coalesce
from django.db.models import DecimalField
from finance.models import FinancialMovement
from django.db.models import Q
from datetime import datetime
from .selectors.document_selector import DocumentSelector
from .services import DocumentService
from django.contrib.auth import get_user_model
from .filters.document_filters import get_filtered_documents
from documents.models import Company

User = get_user_model()

class DocumentListView(LoginRequiredMixin, ListView): 
    template_name = "private/documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 20
    
    def get_queryset(self):
        return get_filtered_documents(
            self.request,
            base_qs=DocumentSelector.for_client(self.request.user.client)
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        page_obj = context.get("page_obj")
        first_doc = page_obj.object_list.first() if page_obj else None

        context["client"] = first_doc.client if first_doc else None
        context["document_types"] = Document.TYPE_CHOICES
        context["companies"] = Company.objects.filter(client=self.request.user.client).order_by("name")

        # 🔹 Querystring sin page
        querydict = self.request.GET.copy()
        querydict.pop("page", None)
        context["querystring"] = querydict.urlencode()
        return context
    

class DocumentDetailView(LoginRequiredMixin, DetailView):
    template_name = "private/documents/document_detail.html"
    context_object_name = "document"

    def get_queryset(self):
        client = self.request.user.client
        return DocumentSelector.detail_queryset(client)
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action")

        # --- Aprobar ---
        if action == "approve" and self.object.status == "pending":
            return approve_document(request, self.object)

        # --- Rechazar ---
        if action == "reject" and self.object.status == "pending":
            rejection_reason = request.POST.get("rejection_reason")
            return reject_document(request, self.object, rejection_reason)

        # --- Guardar cambios ---
        if action == "save":
            return save_document(request, self.object)
        
        # --- Archivar ---
        if action == "archive" and self.object.status in ["approved", "rejected"]:
            return archive_document(request, self.object)
        
        # --- Desarchivar ---
        if action == "unarchive" and self.object.is_archived:
            return unarchive_document(request, self.object)

        # Si no hay acción reconocida, redirigir
        messages.warning(request, "Acción no reconocida.")
        return redirect("documents:detail", pk=self.object.pk)


def approve_document(request, document):
    DocumentService.approve(document, user=request.user)
    messages.success(request, "El documento ha sido aprobado.")
    return redirect("documents:detail", pk=document.pk)

def reject_document(request, document, reason=None):
    DocumentService.reject(document, user=request.user, reason=reason)
    messages.success(request, "El documento ha sido rechazado.")
    return redirect("documents:detail", pk=document.pk)

def save_document(request, document):
    try:
        DocumentService.update_from_form(
            document=document,
            user=request.user,
            data=request.POST
        )
    except ValueError:
        messages.error(request, "Importe inválido en uno de los campos.")
        return redirect("documents:detail", pk=document.pk)

    messages.success(request, "Cambios guardados correctamente.")
    return redirect("documents:detail", pk=document.pk)

def archive_document(request, document): 
    DocumentService.archive(document, user=request.user)
    messages.success(request, "Documento archivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

def unarchive_document(request, document):
    DocumentService.unarchive(document, user=request.user)
    messages.warning(request, "Documento desarchivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

class DashboardView(LoginRequiredMixin,TemplateView):
    template_name="private/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        client = self.request.user.client
        client = client if client else None

        qs = DocumentSelector.pending(client)
        today = timezone.now().date()
        month_start = today.replace(day=1)

        movement_qs = FinancialMovement.objects.filter(
            client=client,
            date__gte=month_start,
            date__lte=today,
            is_active=True,
        )

        pending_count = qs.count()
        required_count = qs.filter(review_level="required").count() or 0
        recommended_count = qs.filter(review_level="recommended").count() or 0

        income_total = movement_qs.filter(movement_type="income").aggregate(
            total=Coalesce(Sum("amount"), 0, output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"]
        expense_total = movement_qs.filter(movement_type="expense").aggregate(
            total=Coalesce(Sum("amount"), 0, output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"]
        balance = income_total - expense_total

        unreconciled_count = movement_qs.filter(is_reconciled=False).count()

        top_expense_categories = (
            movement_qs.filter(movement_type="expense")
            .values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:3]
        )

        context = {
            "pending_documents": qs.order_by("-created_at")[:10],
            "pending_count": pending_count,
            "required_review_count": required_count,
            "recommended_review_count": recommended_count,
            "client": client,
            "finance_period_label": f"{month_start.strftime('%d/%m/%Y')} - {today.strftime('%d/%m/%Y')}",
            "finance_income_total": income_total,
            "finance_expense_total": expense_total,
            "finance_balance": balance,
            "unreconciled_movements_count": unreconciled_count,
            "recent_movements": movement_qs.select_related("category")[:5],
            "top_expense_categories": top_expense_categories,
        }

        return context
    
from .utils import export_to_csv, export_to_excel
class DocumentExportView(LoginRequiredMixin, View):

    def get_exportable_queryset(self, ids=None):
        client = self.request.user.client

        base_qs = DocumentSelector.exportable(client)

        qs = get_filtered_documents(self.request, base_qs=base_qs)

        if ids:
            qs = qs.filter(id__in=ids)

        return qs
    
    def get(self, request):
        qs = self.get_exportable_queryset()
        return export_to_csv(qs)
    
    def post(self, request):
        ids = request.POST.getlist("ids")
        fmt = request.POST.get("format", "csv")

        qs = self.get_exportable_queryset(ids=ids)

        if fmt == "xlsx":
            return export_to_excel(qs)
        return export_to_csv(qs)
    
from django.db.models import Sum, Min, Max, Avg
class DocumentExportPreviewView(LoginRequiredMixin, ListView):
    template_name = "private/documents/document_export_preview.html"

    def get_exportable_queryset(self, ids=None):
        client = self.request.user.client

        base_qs = DocumentSelector.exportable(client)

        qs = get_filtered_documents(self.request, base_qs=base_qs)

        if ids:
            qs = qs.filter(id__in=ids)

        return qs

    def get_queryset(self):
        ids = self.request.GET.getlist("ids")
        return self.get_exportable_queryset(ids=ids)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        qs = self.get_queryset()

        context["documents_count"] = qs.count()
        context["providers_count"] = qs.values("company").distinct().count()

        summary = qs.aggregate(
            base_total=Sum("base_amount"),
            tax_total=Sum("tax_amount"),
            grand_total=Sum("total_amount"),
            min_date=Min("issue_date"),
            max_date=Max("issue_date"),
            avg_confidence=Avg("confidence_global"),
        )

        context["summary"] = summary
        summary["min_date"] = format_date(summary["min_date"], format="d MMMM y", locale="es")
        summary["max_date"] = format_date(summary["max_date"], format="d MMMM y", locale="es")

        return context

from .services import MetricsService
from babel.dates import format_date
from django.utils import timezone

class MetricsDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "private/metrics/dashboard.html"

    def get_dashboard_metrics(self, request):
        start = request.GET.get("start")
        end = request.GET.get("end")
        today = timezone.now().date()

        if not start:
            start = today.replace(day=1)
        else:
            start = timezone.datetime.strptime(start, "%Y-%m-%d").date()

        if not end:
            end = today
        else:
            end = timezone.datetime.strptime(end, "%Y-%m-%d").date()

        first_day_of_month = today.replace(day=1)
        is_current_month = (
            start == first_day_of_month and end == today
        )

        metrics = MetricsService.get_user_metrics(
            user=request.user,
            start=start,
            end=end
        )

        # Formato bonito español
        metrics["period"] = {
            "start": start,
            "end": end,
            "start_formatted": format_date(start, format="d MMMM y", locale="es"),
            "end_formatted": format_date(end, format="d MMMM y", locale="es"),
            "is_current_month": is_current_month, 
        }

        return metrics

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metrics = self.get_dashboard_metrics(self.request)
        context.update(metrics)

        historical_metrics = MetricsService.get_historical_metrics(self.request.user)

        client = self.request.user.client
        context["client"] = client if client else None
        context["period"] = {
            "start": metrics["period"]["start"],
            "end": metrics["period"]["end"],
            "start_formatted": metrics["period"]["start_formatted"],
            "end_formatted": metrics["period"]["end_formatted"],
            "is_current_month": metrics["period"]["is_current_month"]
        }
        context["historical_metrics"] = historical_metrics

        return context
