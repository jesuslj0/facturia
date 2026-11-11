from .models import MovementCategory, FinancialMovement
from django.views.generic import ListView, CreateView, DeleteView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .forms import FinancialMovementForm, MovementCategoryForm
from django.db.models import ProtectedError
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.http import HttpResponseRedirect
from .filters import get_filtered_movements
from django.shortcuts import get_object_or_404
from django.views import View
from billing_ai.storage import private_file_response
from billing_ai import listing
from django.db.models import Count, Q, Sum

class FinancialMovementListView(LoginRequiredMixin, ListView):
    model = FinancialMovement
    template_name = "private/finance/movement_list.html"
    context_object_name = "movements"
    paginate_by = 25

    def get_queryset(self):
        return get_filtered_movements(
            self.request,
            base_qs=FinancialMovement.objects.filter(
                client=self.request.user.client
            ).select_related("category")
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        categories = MovementCategory.objects.filter(client=request.user.client)
        context["categories"] = categories
        context["payment_methods"] = FinancialMovement.PAYMENT_CHOICES

        # Totales del conjunto filtrado (no solo de la página visible)
        totals = self.object_list.aggregate(
            income=Sum("amount", filter=Q(movement_type="income")),
            expense=Sum("amount", filter=Q(movement_type="expense")),
        )
        income, expense = totals["income"] or 0, totals["expense"] or 0
        context["totals"] = {"income": income, "expense": expense, "balance": income - expense}

        spec = [
            ("q", "Búsqueda", None, False),
            ("category", "Categoría", {str(c.pk): c.name for c in categories}, True),
            ("method", "Método", dict(FinancialMovement.PAYMENT_CHOICES), True),
            ("start", "Desde", listing.pretty, True),
            ("end", "Hasta", listing.pretty, True),
            ("min_amount", "Importe mín.", lambda v: f"{v} €", True),
            ("max_amount", "Importe máx.", lambda v: f"{v} €", True),
            ("is_reconciled", "Estado", lambda v: "Conciliados", True),
            ("has_receipt", "Recibo", lambda v: "Con recibo", True),
        ]
        filters = listing.active_filters(request, spec)
        page_obj = context.get("page_obj")
        context["active_filters"] = filters
        context["panel_filter_count"] = sum(1 for f in filters if f["in_panel"])
        context["page_numbers"] = listing.page_window(page_obj) if page_obj and page_obj.paginator.num_pages > 1 else []
        context["querystring"] = listing.qs_without(request)
        return context


class FinancialMovementCreateView(LoginRequiredMixin, CreateView):
    model = FinancialMovement
    template_name = "private/finance/movement_form.html"
    form_class = FinancialMovementForm
    success_url = "/finance/movements"

    def get_initial(self):
        initial = super().get_initial()
        category_id = self.request.GET.get('category')
        if category_id:
            try:
                initial['category'] = MovementCategory.objects.get(pk=category_id)
            except MovementCategory.DoesNotExist:
                pass
        return initial

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

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        ).annotate(movement_count=Count("movements"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        categories = list(self.get_queryset())
        groups = []
        for key, label, icon, always in (
            ("expense", "Gastos", "fa-solid fa-arrow-trend-down", True),
            ("income", "Ingresos", "fa-solid fa-arrow-trend-up", True),
            ("investment", "Inversión", "fa-solid fa-piggy-bank", False),
            ("loan", "Préstamos", "fa-solid fa-hand-holding-dollar", False),
        ):
            items = [c for c in categories if c.type == key]
            if items or always:
                groups.append({"key": key, "label": label, "icon": icon, "items": items,
                               "movements": sum(c.movement_count for c in items)})
        context["groups"] = groups
        context["total_categories"] = len(categories)
        # compatibilidad con plantillas/tests previos
        context["expense_categories"] = [c for c in categories if c.type == "expense"]
        context["income_categories"] = [c for c in categories if c.type == "income"]
        context["investment_categories"] = [c for c in categories if c.type == "investment"]
        context["loan_categories"] = [c for c in categories if c.type == "loan"]
        return context

class MovementCategoryCreateView(LoginRequiredMixin, CreateView):
    model = MovementCategory
    template_name = "private/finance/category_form.html"
    form_class = MovementCategoryForm
    success_url = reverse_lazy("finance:categories")

    def get_initial(self):
        initial = super().get_initial()
        kind = self.request.GET.get("type")
        if kind in dict(MovementCategory._meta.get_field("type").choices):
            initial["type"] = kind
        return initial

    def get_queryset(self):
        return MovementCategory.objects.filter(
            client=self.request.user.client
        )
    
    def form_valid(self, form):
        form.instance.client = self.request.user.client
        cat_name = form.instance.name
        messages.success(self.request, f"Categoría {cat_name} creada correctamente")
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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement_count"] = self.object.movements.count()
        return context

    def form_valid(self, form):
        name = self.object.name
        try:
            response = super().form_valid(form)
        except ProtectedError:
            # Una categoría con movimientos no se puede borrar: habría que reasignarlos antes.
            messages.error(self.request, f"No se puede borrar «{name}»: tiene movimientos asociados.")
            return HttpResponseRedirect(reverse("finance:edit_category", kwargs={"pk": self.object.pk}))
        messages.success(self.request, f"Categoría {name} borrada correctamente")
        return response

class FinancialMovementReceiptView(LoginRequiredMixin, View):
    def get(self, request, pk):
        movement = get_object_or_404(
            FinancialMovement, pk=pk, client=request.user.client
        )
        return private_file_response(movement.receipt)
