from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.db.models import Q

from clients.models import Client
from documents.models import Company, Document
from documents.selectors.document_selector import DocumentSelector
from documents.services.metrics_service import MetricsService


User = get_user_model()


class DocumentVersioningTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(name="ACME")
        self.user = User.objects.create_user(
            username="owner",
            password="secret",
            client=self.client_obj,
        )
        self.company = Company.objects.create(
            client=self.client_obj,
            name="Proveedor",
            is_provider=True,
        )

    def _build_document(self, **kwargs):
        defaults = {
            "client": self.client_obj,
            "company": self.company,
            "external_id": kwargs.get("external_id", "ext"),
            "original_name": "invoice.pdf",
            "file": SimpleUploadedFile("invoice.pdf", b"pdf-content", content_type="application/pdf"),
            "document_type": "invoice",
            "status": "approved",
            "issue_date": date(2024, 1, 10),
            "base_amount": Decimal("100.00"),
            "tax_amount": Decimal("21.00"),
            "tax_percentage": Decimal("21.00"),
            "total_amount": Decimal("121.00"),
            "flow": "in",
            "review_level": "manual",
            "confidence": {"score": 0.95},
            "is_current": True,
        }
        defaults.update(kwargs)
        return Document.all_objects.create(**defaults)

    def test_selector_for_client_returns_only_current_versions(self):
        root = self._build_document(external_id="doc-1", is_current=False)
        current = self._build_document(
            external_id="doc-1-rect-2",
            parent_document=root,
            version=2,
            is_current=True,
        )

        qs = DocumentSelector.for_client(self.client_obj)

        self.assertEqual(list(qs), [current])
        self.assertEqual(DocumentSelector.with_versions(self.client_obj).count(), 2)

    def test_metrics_only_count_current_documents(self):
        root = self._build_document(
            external_id="metrics-doc-1",
            base_amount=Decimal("100.00"),
            tax_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            is_current=False,
        )
        self._build_document(
            external_id="metrics-doc-1-rect-2",
            parent_document=root,
            version=2,
            base_amount=Decimal("200.00"),
            tax_amount=Decimal("42.00"),
            total_amount=Decimal("242.00"),
            is_current=True,
        )

        metrics = MetricsService.get_user_metrics(
            user=self.user,
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )

        self.assertEqual(metrics["documents"]["total"], 1)
        self.assertEqual(metrics["financials"]["documents"]["income"], 200.0)

    def test_create_rectification_keeps_single_current_version(self):
        doc = self._build_document(external_id="rectify-1", version=1, is_current=True)

        new_doc = doc.create_rectification(user=self.user, reason="Ajuste", base_amount=Decimal("150.00"))

        versions = DocumentSelector.with_versions(self.client_obj).filter(
            Q(pk=new_doc.parent_document_id) | Q(parent_document_id=new_doc.parent_document_id)
        )

        self.assertEqual(versions.filter(is_current=True).count(), 1)
        self.assertEqual(new_doc.is_current, True)
        self.assertEqual(new_doc.version, 2)
        self.assertEqual(new_doc.parent_document_id, doc.id)
