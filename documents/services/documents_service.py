from django.db import transaction
from documents.models import Document, DocumentAuditLog
from documents.utils import parse_decimal
from documents.services import organization
from decimal import InvalidOperation

class DocumentService:

    @staticmethod
    @transaction.atomic
    def approve(document: Document, user=None):
        document.approve(user=user, auto=False)

    @staticmethod
    @transaction.atomic
    def auto_approve(document: Document, user=None):
        document.approve(user=user, auto=True)

    @staticmethod
    @transaction.atomic
    def reject(document: Document, user=None, reason=None):
        document.reject(user=user, reason=reason)

    @staticmethod
    @transaction.atomic
    def archive(document: Document, user=None):
        document.archive(user=user)

    @staticmethod
    @transaction.atomic
    def unarchive(document: Document, user=None):
        document.unarchive(user=user)

    @staticmethod
    @transaction.atomic
    def rectify(document: Document, user=None, reason=None, form_data=None):
        return document.create_rectification(user=user, reason=reason, **(form_data or {}))

    @staticmethod
    @transaction.atomic
    def update_from_form(document: Document, user, data: dict):

        try:
            new_base = parse_decimal(data.get("base_amount"))
            new_tax_percentage = parse_decimal(data.get("tax_percentage"))
            new_tax_amount = parse_decimal(data.get("tax_amount"))
            new_total = parse_decimal(data.get("total_amount"))
        except (InvalidOperation, ValueError):
            raise ValueError("Importe inválido")

        # Asignaciones
        if data.get("document_number"):
            document.document_number = data["document_number"]

        if data.get("issue_date"):
            document.issue_date = data["issue_date"]

        if new_base is not None:
            document.base_amount = new_base

        if new_tax_percentage is not None:
            document.tax_percentage = new_tax_percentage

        if new_tax_amount is not None:
            document.tax_amount = new_tax_amount

        if new_total is not None:
            document.total_amount = new_total

        # Si el usuario cambia compra/venta, deja de ser el flujo calculado por la IA.
        if data.get("flow") and data["flow"] != document.flow:
            document.flow = data["flow"]
            document.flow_source = "manual"

        organization.apply_organization(document, data)

        document.mark_as_manually_reviewed(user)

        document.save()
        if "tags" in data:
            organization.set_tags(document, data.get("tags"))

    @staticmethod
    @transaction.atomic
    def organize(document: Document, user, data: dict):
        """Cambia solo la organización (carpeta manual y etiquetas): no es una rectificación ni una
        edición de datos, así que vale en cualquier estado y no toca revisión ni importes."""
        before = {
            "folder": document.folder_id,
            "tags": sorted(document.tags.values_list("name", flat=True)),
        }
        organization.apply_folder(document, data)
        document.save(update_fields=["folder"])
        if "tags" in data:
            organization.set_tags(document, data.get("tags"))
        after = {
            "folder": document.folder_id,
            "tags": sorted(document.tags.values_list("name", flat=True)),
        }
        if before != after:
            DocumentAuditLog(
                document=document, user=user, action="edited",
                changes={"organization": {"from": before, "to": after}},
            ).save()
