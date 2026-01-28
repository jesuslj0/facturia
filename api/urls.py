from .views import DocumentIngestAPIView, DocumentListAPIView
from django.urls import path

app_name = "api"

urlpatterns = [
    path("v1/documents/ingest", DocumentIngestAPIView.as_view()),
    path("v1/documents/", DocumentListAPIView.as_view(), name="api_documents_list")
]
