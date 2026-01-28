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
    

class DocumentDetailView(LoginRequiredMixin, DetailView):
    model = Document
    template_name = "documents/document_detail.html"

    def get_queryset(self):
        return Document.objects.filter(
            client__clientuser__user=self.request.user
        )