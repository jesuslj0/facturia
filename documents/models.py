from django.db import models
from clients.models import Client
import os

from django.contrib.auth import get_user_model
User = get_user_model()

class Company(models.Model):
    TYPE_CHOICES = [
        ("provider", "Proveedor"),
        ("customer", "Cliente"),
    ]

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, 
        related_name="companies"
    )
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client", "tax_id"],
                name="unique_company_per_client_tax_id",
                condition=models.Q(tax_id__isnull=False),
            ),
        ]

        indexes = [
            models.Index(fields=["client", "tax_id"]),
            models.Index(fields=["client", "name"]),
        ]
    
    def save(self, *args, **kwargs):
        if self.tax_id:
            self.tax_id = (
                self.tax_id.replace(" ", "").replace("-", "").upper(
                    
                )
            )
        if self.name: 
            self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
    

class ActiveDocumentManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False)

class Document(models.Model):
    TYPE_CHOICES = [
        ("invoice", "Factura"),
        ("delivery", "Albarán"),
        ("corrected_invoice", "Abono")
    ]

    TOTAL_SOURCE_CHOICES = [
        ('explicit', 'Explicit'),
        ('base_tax', 'Base + Tax'),
        ('base', 'Base only'),
        ('unknown', 'Unknown'),
    ]

    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("approved", "Aprobado"),
        ("rejected", "Rechazado"),
    ]

    REVIEW_LEVEL_CHOICES = [
        ('auto', 'Aprobado automáticamente'),
        ('manual', 'Manual'),
        ('recommended', 'Revisión recomendada'),
        ('required', 'Revisión requerida'),
    ]

    FLOW_CHOICES = [
        ("in", "Compra"),
        ("out", "Venta"),
        ("unknown", "Por revisar"),
    ]

    FLOW_SOURCE_CHOICES = [
        ("auto", "Automático"),
        ("manual", "Manual"),
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
    
    @property
    def display_review_level(self):
        if self.status == "rejected" or (self.status == "approved" and self.approved_at):
            return "Manual"
        if self.status == "approved" and not self.approved_at:
            return "Auto"
        if self.review_level == "manual":
            return "Manual"
        if self.review_level == "auto":
            return "Auto"
        if self.review_level == "recommended":
            return "Revisión recomendada"
        if self.review_level == "required":
            return "Revisión obligatoria"
        return "-"

    @property 
    def is_editable(self):
        return self.status in ["pending"]

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, 
        related_name="documents"
    )
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, 
        related_name="documents",
        null=True
    )

    @property
    def status_message(self):
        if self.status == "rejected":
            return f"El documento ha sido rechazado por {self.rejected_by}"
        if self.approved_at:
            return f"Documento aprobado el {self.approved_at.strftime('%d-%m-%Y')}"
        if self.is_auto_approved:
            return "Documento aprobado automáticamente"
        if self.edited_at:
            return f"Documento editado manualmente el {self.edited_at.strftime('%d-%m-%Y')}"
        return "Documento pendiente de revisión"


    external_id = models.CharField(max_length=255, unique=True)
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/")
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    document_number = models.CharField(max_length=255, null=True, blank=True)
    confidence = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    review_level = models.CharField(max_length=20, choices=REVIEW_LEVEL_CHOICES, default='required')
    issue_date = models.DateField(null=True, blank=True)
    base_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_source = models.CharField(max_length=10, choices=TOTAL_SOURCE_CHOICES, default="unknown")
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        related_name="approved_documents",
        null=True
    )
    rejected_at = models.DateTimeField(blank=True, null=True)
    flow = models.CharField(max_length=20, choices=FLOW_CHOICES, default="in")
    flow_source = models.CharField(max_length=20, choices=FLOW_SOURCE_CHOICES, default="auto")
    is_auto_approved = models.BooleanField(default=False, db_index=True)
    review_started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        related_name="reviewed_documents",
        null=True
    )
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    rejected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        related_name="rejected_documents",
        null=True, 
        blank=True
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(blank=True, null=True)
    archived_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        related_name="archived_documents",
        null=True
    )
    confidence_global = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, db_index=True)

    objects = ActiveDocumentManager()
    all_objects = models.Manager()

    indexes = [
        models.Index(fields=["client", "status"]),
        models.Index(fields=["client", "review_level"]),
        models.Index(fields=["client", "created_at"]),
        models.Index(fields=["client", "company"]),
    ]

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.document_number or self.original_name} ({self.flow})"
    

