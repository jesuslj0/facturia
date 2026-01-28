from django.shortcuts import render
from documents.models import Document
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView

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