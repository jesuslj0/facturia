from django.db import models
from django.db.models import Q
from django.db import models, transaction
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
        ("corrected_invoice", "Factura rectificativa"),
        ("delivery_credit_note", "Abono de albarán"),
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

    OCR_CONFIDENCE_CHOICES = [
        ('low', 'Bajo'),
        ('medium', 'Medio'),
        ('high', 'Alto'),
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
        return self.status == "pending" and not self.is_archived
    
    @property
    def has_rectifications(self):
        return self.parent_document 

    @property
    def status_message(self):
        if self.has_rectifications:
            if self.rectified_by and self.rectified_at:
                return f"Rectificación hecha por {self.rectified_by} el {self.rectified_at.strftime('%d-%m-%Y')}"
            return "Documento rectificado"
        
        if self.is_archived:
            if self.archived_by and self.archived_at:
                return f"Documento archivado por {self.archived_by} el {self.archived_at.strftime('%d-%m-%Y')}"
            return "Documento archivado"
        
        if self.status == "rejected":
            if self.rejected_by and self.rejected_at:
                return f"Documento rechazado por {self.rejected_by} el {self.rejected_at.strftime('%d-%m-%Y')}"
            return "Documento rechazado"
        
        if self.approved_at:
            if self.approved_by:
                return f"Documento aprobado por {self.approved_by} el {self.approved_at.strftime('%d-%m-%Y')}"
            return "Documento aprobado"
        
        if self.is_auto_approved:
            return "Documento aprobado automáticamente"
        
        if self.edited_at:
            if self.reviewed_by:
                return f"Documento editado y guardado manualmente por {self.reviewed_by} el {self.edited_at.strftime('%d-%m-%Y')}"
            return "Documento editado manualmente"
        
        return "Documento pendiente de revisión"
    
    @property
    def ocr_confidence(self):
        if self.confidence_global is None:
            return self.OCR_CONFIDENCE_CHOICES[0][0]

        if self.confidence_global >= 0.9:
            return self.OCR_CONFIDENCE_CHOICES[2][0]
        elif self.confidence_global >= 0.6:
            return self.OCR_CONFIDENCE_CHOICES[1][0]
        return self.OCR_CONFIDENCE_CHOICES[0][0]
            

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, 
        related_name="documents"
    )
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, 
        related_name="documents",
        null=True
    )
    external_id = models.CharField(max_length=255, null=True, blank=True)
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
        User,
        related_name="approved_documents",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )
    flow = models.CharField(max_length=20, choices=FLOW_CHOICES, default="in", db_index=True)
    flow_source = models.CharField(max_length=20, choices=FLOW_SOURCE_CHOICES, default="auto")
    is_auto_approved = models.BooleanField(default=False, db_index=True)
    review_started_at = models.DateTimeField(blank=True, null=True, db_index=True)
    reviewed_by = models.ForeignKey(
        User,
        related_name="reviewed_documents",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    rejected_by = models.ForeignKey(
        User, 
        related_name="rejected_documents",
        null=True, 
        blank=True,
        on_delete=models.PROTECT

    )
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(blank=True, null=True)
    archived_by = models.ForeignKey(
        User, 
        related_name="archived_documents",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )
    confidence_global = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, db_index=True)

    rectified_at = models.DateTimeField(blank=True, null=True)
    rectified_by = models.ForeignKey(
        User,
        related_name="rectified_documents",
        null=True,
        blank=True,
        on_delete=models.PROTECT
    )
    rectification_reason = models.CharField(max_length=255, null=True, blank=True)

    parent_document = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="child_documents"
    )
    version = models.PositiveIntegerField(default=1, db_index=True)
    is_current = models.BooleanField(default=True, db_index=True)

    orc_snapshot = models.JSONField(default=dict, blank=True)
    amount_snapshot = models.JSONField(default=dict, blank=True)

    objects = ActiveDocumentManager() #Queryset Documentos activos
    all_objects = models.Manager() #Queryset Documentos archivados y activos

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["client", "review_level"]),
            models.Index(fields=["client", "created_at"]),
            models.Index(fields=["client", "company"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "external_id"],
                name="unique_external_id_per_client",
            ),
            models.UniqueConstraint(
                fields=["parent_document"],
                condition=Q(is_current=True),
                name="unique_current_version_per_document"
            )
        ]

    def __str__(self):
        return f"{self.document_number or self.original_name} ({self.flow})"
    
    def save(self, *args, **kwargs):
        if self.company and self.company.client != self.client:
            raise ValueError("Company must belong to the same client.")
        
        self.full_clean()
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

    def create_rectification(self, user, reason=None, **kwargs):
        parent = self.parent_document or self

        if parent.parent_document_id is not None:
            parent = parent.parent_document

        with transaction.atomic():
            Document.all_objects.filter(
                models.Q(pk=parent.pk) | models.Q(parent_document=parent)
            ).update(is_current=False)

            if self.parent_document_id is None and self.pk != parent.pk:
                self.parent_document = parent
                self.save(update_fields=["parent_document"])

            amount_snapshot = {
                "company_id": self.company_id,
                "base_amount": float(self.base_amount or 0),
                "tax_amount": float(self.tax_amount or 0),
                "total_amount": float(self.total_amount or 0),
            }
            latest_version = (
                Document.all_objects.filter(
                    models.Q(pk=parent.pk) | models.Q(parent_document=parent)
                ).aggregate(max_version=models.Max("version"))["max_version"]
                or parent.version
            )
            new_external_id = f"{self.external_id}-rect-{latest_version + 1}" if self.external_id else None

            new_doc = Document.objects.create(
                client=self.client,
                company=kwargs.get("company", self.company),
                external_id=new_external_id,
                original_name=self.original_name,
                file=self.file,
                document_type=self.document_type,
                document_number=kwargs.get("document_number", self.document_number),
                confidence=self.confidence,
                confidence_global=self.confidence_global,
                status="pending",
                review_level=self.review_level,
                issue_date=kwargs.get("issue_date", self.issue_date),
                base_amount=kwargs.get("base_amount", self.base_amount),
                tax_amount=kwargs.get("tax_amount", self.tax_amount),
                tax_percentage=kwargs.get("tax_percentage", self.tax_percentage),
                total_amount=kwargs.get("total_amount", self.total_amount),
                total_source=self.total_source,
                flow=kwargs.get("flow", self.flow),
                flow_source=self.flow_source,
                is_auto_approved=False,
                parent_document=parent,
                version=latest_version + 1,
                is_current=True,
                rectified_by=user,
                rectified_at=timezone.now(),
                rectification_reason=reason,
                amount_snapshot=amount_snapshot,
            )

        return new_doc
