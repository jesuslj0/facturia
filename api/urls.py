from .views import DocumentIngestAPIView
from django.urls import path

app_name = 'api'

urlpatterns = [
    path("v1/documents/ingest", DocumentIngestAPIView.as_view()),
]
