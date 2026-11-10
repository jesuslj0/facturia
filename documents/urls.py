from django.urls import path 
from documents.views import (
    DocumentListView, DocumentDetailView, DocumentExportView,
    DocumentExportPreviewView, DocumentRectifyView, DocumentPDFPreviewView,
    DocumentFileView, DocumentUploadView,
)

app_name = "documents"

urlpatterns = [
    path("", DocumentListView.as_view(), name="list"),
    path("upload/", DocumentUploadView.as_view(), name="upload"),
    path("<int:pk>/", DocumentDetailView.as_view(), name="detail"),
    path("<int:pk>/file/", DocumentFileView.as_view(), name="file"),
    path("<int:pk>/rectify", DocumentRectifyView.as_view(), name="rectify"),
    path("export/", DocumentExportView.as_view(), name="export"),
    path("export/preview/", DocumentExportPreviewView.as_view(), name="export_preview"),
    path("pdf_preview/", DocumentPDFPreviewView.as_view(), name="pdf_preview"),
]
