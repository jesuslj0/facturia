from django.shortcuts import redirect, get_object_or_404
from documents.models import Document
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView
from django.contrib import messages
from django.utils.timezone import now

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
    

def approve_document(request, pk):
    document = get_object_or_404(Document, pk=pk)
    document.status = "approved"
    document.reviewed_at = now()
    document.save()
    # Mensaje de éxito
    msg = "El documento ha sido aprobado."
    messages.success(request, msg) 
    print(request._messages)   
                     
    # Redirige a la página de detalle del documento
    return redirect("documents:detail", pk=document.pk)


def reject_document(request, pk):
    document = get_object_or_404(Document, pk=pk)
    document.status = "rejected"
    document.reviewed_at = now()
    document.save()
    messages.error(request, "El documento ha sido rechazado.")  # Mensaje de error
    # Redirige a la página de detalle del documento
    return redirect("documents:detail", pk=document.pk)