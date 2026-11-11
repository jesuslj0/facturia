from django import forms
from documents.models import Document, Company

class CommaDecimalField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip()
            if "," in value:
                value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)


class DocumentRectificationForm(forms.ModelForm):
    base_amount = CommaDecimalField(required=False, max_digits=10, decimal_places=2)
    tax_amount = CommaDecimalField(required=False, max_digits=10, decimal_places=2)
    tax_percentage = CommaDecimalField(required=False, max_digits=10, decimal_places=2)
    total_amount = CommaDecimalField(required=False, max_digits=10, decimal_places=2)
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
