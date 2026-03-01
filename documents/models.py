from django.db import models
from clients.models import Client
import os
from django.utils import timezone
from django.core.exceptions import ValidationError

from django.contrib.auth import get_user_model
User = get_user_model()

class Company(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, 
        related_name="companies"
    )
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, null=True, blank=True)
    is_provider = models.BooleanField(default=False, db_index=True)
    is_customer = models.BooleanField(default=False, db_index=True)
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

    def get_type(self):
        return "Proveedor" if self.is_provider else "Cliente"


    def __str__(self):
        return f"{self.name} ({self.get_type()})"
    

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
        ("in", "Ingreso (venta)"),
        ("out", "Gasto (compra)"),
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
        if self.is_archived:
            return f"Documento archivado  por {self.archived_by} el {self.archived_at.strftime('%d-%m-%Y')}"
        if self.status == "rejected":
            return f"El documento ha sido rechazado por {self.rejected_by} el {self.rejected_at.strftime('%d-%m-%Y')}"
        if self.approved_at:
            return f"Documento aprobado por {self.approved_by} el {self.approved_at.strftime('%d-%m-%Y')}"
        if self.is_auto_approved:
            return "Documento aprobado automáticamente"
        if self.edited_at:
            return f"Documento editado y guardado manualmente por {self.reviewed_by} el {self.edited_at.strftime('%d-%m-%Y')}"
        return "Documento pendiente de revisión"
    
    def save(self, *args, **kwargs):
        if self.company and self.company.client != self.client:
            raise ValueError("Company must belong to the same client.")
        super().save(*args, **kwargs)

    def can_be_approved(self): 
        return (
            self.status == "pending" 
            and self.total_amount is not None
            and self.issue_date is not None
        )
    def mark_as_manually_reviewed(self, user):
        self.review_level = "manual"
        self.is_auto_approved = False
        self.reviewed_by = user
        self.edited_at = timezone.now()
    
    def approve(self, user=None, auto=False):
        if not self.can_be_approved():
            raise ValueError("Document cannot be approved.")
        
        self.status = "approved"
        self.approved_at = None if auto else timezone.now()
        self.approved_by = None if auto else user
        self.is_auto_approved = auto
        self.save(
            update_fields=[
                "status", "approved_at", "approved_by", "is_auto_approved"
            ]
        )

    def reject(self, user=None, reason=None):
        if self.status != "pending":
            raise ValidationError("Document cannot be rejected.")

        self.status = "rejected"
        self.rejected_at = timezone.now()
        self.rejected_by = user
        self.rejection_reason = reason

        self.save(
            update_fields=[
                "status", "rejected_at", "rejected_by", "rejection_reason"
            ]
        )

    def archive(self, user=None):
        if self.status not in ["approved", "rejected"]:
            raise ValidationError("Document cannot be archived.")

        self.is_archived = True
        self.archived_at = timezone.now()
        self.archived_by = user
        self.save(
            update_fields=[
                "is_archived", "archived_at", "archived_by"
            ]
        )

    def unarchive(self, user=None):
        if not self.is_archived:
            raise ValidationError("Document is not archived.")

        self.is_archived = False
        self.archived_at = None
        self.archived_by = None
        self.save(
            update_fields=[
                "is_archived", "archived_at", "archived_by"
            ]
        )



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
    flow = models.CharField(max_length=20, choices=FLOW_CHOICES, default="in", db_index=True)
    flow_source = models.CharField(max_length=20, choices=FLOW_SOURCE_CHOICES, default="auto")
    is_auto_approved = models.BooleanField(default=False, db_index=True)
    review_started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        related_name="reviewed_documents",
        null=True
    )
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
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

    objects = ActiveDocumentManager() #Queryset Documentos activos
    all_objects = models.Manager() #Queryset Documentos archivados y activos

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
    

