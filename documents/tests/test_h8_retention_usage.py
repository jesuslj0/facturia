"""H8: retención, coste/tokens y log por documento."""
import logging
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from documents.models import Document
from documents.services import MetricsService, retention
from documents.services.usage import extraction_usage
from documents.tests.factories import ClientFactory, DocumentFactory, ExtractionRunFactory

pytestmark = pytest.mark.django_db
TODAY = date(2026, 11, 10)


class TestRetention:
    def test_cutoff(self):
        assert retention.cutoff_date(TODAY, 10) == date(2016, 11, 10)
        assert retention.cutoff_date(date(2028, 2, 29), 1) == date(2027, 2, 28)

    def test_default_is_ten_years(self, settings):
        assert retention.retention_years() == 10

    def test_only_expired_are_purged(self, client_entity):
        old = DocumentFactory(client=client_entity, issue_date=date(2010, 1, 1))
        recent = DocumentFactory(client=client_entity, issue_date=date(2025, 1, 1))
        r = retention.purge_expired(apply=True, today=TODAY)
        assert r["documents"] == 1
        assert not Document.all_objects.filter(pk=old.pk).exists()
        assert Document.all_objects.filter(pk=recent.pk).exists()

    def test_dry_run_deletes_nothing(self, client_entity):
        d = DocumentFactory(client=client_entity, issue_date=date(2010, 1, 1))
        r = retention.purge_expired(apply=False, today=TODAY)
        assert r["documents"] == 1 and r["applied"] is False
        assert Document.all_objects.filter(pk=d.pk).exists()

    def test_chain_kept_while_any_version_is_recent(self, client_entity, user):
        old = DocumentFactory(client=client_entity, issue_date=date(2010, 1, 1))
        new = old.create_rectification(user, issue_date=date(2025, 1, 1))
        assert retention.purge_expired(apply=True, today=TODAY)["documents"] == 0
        assert Document.all_objects.filter(pk__in=[old.pk, new.pk]).count() == 2

    def test_expired_chain_deleted_with_file(self, client_entity, user):
        old = DocumentFactory(client=client_entity, issue_date=date(2010, 1, 1))
        new = old.create_rectification(user)
        storage, name = old.file.storage, old.file.name
        assert storage.exists(name)
        r = retention.purge_expired(apply=True, today=TODAY)
        assert r["documents"] == 2
        assert not Document.all_objects.filter(pk__in=[old.pk, new.pk]).exists()
        assert not storage.exists(name)

    def test_without_issue_date_uses_created_at(self, client_entity):
        DocumentFactory(client=client_entity, issue_date=None)
        assert retention.purge_expired(today=TODAY)["documents"] == 0

    def test_scoped_by_client(self, client_entity):
        other = ClientFactory()
        DocumentFactory(client=other, issue_date=date(2010, 1, 1))
        assert retention.purge_expired(client=client_entity, today=TODAY)["documents"] == 0

    def test_command_is_dry_run_by_default(self, client_entity):
        d = DocumentFactory(client=client_entity, issue_date=date(2010, 1, 1))
        out = StringIO()
        call_command("purge_expired", stdout=out)
        assert "simulacro" in out.getvalue()
        assert Document.all_objects.filter(pk=d.pk).exists()
        call_command("purge_expired", "--apply", stdout=out)
        assert not Document.all_objects.filter(pk=d.pk).exists()


class TestUsage:
    def test_totals_by_model_and_tenant(self, client_entity):
        d = DocumentFactory(client=client_entity)
        ExtractionRunFactory(document=d, client=client_entity, model="haiku", input_tokens=100,
                             output_tokens=10, cost_usd=Decimal("0.001"))
        ExtractionRunFactory(document=d, client=client_entity, model="sonnet", is_fallback=True,
                             input_tokens=200, output_tokens=20, cost_usd=Decimal("0.004"))
        other = DocumentFactory(client=ClientFactory())
        ExtractionRunFactory(document=other, client=other.client, cost_usd=Decimal("9"))
        u = extraction_usage(client_entity)
        assert u["runs"] == 2 and u["documents"] == 1 and u["fallback_runs"] == 1
        assert u["input_tokens"] == 300 and u["cost_usd"] == Decimal("0.005")
        assert u["cost_per_document"] == Decimal("0.005")
        assert [m["model"] for m in u["by_model"]] == ["sonnet", "haiku"]

    def test_empty(self, client_entity):
        u = extraction_usage(client_entity)
        assert u["runs"] == 0 and u["cost_usd"] == 0 and u["cost_per_document"] == 0

    def test_in_dashboard_metrics(self, user, client_entity):
        d = DocumentFactory(client=client_entity)
        ExtractionRunFactory(document=d, client=client_entity, cost_usd=Decimal("0.002"))
        m = MetricsService.get_user_metrics(user, date(2000, 1, 1), date(2100, 1, 1))
        assert m["extraction"]["cost_usd"] == 0.002

    def test_command(self, client_entity):
        out = StringIO()
        call_command("extraction_cost", stdout=out)
        assert "Coste" in out.getvalue()


class TestProcessingLog:
    def test_summary_line_has_ids_but_no_personal_data(self, client_entity, caplog):
        from documents.services import processing
        d = DocumentFactory(client=client_entity, company__name="Empresa Secreta SL")
        ExtractionRunFactory(document=d, client=client_entity, cost_usd=Decimal("0.001"))
        with caplog.at_level(logging.INFO, logger="documents.services.processing"):
            processing._log_summary(d.pk, "processed")
        msg = caplog.text
        assert f"document={d.pk}" in msg and "outcome=processed" in msg and "cost_usd=0.001" in msg
        assert "Empresa Secreta" not in msg
