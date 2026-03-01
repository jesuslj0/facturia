from django.db import transaction
from documents.models import Document
from .metrics_service import MetricsService
from documents.utils import parse_decimal
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

        if data.get("flow"):
            document.flow = data["flow"]

        document.mark_as_manually_reviewed(user)

        document.save()