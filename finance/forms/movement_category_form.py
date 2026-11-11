import re

from django import forms
from finance.models import MovementCategory

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
ICON_CLASSES = re.compile(r"^[a-z0-9 -]{0,60}$")
DEFAULT_COLOR = "#3b82f6"


class MovementCategoryForm(forms.ModelForm):
    class Meta:
        model = MovementCategory
        fields = ['name', 'type', 'color', 'icon']

        labels = {
            "name": "Nombre",
            "type": "Tipo",
            "color": "Color",
            "icon": "Icono",
        }

        help_texts = {
            "icon": "Clase de Font Awesome, por ejemplo «fa-solid fa-cart-shopping». Elige uno de la lista o escribe el tuyo.",
        }

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 100, "placeholder": "Ej. Material de oficina", "autofocus": True}),
            "type": forms.RadioSelect(),
            "color": forms.TextInput(attrs={"type": "color", "class": "color-picker"}),
            "icon": forms.TextInput(attrs={"class": "form-control", "placeholder": "fa-solid fa-tag", "autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (self.instance and self.instance.color):
            self.initial.setdefault("color", DEFAULT_COLOR)
        self.fields["type"].choices = list(MovementCategory._meta.get_field("type").choices)

    def clean_color(self):
        color = (self.cleaned_data.get("color") or "").strip()
        if color and not HEX_COLOR.match(color):
            raise forms.ValidationError("Usa un color hexadecimal, por ejemplo #3b82f6.")
        return color

    def clean_icon(self):
        icon = " ".join((self.cleaned_data.get("icon") or "").split()).lower()
        if not ICON_CLASSES.match(icon):
            raise forms.ValidationError("El icono solo puede contener letras minúsculas, números y guiones.")
        return icon
