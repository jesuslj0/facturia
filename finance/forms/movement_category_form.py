from django import forms 
from finance.models import MovementCategory

class MovementCategoryForm(forms.ModelForm):
    class Meta:
        model = MovementCategory
        fields = ['name', 'type']

        labels = {
            "name": "Nombre",
            "type": "Tipo"
        }

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"})
        }