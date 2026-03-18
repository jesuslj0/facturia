import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "billing_ai.settings.base")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import django
from django.conf import settings

django.setup()
settings.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.core.management import call_command
from django.test import Client as DjangoClient
from django.test import RequestFactory
from rest_framework.test import APIClient

from api.models import ApiKey
from clients.models import Client, Role
from documents.models import Company, Document
from finance.models import FinancialMovement, MovementCategory
from finance.signals import create_default_categories
from django.db.models.signals import post_save

post_save.disconnect(create_default_categories, sender=Client)


@pytest.fixture
def client():
    return DjangoClient()


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def client_entity(db):
    return Client.objects.create(name="ACME", tax_id="ES12345678")


@pytest.fixture
def other_client_entity(db):
    return Client.objects.create(name="Other Corp", tax_id="ES87654321")


@pytest.fixture
def role_owner(db, client_entity):
    return Role.objects.create(client=client_entity, name="Owner", code="owner")


@pytest.fixture
def role_reviewer(db, client_entity):
    return Role.objects.create(client=client_entity, name="Reviewer", code="reviewer")


@pytest.fixture
def user(db, client_entity, role_owner):
    User = get_user_model()
    instance = User.objects.create_user(
        username=f"owner-{uuid4().hex[:8]}",
        password="secret123",
        client=client_entity,
        email=f"owner-{uuid4().hex[:8]}@example.com",
    )
    instance.roles.add(role_owner)
    return instance


@pytest.fixture
def other_user(db, other_client_entity):
    User = get_user_model()
    return User.objects.create_user(
        username=f"other-{uuid4().hex[:8]}",
        password="secret123",
        client=other_client_entity,
        email=f"other-{uuid4().hex[:8]}@example.com",
    )


@pytest.fixture
def company(db, client_entity):
    company, _ = Company.objects.get_or_create(
        client=client_entity,
        tax_id="B12345678",
        defaults={"name": "Proveedor Uno", "is_provider": True},
    )
    return company


@pytest.fixture
def customer_company(db, client_entity):
    company, _ = Company.objects.get_or_create(
        client=client_entity,
        tax_id="C87654321",
        defaults={"name": "Cliente Uno", "is_customer": True},
    )
    return company


@pytest.fixture
def document_file():
    return SimpleUploadedFile("invoice.pdf", b"pdf-content", content_type="application/pdf")


@pytest.fixture
def document(db, client_entity, company, document_file):
    return Document.all_objects.create(
        client=client_entity,
        company=company,
        external_id="doc-001",
        original_name="invoice.pdf",
        file=document_file,
        document_type="invoice",
        document_number="INV-001",
        confidence={"confianza_extraccion": 0.95, "fecha": 0.9, "total": 0.95},
        status="pending",
        review_level="required",
        issue_date=date(2026, 3, 10),
        base_amount=Decimal("100.00"),
        tax_amount=Decimal("21.00"),
        tax_percentage=Decimal("21.00"),
        total_amount=Decimal("121.00"),
        confidence_global=Decimal("0.9500"),
        flow="in",
        is_current=True,
    )


@pytest.fixture
def approved_document(db, document, user):
    document.status = "approved"
    document.review_level = "manual"
    document.approved_at = timezone.now()
    document.approved_by = user
    document.is_auto_approved = False
    document.save()
    return document


@pytest.fixture
def movement_category(db, client_entity):
    return MovementCategory.objects.create(
        client=client_entity,
        name="Ventas",
        type="income",
        icon="fa-euro-sign",
        color="#00FF00",
    )


@pytest.fixture
def expense_category(db, client_entity):
    return MovementCategory.objects.create(
        client=client_entity,
        name="Compras Custom",
        type="expense",
        icon="fa-cart-shopping",
        color="#FF0000",
    )


@pytest.fixture
def financial_movement(db, client_entity, user, movement_category):
    return FinancialMovement.objects.create(
        client=client_entity,
        movement_type="income",
        created_by=user,
        category=movement_category,
        description="Cobro factura",
        amount=Decimal("500.00"),
        payment_method="transfer",
        is_reconciled=False,
        is_recurrent=False,
        is_active=True,
        date=date(2026, 3, 10),
    )


@pytest.fixture
def api_key(db, client_entity):
    from django.contrib.auth.hashers import make_password

    secret = "test-secret-value"
    key = ApiKey.objects.create(
        client=client_entity,
        name="Main key",
        prefix="sk_test_fixture",
        key_hash=make_password(secret),
        environment="test",
        scopes=["documents:write"],
    )
    key.raw_key = f"{key.prefix}.{secret}"
    return key


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def api_client():
    return APIClient()
