from django.shortcuts import redirect, get_object_or_404
from documents.models import Document
from clients.models import ClientUser
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from datetime import datetime


# Create your views here.
def get_filtered_documents(request):
    qs = Document.objects.filter(
            client__clientuser__user=request.user
        )
    q = request.GET.get("q")
    company = request.GET.get("company")
    status = request.GET.get("status")
    review = request.GET.get("review")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    document_type = request.GET.get("document_type")
    flow = request.GET.get("flow")

    if q:
        qs = qs.filter(
            Q(original_name__icontains=q) | Q(company__name__icontains=q)
        )

    if company:
        qs = qs.filter(company__name=company)
    if status:
        qs = qs.filter(status=status)

    if review:
        qs = qs.filter(review_level=review)
    
    if date_from:
        qs = qs.filter(issue_date__gte=date_from)

    if date_to:
        qs = qs.filter(
            issue_date__lte=datetime.combine(
                datetime.fromisoformat(date_to).date(), 
                datetime.max.time()
            )
        )

    if document_type: 
        qs = qs.filter(document_type=document_type)

    if flow:
        qs = qs.filter(flow=flow)
        
    return qs.order_by("-issue_date", "-created_at")

from documents.models import Company
class DocumentListView(LoginRequiredMixin, ListView): 
    model = Document
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
    model = Document
    template_name = "public/documents/document_detail.html"

    def get_queryset(self):
        return Document.objects.filter(
            client__clientuser__user=self.request.user
        )
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action")

        # --- Aprobar ---
        if action == "approve" and self.object.status == "pending":
            return approve_document(request, self.object)

        # --- Rechazar ---
        if action == "reject" and self.object.status == "pending":
            return reject_document(request, self.object)

        # --- Guardar cambios ---
        if action == "save":
            return save_document(request, self.object)

        # Si no hay acción reconocida, redirigir
        messages.warning(request, "Acción no reconocida.")
        return redirect("documents:detail", pk=self.object.pk)
    

def approve_document(request, document):
    document.status = "approved"
    document.is_auto_approved = False
    document.review_level = "manual"
    document.reviewed_by = request.user
    document.approved_at = timezone.now()
    document.save()
    messages.success(request, "El documento ha sido aprobado.")
    return redirect("documents:detail", pk=document.pk)


def reject_document(request, document):
    document.is_auto_approved = False   
    document.status = "rejected"
    document.review_level = "manual"
    document.reviewed_by = request.user
    document.rejected_by = request.user
    document.save()
    messages.success(request, "El documento ha sido rechazado.")
    return redirect("documents:detail", pk=document.pk)

from decimal import Decimal, InvalidOperation
def save_document(request, document):
    if document.status == "rejected":
        messages.error(request, "El documento ha sido rechazado.")
        return redirect("documents:detail", pk=document.pk)

    # Obtener datos del formulario
    issue_date = request.POST.get("issue_date")
    base_amount = request.POST.get("base_amount")
    tax_percentage = request.POST.get("tax_percentage")
    tax_amount = request.POST.get("tax_amount")
    total_amount = request.POST.get("total_amount")
    document_number = request.POST.get("document_number")
    flow = request.POST.get("flow")

    # Validar importes
    try:
        new_base = Decimal(base_amount) if base_amount else None
        new_tax_percentage = Decimal(tax_percentage) if tax_percentage else None
        new_tax_amount = Decimal(tax_amount) if tax_amount else None
        new_total = Decimal(total_amount) if total_amount else None
    except InvalidOperation:
        messages.error(request, "Importe inválido en uno de los campos.")
        return redirect("documents:detail", pk=document.pk)

    # Asignar solo si pasó validación
    if document_number:
        document.invoice_number = document_number

    if issue_date:
        document.issue_date = issue_date

    if new_base is not None:
        document.base_amount = new_base

    if new_tax_percentage is not None:
        document.tax_percentage = new_tax_percentage

    if new_tax_amount is not None:
        document.tax_amount = new_tax_amount

    if new_total is not None:
        document.total_amount = new_total

    if flow:
        document.flow = flow

    # Marcar como revisado manualmente
    document.review_level = "manual"
    document.is_auto_approved = False
    document.reviewed_by = request.user
    document.edited_at = timezone.now()
    document.save()
    messages.success(request, "Cambios guardados correctamente.")
    return redirect("documents:detail", pk=document.pk)

class DashboardView(LoginRequiredMixin,TemplateView):
    template_name="public/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = Document.objects.filter(status="pending", client__clientuser__user=self.request.user)

        pending_count = qs.count()
        required_count = qs.filter(review_level="required").count() or 0
        recommended_count = qs.filter(review_level="recommended").count() or 0
        client = ClientUser.objects.filter(user=self.request.user).first().client 
        client = client if client else None

        context = {
            "pending_documents": qs.order_by("-created_at")[:5],
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
    model = Document

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["documents"] = get_filtered_documents(self.request)
        return context

from .services import MetricsService

class MetricsDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "private/metrics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        metrics = MetricsService.get_user_metrics(self.request.user)

        context.update(metrics)
        context["client"] = ClientUser.objects.filter(user=self.request.user).first().client
        return context