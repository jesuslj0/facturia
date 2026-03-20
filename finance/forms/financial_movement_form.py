from django.forms import ModelForm
from finance.models import FinancialMovement, MovementCategory
from django import forms

class FinancialMovementForm(ModelForm):
    class Meta:
        model = FinancialMovement
        fields = ['category', 'amount', 'date', 'description', 'receipt', 'payment_method', 'is_recurrent', 'is_active', 'is_reconciled']

        labels = {
            "category": "Categoría",
            "amount": "Importe (€)",
            "date": "Fecha del movimiento",
            "description": "Concepto",
            "receipt": "Recibo o justificante",
            "payment_method": "Metodo de pago",
            "is_recurrent": "Movimiento recurrente",
            "is_active": "Movimiento activo",
            "is_reconciled": "Movimiento conciliado",
        }

        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
            "receipt": forms.FileInput(attrs={
                "class": "form-input",
                "accept": "image/*, application/pdf",
            }),
            "payment_method": forms.Select(attrs={"class": "form-select"}),
            "is_recurrent": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "is_reconciled": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        }

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)

        if client:
            categories = MovementCategory.objects.filter(
                client=client
            ).order_by("type", "name")
            self.fields['category'].queryset = categories
            self.fields['category'].label_from_instance = lambda obj: f"{obj.name} ({obj.get_type_display()})"
        else:
            self.fields['category'].queryset = MovementCategory.objects.none()

