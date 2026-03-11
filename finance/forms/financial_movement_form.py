from django.forms import ModelForm
from finance.models import FinancialMovement, MovementCategory
from django import forms

class FinancialMovementForm(ModelForm):
    class Meta:
        model = FinancialMovement
        fields = ['category', 'amount', 'date', 'description']

        labels = {
            "category": "Categoría",
            "amount": "Importe (€)",
            "date": "Fecha del movimiento",
            "description": "Concepto"
        }

        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-input", "placeholder": "0.00"}),
            "date": forms.DateInput(attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)

        if client:
            categories = MovementCategory.objects.filter(
                client=client
            ).order_by("type", "name")
            self.fields['category'].queryset = categories
            self.fields['category'].label_from_instance = lambda obj: obj.name
        else:
            self.fields['category'].queryset = MovementCategory.objects.none()

