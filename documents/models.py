from django.db import models
from django.db.models import Q
from django.db import models, transaction
from clients.models import Client
import os
from django.utils import timezone
from django.core.exceptions import ValidationError

from django.contrib.auth import get_user_model
from billing_ai.storage import document_upload_to
User = get_user_model()

class Company(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, 
        related_name="companies"
    )
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=50, null=True, blank=True)
    address = models.CharField(max_length=255, blank=True, default="")
    postal_code = models.CharField(max_length=20, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    country = models.CharField(max_length=2, default="ES", help_text="ISO 3166-1 alpha-2")
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
        if not self.tax_id:
            # "" violaría la unicidad (client, tax_id); sin NIF se guarda NULL.
            self.tax_id = None
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
    file = models.FileField(upload_to=document_upload_to)
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

    # --- H1: procesado, origen y organización --------------------------------
    PROCESSING_CHOICES = [
        ("uploaded", "Subido"),
        ("queued", "En cola"),
        ("processing", "Procesando"),
        ("processed", "Procesado"),
        ("failed", "Error"),
    ]
    SOURCE_CHOICES = [
        ("n8n", "n8n (API de ingesta)"),
        ("upload", "Subida en la app"),
        ("import", "Importación"),
    ]
    processing_status = models.CharField(
        max_length=12, choices=PROCESSING_CHOICES, default="processed", db_index=True
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="n8n")
    currency = models.CharField(max_length=3, default="EUR")
    iban = models.CharField(max_length=34, blank=True, default="")
    category = models.ForeignKey(
        "DocumentCategory", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="documents",
    )
    folder = models.ForeignKey(
        "Folder", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="documents",
    )
    tags = models.ManyToManyField("Tag", blank=True, related_name="documents")

    @property
    def quarter(self):
        """Trimestre natural de la fecha de emisión, p. ej. '2026-T1' (None si no hay fecha)."""
        if not self.issue_date:
            return None
        return f"{self.issue_date.year}-T{(self.issue_date.month - 1) // 3 + 1}"

    objects = ActiveDocumentManager() #Queryset Documentos activos
    all_objects = models.Manager() #Queryset Documentos archivados y activos

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["client", "review_level"]),
            models.Index(fields=["client", "created_at"]),
            models.Index(fields=["client", "company"]),
            models.Index(fields=["client", "is_current"], name="doc_client_current_idx"),
            models.Index(fields=["client", "issue_date"], name="doc_client_issue_idx"),
            models.Index(fields=["client", "processing_status"], name="doc_client_proc_idx"),
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



# ---------------------------------------------------------------------------
# H1 — organización
# ---------------------------------------------------------------------------

