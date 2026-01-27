from rest_framework import serializers
from documents.models import Document

class DocumentIngestSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=255)
    original_name = serializers.CharField(max_length=255)
    document_type = serializers.ChoiceField(choices=["invoice", "delivery", "other"])
    confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    extracted_data = serializers.JSONField()

    def validate(self, data):
        if Document.objects.filter(external_id=data["external_id"]).exists():
            raise serializers.ValidationError("Document already ingested")
        return data

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = "__all__"

