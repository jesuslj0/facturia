from django import forms
from documents.models import Document, Company

class DocumentRectificationForm(forms.ModelForm):
    rectification_reason = forms.CharField(required=True, label="Motivo de la rectificación")
    company = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        required=False,
        label="Empresa (opcional)",
        help_text="Selecciona una empresa existente si quieres corregirla"
    )

    class Meta:
        model = Document
        fields = [
            "base_amount", "tax_amount", "tax_percentage", "total_amount",
            "issue_date", "document_number", "company", "rectification_reason"
        ]

    def clean_base_amount(self):
        val = self.cleaned_data["base_amount"]
        if isinstance(val, str):
            val = val.replace(",", ".")
        return val
    def clean_tax_amount(self):
        val = self.cleaned_data["tax_amount"]
        if isinstance(val, str):
            val = val.replace(",", ".")
        return val
    def clean_tax_percentage(self):
        val = self.cleaned_data["tax_percentage"]
        if isinstance(val, str):
            val = val.replace(",", ".")
        return val
    def clean_total_amount(self):
        val = self.cleaned_data["total_amount"]
        if isinstance(val, str):
            val = val.replace(",", ".")
        return val
