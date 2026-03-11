from .models import MovementCategory, FinancialMovement
from django.views.generic import ListView, CreateView, DeleteView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .forms import FinancialMovementForm
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
        messages.success(self.request, "Movimiento creado correctamente")
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
        messages.success(self.request, "Movimiento actualizado correctamente")
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
        messages.success(self.request, "Movimiento borrado correctamente")
        return super().form_valid(form)


        
