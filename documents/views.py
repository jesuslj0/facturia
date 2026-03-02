from django.shortcuts import redirect, get_object_or_404
from .models import Document
from clients.models import ClientUser
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from datetime import datetime
from .selectors import DocumentSelector
from .services import DocumentService

def get_filtered_documents(request):
    doc_status = request.GET.get("doc_status")
    query = request.GET.get("q")
    company = request.GET.get("company")
    status = request.GET.get("status")
    review_level = request.GET.get("review_level")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    document_type = request.GET.get("document_type")
    flow = request.GET.get("flow")

    filters = {}

    if doc_status:
        filters["doc_status"] = doc_status
    if query:
        filters["query"] = query
    if company:
        filters["company"] = company
    if status:
        filters["status"] = status
    if review_level:
        filters["review_level"] = review_level
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if document_type:
        filters["document_type"] = document_type
    if flow:
        filters["flow"] = flow

    client = ClientUser.objects.get(user=request.user).client
    return DocumentSelector.filtered(client, filters)

from documents.models import Company
class DocumentListView(LoginRequiredMixin, ListView): 
    template_name = "public/documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 20
    
    def get_queryset(self):
        return get_filtered_documents(self.request)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        page_obj = context.get("page_obj")
        first_doc = page_obj.object_list.first() if page_obj else None

        context["client"] = first_doc.client if first_doc else None
        context["document_types"] = Document.TYPE_CHOICES
        context["companies"] = Company.objects.filter(
            client__clientuser__user=self.request.user
        ).order_by("name")

        # 🔹 Querystring sin page
        querydict = self.request.GET.copy()
        querydict.pop("page", None)
        context["querystring"] = querydict.urlencode()
        return context

    

class DocumentDetailView(LoginRequiredMixin, DetailView):
    template_name = "public/documents/document_detail.html"
    context_object_name = "document"

    def get_queryset(self):
        client = ClientUser.objects.get(user=self.request.user).client
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
    template_name="public/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        client = ClientUser.objects.filter(user=self.request.user).first().client
        client = client if client else None

        qs = DocumentSelector.pending(client)

        pending_count = qs.count()
        required_count = qs.filter(review_level="required").count() or 0
        recommended_count = qs.filter(review_level="recommended").count() or 0

        context = {
            "pending_documents": qs.order_by("-created_at")[:10],
            "pending_count": pending_count,
            "required_review_count": required_count,
            "recommended_review_count": recommended_count,
            "client": client
        }

        return context
    
from .utils import export_to_csv, export_to_excel
class DocumentExportView(LoginRequiredMixin, ListView):
    def get(self, request):
        qs = get_filtered_documents(request)
        return export_to_csv(qs)
    
    def post(self,request):
        ids = request.POST.getlist("ids")
        fmt = request.POST.get("format", "csv")

        qs = Document.objects.filter(
            id__in=ids, 
            client__clientuser__user=request.user
        )

        if fmt == "xlsx":
            return export_to_excel(qs)
        return export_to_csv(qs)
    
class DocumentExportPreviewView(LoginRequiredMixin, ListView):
    template_name = "public/documents/document_export_preview.html"

    def get_queryset(self):
        return get_filtered_documents(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["documents"] = get_filtered_documents(self.request)
        return context

from .services import MetricsService
from babel.dates import format_date
from django.utils import timezone
from calendar import monthrange

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
            "is_current_month": is_current_month
        }

        return metrics

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metrics = self.get_dashboard_metrics(self.request)
        context.update(metrics)

        historical_metrics = MetricsService.get_historical_metrics(self.request.user)

        client = ClientUser.objects.filter(user=self.request.user).first().client
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