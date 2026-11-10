from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
pytestmark = pytest.mark.django_db

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from api.permissions import HasApiKey
from api.serializers import DocumentIngestSerializer, DocumentListSerializer
from documents.models import Company, Document


@pytest.mark.django_db
class TestApiAuthAndSerializers:
    def test_has_api_key_rejects_missing_and_invalid_headers(self, rf):
        permission = HasApiKey()
        request = rf.get("/api/v1/documents/ingest/")

        assert permission.has_permission(request, None) is False

        request = rf.get("/api/v1/documents/ingest/", HTTP_X_API_KEY="malformed")
        assert permission.has_permission(request, None) is False

    def test_ingest_serializer_rejects_duplicate_external_id(self, client_entity, document):
        serializer = DocumentIngestSerializer(
            data={
                "file": SimpleUploadedFile("dup.pdf", b"x", content_type="application/pdf"),
                "external_id": document.external_id,
                "original_name": "dup.pdf",
                "document_type": "invoice",
                "provider_name": "Proveedor Uno",
                "provider_tax_id": "B12345678",
                "document_number": "INV-2",
                "issue_date": "2026-03-10",
                "base_amount": 100,
                "tax_amount": 21,
                "tax_percentage": 21,
                "total_amount": 121,
                "confidence": {},
                "flow": "in",
            },
            context={"client": client_entity},
        )

        assert serializer.is_valid() is False
        assert "external_id" in serializer.errors

    def test_document_list_serializer_builds_absolute_file_url(self, rf, document):
        request = rf.get("/api/v1/documents/")
        serialized = DocumentListSerializer(document, context={"request": request}).data

        assert serialized["file_url"].endswith(f"/documents/{document.pk}/file/")


@pytest.mark.django_db
class TestDocumentApiViews:
    def _auth_headers(self, api_key):
        return {"HTTP_X_API_KEY": api_key.raw_key}

    PAYLOAD = {
        "external_id": "api-doc-001", "original_name": "invoice.pdf", "document_type": "invoice",
        "provider_name": "Proveedor API", "provider_tax_id": " b-12345678 ",
        "document_number": "INV-API-1", "issue_date": "2026-03-10",
        "base_amount": "100.00", "tax_amount": "21.00", "tax_percentage": "21.00", "total_amount": "121.00",
        "confidence": "{\"confianza_extraccion\": 0.95, \"fecha\": 0.95, \"total\": 0.9}", "flow": "out",
    }

    def _ingest(self, api_client, api_key, content=b"%PDF-1.4 content", **over):
        data = {**self.PAYLOAD, **over,
                "file": SimpleUploadedFile("invoice.pdf", content, content_type="application/pdf")}
        with patch("api.permissions.HasApiKey.has_permission",
                   side_effect=lambda request, view: setattr(request, "client", api_key.client) or True):
            return api_client.post("/api/v1/documents/ingest/", data=data, format="multipart",
                                   **self._auth_headers(api_key))

    def test_document_ingest_creates_document_and_company(self, api_client, api_key):
        from documents.models import DocumentFile
        response = self._ingest(api_client, api_key)

        assert response.status_code == status.HTTP_201_CREATED
        doc = Document.all_objects.get(external_id="api-doc-001")
        assert doc.status == "approved" and doc.review_level == "auto" and doc.is_auto_approved is True
        assert doc.company.tax_id == "B12345678"
        assert doc.source == "n8n" and doc.processing_status == "processed"
        assert DocumentFile.objects.get(document=doc).origin == "n8n"

    def test_ingest_rejects_same_content_with_409(self, api_client, api_key):
        first = self._ingest(api_client, api_key)
        second = self._ingest(api_client, api_key, external_id="api-doc-other")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["document_id"] == Document.all_objects.get(external_id="api-doc-001").pk
        assert Document.all_objects.count() == 1

    def test_ingest_disabled_returns_410(self, api_client, api_key, settings):
        settings.N8N_INGEST_ENABLED = False
        response = self._ingest(api_client, api_key)
        assert response.status_code == status.HTTP_410_GONE
        assert Document.all_objects.count() == 0

    def test_document_ingest_returns_400_for_invalid_flow(self, api_client, api_key):
        with patch("api.permissions.HasApiKey.has_permission", side_effect=lambda request, view: setattr(request, "client", api_key.client) or True):
            response = api_client.post(
                "/api/v1/documents/ingest/",
                data={
                    "file": SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 content", content_type="application/pdf"),
                    "external_id": "api-doc-002",
                    "original_name": "invoice.pdf",
                    "document_type": "invoice",
                    "provider_name": "Proveedor API",
                    "provider_tax_id": "B12345678",
                    "base_amount": "100.00",
                    "tax_amount": "21.00",
                    "tax_percentage": "21.00",
                    "total_amount": "121.00",
                    "confidence": "{\"confianza_extraccion\": 0.95, \"fecha\": 0.95, \"total\": 0.9}",
                    "flow": "sideways",
                },
                format="multipart",
                **self._auth_headers(api_key),
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Document.objects.filter(external_id="api-doc-002").exists() is False

    def test_document_list_requires_authenticated_user(self, client, document):
        response = client.get(reverse("api:api_documents_list"))

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_document_list_returns_only_user_client_documents(self, api_client, user, document, other_client_entity):
        other_company = Company.objects.create(client=other_client_entity, name="Foreign", is_provider=True)
        Document.all_objects.create(
            client=other_client_entity,
            company=other_company,
            external_id="foreign-doc",
            original_name="foreign.pdf",
            file=SimpleUploadedFile("foreign.pdf", b"x", content_type="application/pdf"),
            document_type="invoice",
            confidence={"score": 0.1},
            status="approved",
            review_level="manual",
            issue_date=date(2026, 3, 10),
            base_amount=Decimal("50.00"),
            tax_amount=Decimal("10.50"),
            tax_percentage=Decimal("21.00"),
            total_amount=Decimal("60.50"),
            flow="in",
        )
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse("api:api_documents_list"))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["id"] == document.id

    def test_metrics_dashboard_returns_metrics_payload(self, api_client, user):
        api_client.force_authenticate(user=user)
        with patch("api.views.MetricsService.get_user_metrics", return_value={"documents": {"total": 2}}) as mocked:
            response = api_client.get("/api/v1/metrics/dashboard/?start=2026-03-01&end=2026-03-31")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"documents": {"total": 2}}
        mocked.assert_called_once()

    def test_metrics_dashboard_validates_dates(self, api_client, user):
        api_client.force_authenticate(user=user)

        response = api_client.get("/api/v1/metrics/dashboard/?start=bad&end=2026-03-31")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
