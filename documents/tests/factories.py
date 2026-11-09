"""Factories (factory_boy) compartidas por los tests de H1+."""
from datetime import date
from decimal import Decimal

import factory
from django.core.files.uploadedfile import SimpleUploadedFile
from factory.django import DjangoModelFactory

from clients.models import Client, CustomUser
from documents.models import (
    Company, Document, DocumentAuditLog, DocumentCategory, DocumentFile,
    ExtractionRun, Folder, InvoiceLine, Tag, TaxBreakdown,
)


class ClientFactory(DjangoModelFactory):
    class Meta:
        model = Client

    name = factory.Sequence(lambda n: f"Cliente {n}")
    tax_id = factory.Sequence(lambda n: f"B{10000000 + n}")


class UserFactory(DjangoModelFactory):
    class Meta:
        model = CustomUser

    client = factory.SubFactory(ClientFactory)
    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "secret123")


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company

    client = factory.SubFactory(ClientFactory)
    name = factory.Sequence(lambda n: f"Proveedor {n}")
    tax_id = factory.Sequence(lambda n: f"A{20000000 + n}")
    is_provider = True


class DocumentFactory(DjangoModelFactory):
    class Meta:
        model = Document

    client = factory.SubFactory(ClientFactory)
    company = factory.SubFactory(CompanyFactory, client=factory.SelfAttribute("..client"))
    external_id = factory.Sequence(lambda n: f"ext-{n}")
    original_name = "factura.pdf"
    file = factory.LazyAttribute(
        lambda o: SimpleUploadedFile("factura.pdf", b"%PDF-1.4 " + o.external_id.encode())
    )
    document_type = "invoice"
    document_number = factory.Sequence(lambda n: f"FAC-{n:04d}")
    confidence = {"confianza_extraccion": 0.95, "fecha": 0.9, "total": 0.95}
    issue_date = date(2026, 2, 15)
    base_amount = Decimal("100.00")
    tax_percentage = Decimal("21.00")
    tax_amount = Decimal("21.00")
    total_amount = Decimal("121.00")
    flow = "out"


class DocumentFileFactory(DjangoModelFactory):
    class Meta:
        model = DocumentFile

    document = factory.SubFactory(DocumentFactory)
    client = factory.SelfAttribute("document.client")
    sha256 = factory.Sequence(lambda n: f"{n:064x}")
    mime_type = "application/pdf"
    size_bytes = 1024


class ExtractionRunFactory(DjangoModelFactory):
    class Meta:
        model = ExtractionRun

    document = factory.SubFactory(DocumentFactory)
    client = factory.SelfAttribute("document.client")
    model = "claude-haiku-5-5"
    prompt_version = "v1"


class TaxBreakdownFactory(DjangoModelFactory):
    class Meta:
        model = TaxBreakdown

    document = factory.SubFactory(DocumentFactory)
    kind = TaxBreakdown.VAT
    rate = Decimal("21.00")
    base = Decimal("100.00")
    amount = Decimal("21.00")


class InvoiceLineFactory(DjangoModelFactory):
    class Meta:
        model = InvoiceLine

    document = factory.SubFactory(DocumentFactory)
    position = factory.Sequence(lambda n: n + 1)
    description = "Servicio"
    quantity = Decimal("1")
    unit_price = Decimal("100.00")
    amount = Decimal("100.00")


class DocumentCategoryFactory(DjangoModelFactory):
    class Meta:
        model = DocumentCategory

    client = factory.SubFactory(ClientFactory)
    name = factory.Sequence(lambda n: f"Categoría {n}")


class FolderFactory(DjangoModelFactory):
    class Meta:
        model = Folder

    client = factory.SubFactory(ClientFactory)
    name = factory.Sequence(lambda n: f"Carpeta {n}")


class TagFactory(DjangoModelFactory):
    class Meta:
        model = Tag

    client = factory.SubFactory(ClientFactory)
    name = factory.Sequence(lambda n: f"tag{n}")


class DocumentAuditLogFactory(DjangoModelFactory):
    class Meta:
        model = DocumentAuditLog

    document = factory.SubFactory(DocumentFactory)
    action = "created"
