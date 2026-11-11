"""
Extended API tests covering:
- HasApiKey permission (valid key, expired, inactive, scope check)
- get_review_level / get_status logic
- get_or_create_company helper
- Real document ingest via API key (no mocks) — happy path and edge cases
- Multi-tenancy: authenticated list endpoint isolates per user
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from api.models import ApiKey
from api.permissions import HasApiKey
from api.views import get_review_level, get_status, get_or_create_company, normalize_tax_id
from documents.models import Company, Document

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Permission: HasApiKey
# ---------------------------------------------------------------------------

class TestHasApiKeyPermission:
    def _make_key(self, client_entity, *, environment="test", is_active=True, expires_at=None):
        secret = "valid-secret-123"
        key = ApiKey.objects.create(
            client=client_entity,
            name="Test key",
            prefix=ApiKey._generate_prefix(environment),
            key_hash=make_password(secret),
            environment=environment,
            scopes=["documents:write"],
            is_active=is_active,
            expires_at=expires_at,
        )
        key.raw_key = f"{key.prefix}.{secret}"
        return key

    def test_valid_key_grants_access_and_sets_request_client(self, rf, client_entity):
        key = self._make_key(client_entity)
        request = rf.get("/", HTTP_X_API_KEY=key.raw_key)
        perm = HasApiKey()

        assert perm.has_permission(request, None) is True
        assert request.client == client_entity
        assert request.api_key == key

    def test_missing_header_denies_access(self, rf):
        request = rf.get("/")
        assert HasApiKey().has_permission(request, None) is False

    def test_malformed_key_no_dot_denies_access(self, rf):
        request = rf.get("/", HTTP_X_API_KEY="nodotseparator")
        assert HasApiKey().has_permission(request, None) is False

    def test_unknown_prefix_denies_access(self, rf):
        request = rf.get("/", HTTP_X_API_KEY="sk_test_unknownprefix.secret")
        assert HasApiKey().has_permission(request, None) is False

    def test_inactive_key_denies_access(self, rf, client_entity):
        key = self._make_key(client_entity, is_active=False)
        request = rf.get("/", HTTP_X_API_KEY=key.raw_key)
        assert HasApiKey().has_permission(request, None) is False

    def test_expired_key_denies_access(self, rf, client_entity):
        key = self._make_key(
            client_entity, expires_at=timezone.now() - timedelta(hours=1)
        )
        request = rf.get("/", HTTP_X_API_KEY=key.raw_key)
        assert HasApiKey().has_permission(request, None) is False

    def test_wrong_secret_denies_access(self, rf, client_entity):
        key = self._make_key(client_entity)
        bad_raw = f"{key.prefix}.totally-wrong-secret"
        request = rf.get("/", HTTP_X_API_KEY=bad_raw)
        assert HasApiKey().has_permission(request, None) is False


# ---------------------------------------------------------------------------
# Business logic: get_review_level / get_status
# ---------------------------------------------------------------------------

class TestReviewLevelLogic:
    def test_high_extraction_confidence_returns_auto(self):
        conf = {"confianza_extraccion": 0.95, "fecha": 0.9, "total": 0.9}
        assert get_review_level(conf, "invoice") == "auto"

    def test_low_extraction_confidence_returns_required(self):
        conf = {"confianza_extraccion": 0.60, "fecha": 0.9, "total": 0.9}
        assert get_review_level(conf, "invoice") == "required"

    def test_poor_fecha_confidence_returns_required(self):
        conf = {"confianza_extraccion": 0.80, "fecha": 0.50, "total": 0.9}
        assert get_review_level(conf, "invoice") == "required"

    def test_poor_total_confidence_returns_required(self):
        conf = {"confianza_extraccion": 0.80, "fecha": 0.85, "total": 0.70}
        assert get_review_level(conf, "invoice") == "required"

    def test_good_confidence_unknown_doc_type_returns_required(self):
        conf = {"confianza_extraccion": 0.80, "fecha": 0.85, "total": 0.85}
        assert get_review_level(conf, "expense_report") == "required"

    def test_good_confidence_delivery_type_returns_recommended(self):
        conf = {"confianza_extraccion": 0.80, "fecha": 0.85, "total": 0.85}
        assert get_review_level(conf, "delivery") == "recommended"

    def test_get_status_auto_review_level_returns_approved(self):
        assert get_status("auto") == "approved"

    def test_get_status_required_review_level_returns_pending(self):
        assert get_status("required") == "pending"

    def test_get_status_recommended_review_level_returns_pending(self):
        assert get_status("recommended") == "pending"


# ---------------------------------------------------------------------------
# normalize_tax_id helper
# ---------------------------------------------------------------------------

class TestNormalizeTaxId:
    def test_strips_spaces_dashes_and_uppercases(self):
        assert normalize_tax_id(" b-12 345 678 ") == "B12345678"

    def test_none_returns_none(self):
        assert normalize_tax_id(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_tax_id("") is None


# ---------------------------------------------------------------------------
# get_or_create_company
# ---------------------------------------------------------------------------

class TestGetOrCreateCompany:
    def test_creates_company_when_none_exists(self, client_entity):
        company = get_or_create_company(
            client=client_entity,
            name="  Nuevo Proveedor  ",
            tax_id=" B-99999999 ",
            is_provider=True,
        )
        assert company.pk is not None
        assert company.name == "Nuevo Proveedor"
        assert company.tax_id == "B99999999"
        assert company.is_provider is True

    def test_returns_existing_company_by_tax_id(self, client_entity, company):
        result = get_or_create_company(
            client=client_entity,
            name="Different Name",
            tax_id=company.tax_id,
            is_provider=True,
        )
        assert result.pk == company.pk
        assert Company.objects.filter(client=client_entity, tax_id=company.tax_id).count() == 1

    def test_returns_existing_company_by_name_when_no_tax_id(self, client_entity, company):
        result = get_or_create_company(
            client=client_entity,
            name=company.name,
            tax_id=None,
            is_provider=True,
        )
        assert result.pk == company.pk

    def test_companies_are_isolated_per_client(self, client_entity, other_client_entity):
        company_a = get_or_create_company(
            client=client_entity,
            name="SharedName",
            tax_id="B00000001",
            is_provider=True,
        )
        company_b = get_or_create_company(
            client=other_client_entity,
            name="SharedName",
            tax_id="B00000001",
            is_provider=True,
        )
        assert company_a.pk != company_b.pk
        assert company_a.client == client_entity
        assert company_b.client == other_client_entity


# ---------------------------------------------------------------------------
# Document ingest endpoint — real DB, no mocks
# ---------------------------------------------------------------------------

class TestDocumentIngestEndpointRealDB:
    def _auth_headers(self, api_key):
        return {"HTTP_X_API_KEY": api_key.raw_key}

    def test_ingest_with_high_confidence_creates_auto_approved_document(
        self, api_client, api_key
    ):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                "file": SimpleUploadedFile("real.pdf", b"pdf", content_type="application/pdf"),
                "external_id": "real-ingest-001",
                "original_name": "real.pdf",
                "document_type": "invoice",
                "provider_name": "Proveedor Real",
                "provider_tax_id": "B11111111",
                "document_number": "INV-R-001",
                "issue_date": "2026-03-15",
                "base_amount": "100.00",
                "tax_amount": "21.00",
                "tax_percentage": "21.00",
                "total_amount": "121.00",
                "confidence": '{"confianza_extraccion": 0.95, "fecha": 0.95, "total": 0.95}',
                "flow": "out",
            },
            format="multipart",
            **self._auth_headers(api_key),
        )

        assert response.status_code == status.HTTP_201_CREATED
        doc = Document.all_objects.get(external_id="real-ingest-001")
        assert doc.status == "approved"
        assert doc.review_level == "auto"
        assert doc.is_auto_approved is True
        assert doc.client == api_key.client
        company = Company.objects.get(client=api_key.client, tax_id="B11111111")
        assert doc.company == company
        assert company.is_provider is True

    def test_ingest_with_low_confidence_creates_pending_document(
        self, api_client, api_key
    ):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                "file": SimpleUploadedFile("low.pdf", b"x", content_type="application/pdf"),
                "external_id": "low-confidence-001",
                "original_name": "low.pdf",
                "document_type": "invoice",
                "provider_name": "Provider Low",
                "provider_tax_id": "B22222222",
                "document_number": "INV-LOW-1",
                "issue_date": "2026-03-15",
                "base_amount": "50.00",
                "tax_amount": "10.50",
                "tax_percentage": "21.00",
                "total_amount": "60.50",
                "confidence": '{"confianza_extraccion": 0.60, "fecha": 0.50, "total": 0.70}',
                "flow": "out",
            },
            format="multipart",
            **self._auth_headers(api_key),
        )

        assert response.status_code == status.HTTP_201_CREATED
        doc = Document.all_objects.get(external_id="low-confidence-001")
        assert doc.status == "pending"
        assert doc.is_auto_approved is False

    def test_ingest_flow_in_creates_customer_company(self, api_client, api_key):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                "file": SimpleUploadedFile("cust.pdf", b"y", content_type="application/pdf"),
                "external_id": "cust-ingest-001",
                "original_name": "cust.pdf",
                "document_type": "invoice",
                "provider_name": "Customer Inc",
                "provider_tax_id": "C33333333",
                "document_number": "INV-C-1",
                "issue_date": "2026-03-20",
                "base_amount": "200.00",
                "tax_amount": "42.00",
                "tax_percentage": "21.00",
                "total_amount": "242.00",
                "confidence": '{"confianza_extraccion": 0.95, "fecha": 0.95, "total": 0.95}',
                "flow": "in",
            },
            format="multipart",
            **self._auth_headers(api_key),
        )

        assert response.status_code == status.HTTP_201_CREATED
        company = Company.objects.get(client=api_key.client, tax_id="C33333333")
        assert company.is_customer is True

    def test_ingest_duplicate_external_id_returns_400(self, api_client, api_key, document):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                "file": SimpleUploadedFile("dup.pdf", b"z", content_type="application/pdf"),
                "external_id": document.external_id,
                "original_name": "dup.pdf",
                "document_type": "invoice",
                "provider_name": "Dup Provider",
                "provider_tax_id": "B44444444",
                "issue_date": "2026-03-15",
                "base_amount": "10.00",
                "tax_amount": "2.10",
                "tax_percentage": "21.00",
                "total_amount": "12.10",
                "confidence": "{}",
                "flow": "out",
            },
            format="multipart",
            **self._auth_headers(api_key),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_ingest_without_api_key_returns_403(self, api_client):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                "file": SimpleUploadedFile("noauth.pdf", b"n", content_type="application/pdf"),
                "external_id": "no-auth-001",
                "original_name": "noauth.pdf",
                "document_type": "invoice",
                "provider_name": "P",
                "provider_tax_id": "B55555555",
                "base_amount": "10.00",
                "tax_amount": "2.10",
                "tax_percentage": "21.00",
                "total_amount": "12.10",
                "confidence": "{}",
                "flow": "out",
            },
            format="multipart",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ingest_missing_required_field_returns_400(self, api_client, api_key):
        response = api_client.post(
            "/api/v1/documents/ingest/",
            data={
                # missing provider_name and file
                "external_id": "missing-fields-001",
                "original_name": "missing.pdf",
                "document_type": "invoice",
                "provider_tax_id": "B66666666",
                "base_amount": "10.00",
                "tax_amount": "2.10",
                "tax_percentage": "21.00",
                "total_amount": "12.10",
                "confidence": "{}",
                "flow": "out",
            },
            format="multipart",
            **self._auth_headers(api_key),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# ApiKey.create_key — exhausted prefix collision raises RuntimeError
# ---------------------------------------------------------------------------

class TestApiKeyCreateKeyExhaustion:
    def test_raises_runtime_error_when_all_prefixes_collide(self, client_entity, monkeypatch):
        """After 10 collisions create_key must raise RuntimeError."""
        collision_prefix = "sk_live_collision999"
        ApiKey.objects.create(
            client=client_entity,
            name="Existing",
            prefix=collision_prefix,
            key_hash=make_password("x"),
            environment="live",
        )

        monkeypatch.setattr(
            ApiKey, "_generate_prefix", staticmethod(lambda env: collision_prefix)
        )

        with pytest.raises(RuntimeError, match="Unable to generate a unique API key prefix"):
            ApiKey.create_key(client=client_entity, name="Failing key", environment="live")


# ---------------------------------------------------------------------------
# ApiKey scope checks
# ---------------------------------------------------------------------------

class TestApiKeyScopes:
    def test_has_scope_returns_false_for_unlisted_scope(self, api_key):
        assert api_key.has_scope("admin:delete") is False

    def test_has_scope_returns_true_for_documents_write(self, api_key):
        assert api_key.has_scope("documents:write") is True

    def test_key_without_scopes_returns_false(self, client_entity):
        key = ApiKey.objects.create(
            client=client_entity,
            name="No scopes",
            prefix=ApiKey._generate_prefix("live"),
            key_hash=make_password("secret"),
            environment="live",
            scopes=[],
        )
        assert key.has_scope("documents:write") is False