class DocumentCategory(models.Model):
    """Categoría contable de un documento (distinta de finance.MovementCategory)."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="document_categories")
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "document categories"
        constraints = [
            models.UniqueConstraint(fields=["client", "name"], name="unique_doc_category_per_client"),
        ]

    def __str__(self):
        return self.name


class Folder(models.Model):
    """Carpeta virtual (solo en base de datos; el bucket no cambia al mover documentos)."""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="folders")
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["client", "name"], name="unique_folder_per_client"),
        ]

    def __str__(self):
        return self.name


class Tag(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["client", "name"], name="unique_tag_per_client"),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# H1 — archivo original y extracción
# ---------------------------------------------------------------------------

class DocumentFile(models.Model):
    """Metadatos del archivo original.

    Un registro por documento *original*. Las rectificaciones (`parent_document`)
    reutilizan el archivo del original y no tienen `DocumentFile` propio.
    `unique(client, sha256)` impide guardar dos veces el mismo contenido por tenant.
    """
    ORIGIN_CHOICES = [
        ("n8n", "n8n"),
        ("upload", "Subida web"),
        ("mobile", "Foto móvil"),
        ("import", "Importación"),
    ]

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="stored_file")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="document_files")
    sha256 = models.CharField(max_length=64)
    mime_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    page_count = models.PositiveSmallIntegerField(null=True, blank=True)
    origin = models.CharField(max_length=10, choices=ORIGIN_CHOICES, default="upload")
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploaded_files"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["client", "sha256"], name="unique_file_hash_per_client"),
        ]
        indexes = [models.Index(fields=["client", "created_at"])]

    def __str__(self):
        return f"{self.sha256[:12]} ({self.size_bytes} B)"

    def save(self, *args, **kwargs):
        if self.document_id and self.client_id and self.document.client_id != self.client_id:
            raise ValueError("DocumentFile must belong to the same client as its document.")
        super().save(*args, **kwargs)


class ExtractionRun(models.Model):
    """Una llamada de extracción (OCR/estructuración) sobre un documento."""
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("running", "En curso"),
        ("succeeded", "Correcta"),
        ("failed", "Fallida"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="extraction_runs")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="extraction_runs")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    provider = models.CharField(max_length=30, default="anthropic")
    model = models.CharField(max_length=100, blank=True, default="")
    prompt_version = models.CharField(max_length=30, blank=True, default="")
    is_fallback = models.BooleanField(default=False)
    attempt = models.PositiveSmallIntegerField(default=1)
    raw_response = models.JSONField(default=dict, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    error_code = models.CharField(max_length=50, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_creation_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document", "-created_at"], name="extrun_doc_created_idx"),
            models.Index(fields=["client", "created_at"], name="extrun_client_created_idx"),
            models.Index(fields=["client", "status"], name="extrun_client_status_idx"),
        ]

    def __str__(self):
        return f"{self.model or 'run'} #{self.attempt} ({self.status})"

    def save(self, *args, **kwargs):
        if self.document_id and self.client_id and self.document.client_id != self.client_id:
            raise ValueError("ExtractionRun must belong to the same client as its document.")
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# H1 — contenido de la factura
# ---------------------------------------------------------------------------

class InvoiceLine(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=1)
    description = models.CharField(max_length=500, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["document_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["document", "position"], name="unique_line_position_per_document"),
            models.CheckConstraint(
                condition=Q(tax_rate__isnull=True) | (Q(tax_rate__gte=0) & Q(tax_rate__lte=100)),
                name="invoice_line_tax_rate_0_100",
            ),
        ]

    def __str__(self):
        return f"{self.position}. {self.description[:40]}"


class TaxBreakdown(models.Model):
    """Desglose de impuestos y retenciones por tipo.

    Importes siempre positivos. Total = base + IVA + recargo − retención
    (ver `documents.services.taxes.expected_total`).
    """
    VAT = "vat"
    SURCHARGE = "surcharge"
    WITHHOLDING = "withholding"
    KIND_CHOICES = [
        (VAT, "IVA"),
        (SURCHARGE, "Recargo de equivalencia"),
        (WITHHOLDING, "Retención (IRPF)"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="tax_lines")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    base = models.DecimalField(max_digits=12, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["document_id", "kind", "-rate"]
        constraints = [
            models.UniqueConstraint(fields=["document", "kind", "rate"], name="unique_tax_line_per_document"),
            models.CheckConstraint(
                condition=Q(rate__gte=0) & Q(rate__lte=100), name="tax_line_rate_0_100"
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name="tax_line_amount_non_negative"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.rate}% = {self.amount}"


# ---------------------------------------------------------------------------
# H1 — auditoría
# ---------------------------------------------------------------------------

class DocumentAuditLog(models.Model):
    """Registro de cambios (solo se añade; no se edita)."""
    ACTION_CHOICES = [
        ("created", "Creado"),
        ("extracted", "Extraído"),
        ("edited", "Editado"),
        ("approved", "Aprobado"),
        ("rejected", "Rechazado"),
        ("archived", "Archivado"),
        ("unarchived", "Desarchivado"),
        ("rectified", "Rectificado"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="audit_logs")
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="document_audit_logs"
    )
    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["document", "created_at"], name="audit_doc_created_idx")]

    def __str__(self):
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("DocumentAuditLog es de solo añadir.")
        super().save(*args, **kwargs)
