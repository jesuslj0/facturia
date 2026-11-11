from datetime import date
from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from clients.models import Client, CustomUser


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


class UserProfileForm(forms.ModelForm):
    """Datos personales del usuario autenticado. El usuario (login) y el cliente no se editan aquí."""

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'city', 'birth_date']
        labels = {'first_name': 'Nombre', 'last_name': 'Apellidos', 'email': 'Correo electrónico',
                  'city': 'Localidad', 'birth_date': 'Fecha de nacimiento'}
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
            'city': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'address-level2'}),
            'birth_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean_birth_date(self):
        born = self.cleaned_data.get('birth_date')
        if born and not (date(1900, 1, 1) <= born <= date.today()):
            raise forms.ValidationError('Introduce una fecha de nacimiento válida.')
        return born

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            raise forms.ValidationError('El correo electrónico es obligatorio.')
        return email


class UserPasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


class ClientInfoForm(forms.ModelForm):
    """Ficha de la empresa. Nombre y NIF/CIF no se editan aquí: determinan si un documento
    es compra o venta, así que se cambian solo desde administración."""

    class Meta:
        model = Client
        fields = ['founded_date', 'employee_count', 'industry', 'city', 'website', 'phone']
        widgets = {
            'founded_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}, format='%Y-%m-%d'),
            'employee_count': forms.NumberInput(attrs={'class': 'form-input', 'min': 0, 'max': 1000000}),
            'industry': forms.TextInput(attrs={'class': 'form-input'}),
            'city': forms.TextInput(attrs={'class': 'form-input'}),
            'website': forms.URLInput(attrs={'class': 'form-input', 'placeholder': 'https://'}),
            'phone': forms.TextInput(attrs={'class': 'form-input', 'type': 'tel'}),
        }

    def clean_founded_date(self):
        d = self.cleaned_data.get('founded_date')
        if d and not (date(1800, 1, 1) <= d <= date.today()):
            raise forms.ValidationError('Introduce una fecha de fundación válida.')
        return d

    def clean_employee_count(self):
        n = self.cleaned_data.get('employee_count')
        if n is not None and n > 1_000_000:
            raise forms.ValidationError('Número de empleados no válido.')
        return n
