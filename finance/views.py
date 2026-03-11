from .models import MovementCategory, FinancialMovement
from django.views.generic import ListView, CreateView, DeleteView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .forms import FinancialMovementForm, MovementCategoryForm
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import HttpResponseRedirect

class FinancialMovementListView(LoginRequiredMixin, ListView):
    model = FinancialMovement
    template_name = "private/finance/movement_list.html"
    context_object_name = "movements"

    def get_queryset(self):
        return FinancialMovement.objects.filter(
            client=self.request.user.client
        )


class FinancialMovementCreateView(LoginRequiredMixin, CreateView):
    model = FinancialMovement
    template_name = "private/finance/movement_form.html"
    form_class = FinancialMovementForm
    success_url = "/finance/movements"

    def get_queryset(self):
        return FinancialMovement.objects.filter(
            client=self.request.user.client
        )
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["client"] = self.request.user.client
        return kwargs
    def form_valid(self, form):
        form.instance.client = self.request.user.client
        form.instance.created_by = self.request.user
        description = form.instance.description
        messages.success(self.request, f"Movimiento {description} creado correctamente")
        return super().form_valid(form)


class FinancialMovementUpdateView(LoginRequiredMixin, UpdateView):
    model = FinancialMovement
    form_class = FinancialMovementForm
    template_name = "private/finance/movement_form.html"
    success_url = reverse_lazy("finance:movements")

    def get_queryset(self):
        return FinancialMovement.objects.filter(
            client=self.request.user.client
        )
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["client"] = self.request.user.client
        return kwargs
    def form_valid(self, form):
        form.instance.client = self.request.user.client
        form.instance.created_by = self.request.user
        messages.success(self.request, f"Movimiento {self.object.description} actualizado correctamente")
        return super().form_valid(form)
    

class FinancialMovementDeleteView(LoginRequiredMixin, DeleteView):
    model = FinancialMovement
    template_name = "private/finance/movement_confirm_delete.html"
    success_url = reverse_lazy("finance:movements")

    def get_queryset(self):
        return FinancialMovement.objects.filter(
            client=self.request.user.client
        )
    
    def form_valid(self, form):
        messages.success(self.request, f"Movimiento {self.object.description} borrado correctamente")
        return super().form_valid(form)


class MovementCategoryListView(LoginRequiredMixin, ListView):
    model = MovementCategory
    template_name = "private/finance/category_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        categories = self.get_queryset()
        context["expense_categories"] = categories.filter(type="expense")
        context["income_categories"] = categories.filter(type="income")
        return context

class MovementCategoryCreateView(LoginRequiredMixin, CreateView):
    model = MovementCategory
    template_name = "private/finance/category_form.html"
    form_class = MovementCategoryForm
    success_url = "/finance/movements"

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        )
    
    def form_valid(self, form):
        form.instance.client = self.request.user.client
        messages.success(self.request, f"Categoría {self.object.name} creada correctamente")
        return super().form_valid(form)


class MovementCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = MovementCategory
    form_class = MovementCategoryForm
    template_name = "private/finance/category_form.html"
    success_url = reverse_lazy("finance:categories")

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        )
    
    def form_valid(self, form):
        form.instance.client = self.request.user.client
        messages.success(self.request, f"Categoría {self.object.name} actualizada correctamente")
        return super().form_valid(form)
    

class MovementCategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = MovementCategory
    template_name = "private/finance/category_confirm_delete.html"
    success_url = reverse_lazy("finance:categories")

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        )
    
    def form_valid(self, form):
        messages.success(self.request, f"Categoría {self.object.name} borrada correctamente")
        return super().form_valid(form)