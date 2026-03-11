from django.urls import path
from .views import (
    FinancialMovementListView, 
    FinancialMovementCreateView, 
    FinancialMovementUpdateView,
    FinancialMovementDeleteView
)

app_name = "finance"

urlpatterns = [
    path("movements", FinancialMovementListView.as_view(), name="movements"),
    path("movements/new", FinancialMovementCreateView.as_view(), name="new_movement"),
    path("movements/<int:pk>/edit", FinancialMovementUpdateView.as_view(), name="edit_movement"),
    path("movements/<int:pk>/delete", FinancialMovementDeleteView.as_view(), name="delete_movement"),
]
