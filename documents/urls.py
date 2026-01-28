from django.urls import path 
from documents.views import DocumentListView, DocumentDetailView

app_name = "documents"

urlpatterns = [
    path("", DocumentListView.as_view(), name="list"),
    path("<int:pk>/", DocumentDetailView.as_view(), name="detail"),
    # path("<int:pk>/approve/", approve_document, name="approve"),
    # path("<int:pk>/mark-review/", mark_for_review, name="mark_review"),
]
