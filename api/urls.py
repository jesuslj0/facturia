from .views import DocumentIngestAPIView, DocumentListAPIView
from django.urls import path
from .views import MetricsDashboardView

app_name = "api"

urlpatterns = [
    path("v1/documents/ingest", DocumentIngestAPIView.as_view()),
    path("v1/documents/", DocumentListAPIView.as_view(), name="api_documents_list"),
    path("v1/metrics/dashboard/", MetricsDashboardView.as_view(), name="dashboard_metrics"),
]
