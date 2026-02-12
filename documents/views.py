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
    status = request.GET.get("status")
    review = request.GET.get("review")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    document_type = request.GET.get("document_type")

    if q:
        qs = qs.filter(
            Q(original_name__icontains=q) | Q(provider_name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    if review:
        qs = qs.filter(review_level=review)
    
    if date_from:
        qs = qs.filter(created_at__gte=date_from)

    if date_to:
        qs = qs.filter(
            issue_date__lte=datetime.combine(
                datetime.fromisoformat(date_to).date(), 
                datetime.max.time()
            )
        )

    if document_type: 
        qs = qs.filter(document_type=document_type)
        
    return qs.order_by("-issue_date", "-created_at")

class DocumentListView(LoginRequiredMixin, ListView): 
    model = Document
    template_name = "documents/document_list.html"
    context_object_name = "documents"
    
    def get_queryset(self):
        return get_filtered_documents(self.request)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        first_doc = self.get_queryset().first()
        context["client"] = first_doc.client if first_doc else None
        context["document_types"] = Document.TYPE_CHOICES
        return context
    

class DocumentDetailView(LoginRequiredMixin, DetailView):
    model = Document
    template_name = "documents/document_detail.html"

    def get_queryset(self):
        return Document.objects.filter(
            client__clientuser__user=self.request.user
        )
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Solo editar si requiere revisión
        if self.object.review_level not in ["required", "recommended"]:
            return redirect("documents:detail", pk=self.object.pk)

        # Obtener datos del formulario
        # provider_name = request.POST.get("provider_name")
        # provider_tax_id = request.POST.get("provider_tax_id")
        issue_date = request.POST.get("issue_date")
        base_amount = request.POST.get("base_amount")
        tax_percentage = request.POST.get("tax_percentage")
        tax_amount = request.POST.get("tax_amount")
        total_amount = request.POST.get("total_amount")
        invoice_number = request.POST.get("invoice_number")

        # Validaciones simples (puedes mejorar)
        # if provider_name:
        #     self.object.provider_name = provider_name.strip()
        # if provider_tax_id:
        #     self.object.provider_tax_id = provider_tax_id.strip()
        if invoice_number: 
            self.object.invoice_number = invoice_number
        if issue_date:
            self.object.issue_date = issue_date
        if base_amount:
            self.object.base_amount = float(base_amount)
        if tax_percentage:
            self.object.tax_percentage = float(tax_percentage)
        if tax_amount:
            self.object.tax_amount = float(tax_amount)
        if total_amount:
            self.object.total_amount = float(total_amount)

        # Marcar como revisado
        self.object.review_level = "manual"

        # Marcar fecha de revisión
        self.object.edited_at = timezone.now()

        # Guardar cambios
        self.object.save()

        # Redirigir de nuevo a la misma página
        return redirect("documents:detail", pk=self.object.pk)
    

def approve_document(request, pk):
    if request.method == "POST":
        document = get_object_or_404(Document, pk=pk)
        document.status = "approved"
        document.review_level = "manual"
        document.approved_at = timezone.now()
        document.save()
        messages.success(request, "El documento ha sido aprobado.")
        return redirect("documents:detail", pk=document.pk)
    else:
        return redirect("documents:detail", pk=pk)


def reject_document(request, pk):
    if request.method == "POST":
        document = get_object_or_404(Document, pk=pk)
        document.status = "rejected"
        document.review_level = "manual"
        document.edited_at = timezone.now()
        document.save()
        messages.success(request, "El documento ha sido rechazado.")
        return redirect("documents:detail", pk=document.pk)
    else:
        return redirect("documents:detail", pk=pk)


class DashboardView(LoginRequiredMixin,TemplateView):
    template_name="dashboard.html"

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
    template_name = "documents/document_export_preview.html"
    model = Document

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["documents"] = get_filtered_documents(self.request)
        return context