from django.shortcuts import redirect, get_object_or_404
from documents.models import Document
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, TemplateView
from django.contrib import messages
from django.utils import timezone

# Create your views here.
class DocumentListView(LoginRequiredMixin, ListView): 
    model = Document
    template_name = "documents/document_list.html"
    context_object_name = "documents"
    
    def get_queryset(self):
        return Document.objects.filter(
            client__clientuser__user=self.request.user
        ).order_by("-created_at")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        first_doc = self.get_queryset().first()
        context["client"] = first_doc.client if first_doc else None
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
        provider_name = request.POST.get("provider_name")
        provider_tax_id = request.POST.get("provider_tax_id")
        issue_date = request.POST.get("issue_date")
        base_amount = request.POST.get("base_amount")
        tax_percentage = request.POST.get("tax_percentage")
        tax_amount = request.POST.get("tax_amount")
        total_amount = request.POST.get("total_amount")

        # Validaciones simples (puedes mejorar)
        if provider_name:
            self.object.provider_name = provider_name.strip()
        if provider_tax_id:
            self.object.provider_tax_id = provider_tax_id.strip()
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
        self.object.review_level = "auto"

        # Marcar fecha de revisión
        self.object.reviewed_at = timezone.now()

        # Guardar cambios
        self.object.save()

        # Redirigir de nuevo a la misma página
        return redirect("documents:detail", pk=self.object.pk)
    

def approve_document(request, pk):
    if request.method == "POST":
        document = get_object_or_404(Document, pk=pk)
        document.status = "approved"
        document.reviewed_at = timezone.now()
        document.save()
        messages.success(request, "El documento ha sido aprobado.")
        return redirect("documents:detail", pk=document.pk)
    else:
        return redirect("documents:detail", pk=pk)


def reject_document(request, pk):
    if request.method == "POST":
        document = get_object_or_404(Document, pk=pk)
        document.status = "rejected"
        document.reviewed_at = timezone.now()
        document.save()
        messages.success(request, "El documento ha sido rechazado.")
        return redirect("documents:detail", pk=document.pk)
    else:
        return redirect("documents:detail", pk=pk)


class DashboardView(LoginRequiredMixin,TemplateView):
    template_name="dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = Document.objects.filter(status="pending")

        pending_count = qs.count()
        required_count = qs.filter(review_level="required").count()
        recommended_count = qs.filter(review_level="recommended").count()

        context = {
            "pending_documents": qs.order_by("-created_at")[:5],
            "pending_count": pending_count,
            "required_review_count": required_count,
            "recommended_review_count": recommended_count
        }

        return context
    

