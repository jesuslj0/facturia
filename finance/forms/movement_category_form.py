from django import forms 
from finance.models import MovementCategory

class MovementCategoryForm(forms.ModelForm):
    class Meta:
        model = MovementCategory
        fields = ['name', 'type', 'color', 'icon']

        labels = {
            "name": "Nombre",
            "type": "Tipo",
            "color": "Color de categoria",
            "icon": "Icono de categoria"
        }

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "color": forms.TextInput(attrs={"class": "form-control"}),
            "icon": forms.TextInput(attrs={"class": "form-control"})
        }