from django.urls import path 
from documents.views import (
    DocumentListView, DocumentDetailView, approve_document, 
    reject_document, DocumentExportView, DocumentExportPreviewView,
    DocumentRectifyView, DocumentPDFPreviewView
)
from .utils import render_pdf_preview

app_name = "documents"

urlpatterns = [
    path("", DocumentListView.as_view(), name="list"),
    path("<int:pk>/", DocumentDetailView.as_view(), name="detail"),
    path("<int:pk>/approve/", approve_document, name="approve"),
    path("<int:pk>/reject/", reject_document, name="reject"),
    path("<int:pk>/rectify", DocumentRectifyView.as_view(), name="rectify"),
    path("export/", DocumentExportView.as_view(), name="export"),
    path("export/preview/", DocumentExportPreviewView.as_view(), name="export_preview"),
    path("pdf_preview/", DocumentPDFPreviewView.as_view(), name="pdf_preview"),
]
