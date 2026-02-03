from rest_framework import serializers
from documents.models import Document

class DocumentIngestSerializer(serializers.ModelSerializer):
    file = serializers.FileField(required=True)
    external_id = serializers.CharField(max_length=255)
    original_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=["invoice", "delivery", "other"])
    confidence = serializers.JSONField(default=dict)
    extracted_data = serializers.JSONField()
    base_amount = serializers.FloatField()
    tax_amount = serializers.FloatField()
    tax_percentage = serializers.FloatField(min_value=0.0, max_value=100.0)
    total_amount = serializers.FloatField()

    def validate(self, data):
        if Document.objects.filter(external_id=data["external_id"]).exists():
            raise serializers.ValidationError("Document already ingested")
        return data
    
    class Meta: 
        model = Document
        fields = ['file', 'external_id', 'original_name', 'document_type', 'confidence', 
                  'extracted_data', 'base_amount', 'tax_amount', 'tax_percentage', 'total_amount']

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
        ]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None
