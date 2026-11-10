from django import forms

MAX_FILES_PER_UPLOAD = 20


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data if d]
        return [single(data, initial)] if data else []


class DocumentUploadForm(forms.Form):
    """`files`: selector/arrastrar; `photos`: cámara del móvil (origen «mobile»)."""
    files = MultipleFileField(required=False)
    photos = MultipleFileField(required=False)

    def clean(self):
        cleaned = super().clean()
        total = len(cleaned.get("files") or []) + len(cleaned.get("photos") or [])
        if total == 0:
            raise forms.ValidationError("Selecciona al menos un archivo.")
        if total > MAX_FILES_PER_UPLOAD:
            raise forms.ValidationError(f"Máximo {MAX_FILES_PER_UPLOAD} archivos por subida.")
        return cleaned
