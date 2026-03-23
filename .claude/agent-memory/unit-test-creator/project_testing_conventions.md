---
name: billing_ai testing conventions
description: Testing framework, patterns, fixture layout, and naming conventions for the billing_ai Django project
type: project
---

## Stack & runner
- pytest-django 4.12, pytest 9.0, Python 3.12
- `pytest.ini`: `DJANGO_SETTINGS_MODULE = billing_ai.settings.base`, `addopts = --reuse-db`
- Run: `source venv/bin/activate && python -m pytest --reuse-db -v`
- Settings module: `billing_ai.settings.base`

## Test file locations
- `api/tests/test_models.py`, `api/tests/test_api.py`, `api/tests/test_api_auth_and_ingest.py`
- `clients/tests/test_models.py`, `clients/tests/test_client_views.py`
- `documents/tests/test_models.py`, `test_views.py`, `test_services.py`, `test_selectors.py`, `test_forms.py`, `test_document_flows.py`, `test_utils.py`
- `finance/tests/test_models.py`, `test_views.py`, `test_forms.py`, `test_finance_extended.py`

## Fixtures (conftest.py at project root)
- `client_entity` — Client "ACME" (ES12345678)
- `other_client_entity` — Client "Other Corp" (ES87654321) for isolation tests
- `user` — CustomUser with `role_owner`, belongs to `client_entity`
- `other_user` — CustomUser belonging to `other_client_entity` (no roles)
- `company` — Provider company (B12345678) under client_entity
- `customer_company` — Customer company (C87654321) under client_entity
- `role_owner`, `role_reviewer` — Role objects under client_entity
- `document` — pending Document, flow="in", status="pending", is_current=True
- `approved_document` — approved version of `document`
- `movement_category` — income category under client_entity
- `expense_category` — expense category under client_entity
- `financial_movement` — FinancialMovement, income, amount=500, date=2026-03-10
- `api_key` — ApiKey with prefix "sk_test_fixture", scopes=["documents:write"], raw_key set
- `auth_client` — Django test client force-logged in as `user`
- `api_client` — DRF APIClient (unauthenticated by default)

## Key patterns
- `@pytest.mark.django_db` on class or `pytestmark = pytest.mark.django_db` at module level
- Multi-tenancy: always test that client A cannot see/edit client B data (expect 404 or filtered qs)
- `Document.all_objects` — includes archived; `Document.objects` — excludes archived (ActiveDocumentManager)
- DocumentSelector.exportable() does NOT exist — use `get_exportable_documents()` from `documents.filters.document_filters`
- Finance signals (`create_default_categories`) are disconnected in conftest `_test_settings` autouse fixture

## Known source code notes
- `api/views.py` get_or_create_company: bug — sets `company.is_supplier` (not `is_provider`) when updating existing record; tests work around this
- PDF export filename: single document → `factura_{document_number}.pdf`; multiple → `facturas.pdf`
- `export_preview` view puts pdf context under `context["pdf_context"]["invoices"]` (not `pdf_preview_documents`)

**Why:** Avoids re-discovering these gotchas in every session.
**How to apply:** When writing new document/finance tests check these names; when a test breaks on filename/context key, refer here first.
