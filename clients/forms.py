from django import forms
from clients.models import Client


class ClientProfileForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['logo', 'primary_color']

        labels = {
            'logo': 'Logotipo',
            'primary_color': 'Color principal',
        }

        widgets = {
            'logo': forms.FileInput(attrs={
                'class': 'form-input',
                'accept': 'image/*',
                'id': 'logo-input',
            }),
            'primary_color': forms.TextInput(attrs={
                'class': 'form-input color-input',
                'type': 'color',
                'id': 'primary-color-input',
            }),
        }
