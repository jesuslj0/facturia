from django.urls import path
from .views import (
    FinancialMovementListView, 
    FinancialMovementCreateView, 
    FinancialMovementUpdateView,
    FinancialMovementDeleteView,
    MovementCategoryCreateView,
    MovementCategoryListView,
    MovementCategoryUpdateView,
    MovementCategoryDeleteView
)

app_name = "finance"

urlpatterns = [
    path("movements", FinancialMovementListView.as_view(), name="movements"),
    path("movements/new", FinancialMovementCreateView.as_view(), name="new_movement"),
    path("movements/<int:pk>/edit", FinancialMovementUpdateView.as_view(), name="edit_movement"),
    path("movements/<int:pk>/delete", FinancialMovementDeleteView.as_view(), name="delete_movement"),
    path("categories", MovementCategoryListView.as_view(), name="categories"),
    path("categories/new", MovementCategoryCreateView.as_view(), name="new_category"),
    path("categories/<int:pk>/edit", MovementCategoryUpdateView.as_view(), name="edit_category"),
    path("categories/<int:pk>/delete", MovementCategoryDeleteView.as_view(), name="delete_category"),
]
