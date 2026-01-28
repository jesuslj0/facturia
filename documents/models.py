from django.db import models
from clients.models import Client
import os

class Document(models.Model):
    TYPE_CHOICES = [
        ("invoice", "Factura"),
        ("delivery", "Albarán"),
        ("other", "Otro"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("approved", "Aprobado"),
        ("needs_review", "Revisión"),
        ("error", "Error"),
    ]
    @property
    def extension(self):
        if not self.file:
            return ""
        return os.path.splitext(self.file.name)[1].lower()

    @property
    def is_pdf(self):
        if not self.file:
            return False
        return self.file.name.lower().endswith(".pdf")
    
    @property
    def is_image(self):
        if not self.file:
            return False
        return self.extension in [".jpg", ".jpeg", ".png", ".webp"]


    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="documents")
    external_id = models.CharField(max_length=255, unique=True)
    file = models.FileField(upload_to="documents/")
    original_name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    confidence = models.FloatField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    extracted_data = models.JSONField()
    provider_name = models.CharField(max_length=255, null=True, blank=True)
    provider_tax_id = models.CharField(max_length=50, null=True, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)