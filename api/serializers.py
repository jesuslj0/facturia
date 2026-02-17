from rest_framework import serializers
from documents.models import Document

class DocumentIngestSerializer(serializers.ModelSerializer):
    # Archivo y datos básicos
    file = serializers.FileField(required=True)
    external_id = serializers.CharField(max_length=255)
    original_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=["invoice", "delivery", "corrected_invoice"])

    # Datos del proveedor / Company
    provider_name = serializers.CharField(max_length=255, required=True)
    provider_tax_id = serializers.CharField(max_length=50, required=True)
    provider_type = serializers.ChoiceField(choices=[("provider", "Provider")], default="provider")

    # Datos de la factura
    invoice_number = serializers.CharField(max_length=255, required=False, allow_blank=True)
    issue_date = serializers.DateField(required=False)
    base_amount = serializers.FloatField()
    tax_amount = serializers.FloatField()
    tax_percentage = serializers.FloatField(min_value=0.0, max_value=100.0)
    total_amount = serializers.FloatField()

    # Confianza / revisión
    confidence = serializers.JSONField(default=dict)

    def validate_external_id(self, value):
        if Document.objects.filter(external_id=value).exists():
            raise serializers.ValidationError("Document already ingested")
        return value

    class Meta:
        model = Document
        fields = [
            "file",
            "external_id",
            "original_name",
            "document_type",
            "provider_name",
            "provider_tax_id",
            "provider_type",
            "invoice_number",
            "issue_date",
            "base_amount",
            "tax_amount",
            "tax_percentage",
            "total_amount",
            "confidence",
        ]



class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = "__all__"


from rest_framework import serializers
from documents.models import Document


class DocumentListSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "original_name",
            "document_type",
            "status",
            "confidence",
            "total_amount",
            "created_at",
            "file_url",
            "invoice_number",
        ]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None
