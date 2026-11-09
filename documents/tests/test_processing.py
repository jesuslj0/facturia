import io
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from pypdf import PdfWriter

from documents.models import Company, Document, DocumentAuditLog, InvoiceLine, TaxBreakdown
from documents.services import processing
from documents.services.extraction import (
    InvalidRequestError, InvalidResponseError, ProviderTimeoutError, RateLimitedError,
)
from documents.services.extraction.schemas import Line, TaxLine
from documents.tasks import process_document
from documents.tests import factories as f
from documents.tests.fakes import FakeExtractor, make_result

pytestmark = pytest.mark.django_db


def pdf(pages=1):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=100, height=100)
    b = io.BytesIO(); w.write(b)
    return b.getvalue()


@pytest.fixture
def client_a():
    # el NIF del destinatario de make_result() es A87654323 → gasto (out)
    return f.ClientFactory(tax_id="A87654323")


def new_doc(client, status="uploaded", data=None, **kw):
    """Documento recién subido: aún sin datos extraídos."""
    return f.DocumentFactory(
        client=client, company=None, processing_status=status, source="upload",
        file=SimpleUploadedFile("up.pdf", data or pdf()), document_number=None, issue_date=None,
        base_amount=None, tax_amount=None, tax_percentage=None, total_amount=None, flow="unknown", **kw,
    )


def run(doc, primary=None, fallback=None):
    return processing.run_processing(doc.pk, extractor=primary or FakeExtractor("claude-haiku-5-5"), fallback=fallback)


class TestClaim:
    @pytest.mark.parametrize("st", ["uploaded", "queued", "failed"])
    def test_claimable_states(self, client_a, st):
        d = new_doc(client_a, st)
        assert processing.claim_document(d.pk).processing_status == "processing"

    def test_second_claim_is_refused(self, client_a):
        d = new_doc(client_a)
        assert processing.claim_document(d.pk) is not None
        assert processing.claim_document(d.pk) is None

    def test_processed_approved_and_archived_are_not_claimed(self, client_a):
        assert processing.claim_document(new_doc(client_a, "processed").pk) is None
        assert processing.claim_document(new_doc(client_a, status_extra := "uploaded").pk) is not None
        a = new_doc(client_a); Document.all_objects.filter(pk=a.pk).update(status="approved")
        assert processing.claim_document(a.pk) is None
        b = new_doc(client_a); Document.all_objects.filter(pk=b.pk).update(is_archived=True)
        assert processing.claim_document(b.pk) is None

    def test_stale_processing_is_reclaimed_but_fresh_is_not(self, client_a, settings):
        d = new_doc(client_a)
        assert processing.claim_document(d.pk) is not None          # worker A
        assert processing.claim_document(d.pk) is None              # worker B justo después: no
        Document.all_objects.filter(pk=d.pk).update(
            processing_started_at=timezone.now() - timedelta(minutes=settings.EXTRACTION_STALE_MINUTES + 1))
        assert processing.claim_document(d.pk) is not None          # worker A murió: se reclama
        assert processing.claim_document(d.pk) is None              # y vuelve a estar «fresco»

    def test_legacy_processing_without_timestamp_is_reclaimed(self, client_a):
        assert processing.claim_document(new_doc(client_a, "processing").pk) is not None


class TestEnqueue:
    def test_marks_queued_and_delays_on_commit(self, client_a, django_capture_on_commit_callbacks):
        d = new_doc(client_a)
        with patch.object(process_document, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                assert processing.enqueue_processing(d) is True
            delay.assert_called_once_with(d.pk)
        d.refresh_from_db()
        assert d.processing_status == "queued"

    def test_does_not_enqueue_processed_unless_forced(self, client_a, django_capture_on_commit_callbacks):
        d = new_doc(client_a, "processed")
        with patch.object(process_document, "delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                assert processing.enqueue_processing(d) is False
                assert processing.enqueue_processing(d, force=True) is True
            assert delay.call_count == 1


class TestRunProcessing:
    def test_success_applies_everything(self, client_a):
        res = make_result(
            tax_lines=[TaxLine(kind="vat", rate="21", base="100.00", amount="21.00")],
            lines=[Line(description="Servicio", quantity="1", unit_price="100", tax_rate="21", amount="100.00")],
            iban="es91 2100 0418 4502 0005 1332",
        )
        d = new_doc(client_a)
        df = f.DocumentFileFactory(document=d, mime_type="", sha256="e" * 64)
        assert run(d, FakeExtractor("claude-haiku-5-5", [res])) == "processed"
        d.refresh_from_db()
        assert d.processing_status == "processed" and d.status == "pending" and not d.is_auto_approved
        assert (d.document_type, d.document_number, str(d.issue_date)) == ("invoice", "F-001", "2026-03-15")
        assert (d.base_amount, d.tax_amount, d.tax_percentage, d.total_amount) == (D("100.00"), D("21.00"), D("21"), D("121.00"))
        assert (d.flow, d.flow_source, d.total_source, d.currency, d.iban) == ("out", "auto", "explicit", "EUR", "ES9121000418450200051332")
        assert d.company.name == "Proveedor SL" and d.company.tax_id == "B12345674" and d.company.is_provider
        assert d.confidence["confianza_extraccion"] == 0.95 and d.confidence_global == D("0.9500")
        assert d.review_level == "recommended"  # nunca "auto" hasta H5
        t = d.tax_lines.get(); assert (t.kind, t.rate, t.amount) == ("vat", D("21"), D("21.00"))
        assert d.lines.get().description == "Servicio"
        log = d.audit_logs.get(action="extracted")
        assert log.changes["fallback"] is False and log.changes["flow"] == "out"
        df.refresh_from_db(); assert (df.mime_type, df.page_count) == ("application/pdf", 1)
        assert d.extraction_runs.get().status == "succeeded"

    def test_income_invoice_creates_customer(self):
        c = f.ClientFactory(tax_id="B12345674")  # el cliente es el emisor
        d = new_doc(c)
        assert run(d) == "processed"
        d.refresh_from_db()
        assert d.flow == "in" and d.company.is_customer and d.company.tax_id == "A87654323"

    @pytest.mark.parametrize("over", [
        dict(total_amount=None), dict(issue_date=None), dict(document_type="other"),
    ])
    def test_incomplete_extraction_requires_review(self, client_a, over):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(**over)]))
        d.refresh_from_db()
        assert d.review_level == "required" and d.processing_status == "processed"

    def test_unknown_flow_requires_review(self):
        d = new_doc(f.ClientFactory(tax_id="Z99999999"))
        run(d)
        d.refresh_from_db()
        assert d.flow == "unknown" and d.review_level == "required"

    def test_no_counterparty_leaves_company_empty(self, client_a):
        from documents.services.extraction.schemas import Party
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(issuer=Party(name=None, tax_id=None, address=None))]))
        d.refresh_from_db()
        assert d.company is None and d.processing_status == "processed"

    def test_reuses_existing_company_by_tax_id(self, client_a):
        existing = f.CompanyFactory(client=client_a, tax_id="B12345674", name="Nombre antiguo", is_provider=False)
        d = new_doc(client_a)
        run(d)
        d.refresh_from_db(); existing.refresh_from_db()
        assert d.company_id == existing.pk and existing.is_provider is True
        assert Company.objects.filter(client=client_a).count() == 1

    def test_fallback_used_on_low_confidence(self, client_a):
        low = make_result(); low.confidence.overall = 0.4
        d = new_doc(client_a)
        run(d, FakeExtractor("haiku", [low]), FakeExtractor("sonnet"))
        d.refresh_from_db()
        assert d.audit_logs.get(action="extracted").changes["fallback"] is True
        assert d.extraction_runs.count() == 2 and d.confidence_global == D("0.9500")

    def test_idempotent_second_run_is_skipped(self, client_a):
        d = new_doc(client_a)
        assert run(d) == "processed"
        assert run(d) == "skipped"
        assert d.extraction_runs.count() == 1

    def test_force_reprocess_replaces_breakdown_and_lines(self, client_a):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(lines=[Line(description="a", quantity="1", unit_price=None, tax_rate=None, amount="1")])]))
        Document.all_objects.filter(pk=d.pk).update(processing_status="uploaded")
        run(d, FakeExtractor("m", [make_result(tax_lines=[
            TaxLine(kind="vat", rate="10", base="50", amount="5"), TaxLine(kind="withholding", rate="15", base="50", amount="7.5")], lines=[])]))
        assert sorted(d.tax_lines.values_list("kind", "rate")) == [("vat", D("10.00")), ("withholding", D("15.00"))]
        assert d.lines.count() == 0

    def test_duplicate_rates_are_aggregated_and_negative_withholding_made_positive(self, client_a):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(tax_lines=[
            TaxLine(kind="vat", rate="21", base="60", amount="12.60"), TaxLine(kind="vat", rate="21", base="40", amount="8.40"),
            TaxLine(kind="withholding", rate="15", base="100", amount="-15"),
            TaxLine(kind="vat", rate="900", base="1", amount="1")])]))  # tipo imposible: se ignora
        rows = {(t.kind, t.rate): t.amount for t in d.tax_lines.all()}
        assert rows == {("vat", D("21.00")): D("21.00"), ("withholding", D("15.00")): D("15.00")}
        d.refresh_from_db(); assert d.tax_amount == D("21.00")

    def test_absurd_amounts_do_not_break_saving(self, client_a):
        d = new_doc(client_a)
        assert run(d, FakeExtractor("m", [make_result(total_amount="99999999999", base_amount="1")])) == "processed"
        d.refresh_from_db(); assert d.total_amount is None and d.review_level == "required"

    def test_multiple_vat_rates_leave_percentage_empty(self, client_a):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(tax_lines=[
            TaxLine(kind="vat", rate="21", base="100", amount="21"), TaxLine(kind="vat", rate="10", base="100", amount="10")])]))
        d.refresh_from_db(); assert d.tax_percentage is None and d.tax_amount == D("31.00")


class TestFailures:
    def test_retryable_error_requeues_and_reraises(self, client_a):
        d = new_doc(client_a)
        with pytest.raises(RateLimitedError):
            run(d, FakeExtractor("m", [RateLimitedError("429", retry_after=7)]))
        d.refresh_from_db()
        assert d.processing_status == "queued"
        assert d.extraction_runs.get().error_code == "rate_limited"
        assert processing.claim_document(d.pk) is not None  # se puede reintentar

    def test_non_retryable_error_marks_failed(self, client_a):
        d = new_doc(client_a)
        assert run(d, FakeExtractor("m", [InvalidRequestError("mal")])) == "failed"
        d.refresh_from_db()
        assert d.processing_status == "failed"
        assert d.audit_logs.get().changes == {"failed": True, "error": "invalid_request"}

    def test_unusable_response_without_fallback_fails(self, client_a):
        d = new_doc(client_a)
        assert run(d, FakeExtractor("m", [InvalidResponseError("x")])) == "failed"

    def test_corrupt_file_fails_without_calling_provider(self, client_a):
        d = new_doc(client_a, data=b"%PDF-1.4 roto")
        ex = FakeExtractor()
        assert run(d, ex) == "failed"
        assert ex.calls == []
        r = d.extraction_runs.get()
        assert (r.status, r.error_code) == ("failed", "corrupt_file")
        d.refresh_from_db(); assert d.processing_status == "failed"

    def test_too_many_pages_reports_clear_error(self, client_a, settings):
        settings.EXTRACTION_MAX_PAGES = 2
        d = new_doc(client_a, data=pdf(3))
        assert run(d) == "failed"
        r = d.extraction_runs.get()
        assert r.error_code == "too_many_pages" and "3 páginas" in r.error_message

    def test_unexpected_exception_does_not_leave_document_stuck(self, client_a):
        class Boom:
            model = "m"
            def extract(self, inp): raise RuntimeError("bug")
        d = new_doc(client_a)
        assert run(d, Boom()) == "failed"
        d.refresh_from_db(); assert d.processing_status == "failed"
        assert d.extraction_runs.get().error_code == "unexpected_error"

    def test_failed_document_can_be_retried(self, client_a):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [InvalidRequestError("mal")]))
        assert run(d) == "processed"


class TestRetryDelay:
    def test_exponential_with_cap_and_jitter(self, settings):
        settings.EXTRACTION_RETRY_BASE_SECONDS, settings.EXTRACTION_RETRY_MAX_SECONDS = 30, 900
        for retries, expected in [(0, 30), (1, 60), (2, 120), (5, 900), (9, 900)]:
            vals = [processing.retry_delay(retries) for _ in range(50)]
            assert expected * 0.79 <= min(vals) and max(vals) <= expected * 1.21

    def test_honors_retry_after_as_minimum(self):
        assert processing.retry_delay(0, RateLimitedError("x", retry_after=600)) >= 600
        assert processing.retry_delay(0, ProviderTimeoutError("t")) < 40


class TestCeleryTask:
    def test_task_runs_pipeline(self, client_a):
        d = new_doc(client_a)
        with patch("documents.services.processing.build_extractors", return_value=(FakeExtractor("m"), None)):
            res = process_document.apply(args=[d.pk])
        assert res.result == "processed"

    def test_retryable_error_is_retried_then_marked_failed(self, client_a, settings):
        settings.EXTRACTION_MAX_RETRIES = 2
        d = new_doc(client_a)
        err = RateLimitedError("429")
        with patch("documents.services.processing.run_processing", side_effect=err) as rp, \
             patch("documents.tasks.processing.retry_delay", return_value=0):
            process_document.apply(args=[d.pk])
        assert rp.call_count == 3  # intento inicial + 2 reintentos
        d.refresh_from_db()
        assert d.processing_status == "failed"
        assert d.audit_logs.filter(changes__error="rate_limited_retries_exhausted").exists()

    def test_unknown_document_is_skipped(self):
        assert process_document.apply(args=[999999]).result == "skipped"


def test_enqueue_command(client_a, django_capture_on_commit_callbacks):
    from django.core.management import call_command
    a, b = new_doc(client_a), new_doc(client_a, "processed")
    with patch.object(process_document, "delay") as delay, django_capture_on_commit_callbacks(execute=True):
        call_command("enqueue_extraction")
    delay.assert_called_once_with(a.pk)


def test_enqueue_command_sync(client_a):
    from django.core.management import call_command
    d = new_doc(client_a)
    with patch("documents.services.processing.build_extractors", return_value=(FakeExtractor("m"), None)):
        call_command("enqueue_extraction", "--sync")
    d.refresh_from_db(); assert d.processing_status == "processed"


class TestValidationIntegration:
    """Validación determinista + política de revisión dentro del procesado."""

    def test_issues_are_persisted_and_logged(self, client_a):
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(total_amount="999")]))
        d.refresh_from_db()
        assert d.review_level == "required" and d.status == "pending"
        assert {i["code"] for i in d.validation_issues} == {"totals_mismatch"}
        assert d.audit_logs.get(action="extracted").changes["issues"] == ["totals_mismatch"]

    def test_clean_document_has_no_issues(self, client_a):
        d = new_doc(client_a)
        run(d)
        d.refresh_from_db()
        assert d.validation_issues == [] and d.review_level == "recommended" and d.status == "pending"

    def test_auto_approve_when_enabled_and_clean(self, client_a, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        d = new_doc(client_a)
        run(d)
        d.refresh_from_db()
        assert (d.status, d.review_level, d.is_auto_approved) == ("approved", "auto", True)
        assert d.approved_by is None and d.display_review_level == "Auto"
        assert d.audit_logs.filter(action="approved", changes__auto=True).count() == 1

    def test_auto_approve_never_happens_with_validation_errors(self, client_a, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        d = new_doc(client_a)
        run(d, FakeExtractor("m", [make_result(total_amount="999")]))
        d.refresh_from_db()
        assert d.status == "pending" and not d.is_auto_approved

    def test_auto_approve_off_by_default(self, client_a):
        d = new_doc(client_a)
        run(d)
        d.refresh_from_db()
        assert d.status == "pending"

    def test_invalid_tax_id_triggers_fallback_and_second_opinion_wins(self, client_a):
        from documents.services.extraction.schemas import Party
        bad = make_result(issuer=Party(name="Proveedor SL", tax_id="B12345678", address=None))  # dígito mal leído
        d = new_doc(client_a)
        run(d, FakeExtractor("haiku", [bad]), FakeExtractor("sonnet"))
        d.refresh_from_db()
        assert d.extraction_runs.count() == 2
        assert d.company.tax_id == "B12345674" and d.validation_issues == []
        assert d.audit_logs.get(action="extracted").changes["fallback"] is True

    def test_fallback_not_used_when_problem_is_not_model_fixable(self, client_a):
        # Cliente sin NIF → flow_unknown (no lo arregla otro modelo): no se gasta Sonnet
        c = f.ClientFactory(tax_id=None)
        d = new_doc(c)
        fb = FakeExtractor("sonnet")
        run(d, FakeExtractor("haiku"), fb)
        assert fb.calls == []
        d.refresh_from_db()
        assert {i["code"] for i in d.validation_issues} == {"flow_unknown"} and d.review_level == "required"

    def test_still_wrong_after_fallback_requires_review(self, client_a):
        bad = make_result(total_amount="999")
        d = new_doc(client_a)
        run(d, FakeExtractor("haiku", [bad]), FakeExtractor("sonnet", [bad]))
        d.refresh_from_db()
        assert d.extraction_runs.count() == 2 and d.review_level == "required"

    def test_duplicate_by_issuer_and_number_is_flagged_not_failed(self, client_a):
        co = f.CompanyFactory(client=client_a, tax_id="B12345674")
        orig = f.DocumentFactory(client=client_a, company=co, document_number="F-001", flow="out")
        d = new_doc(client_a)
        fb = FakeExtractor("sonnet")
        assert run(d, FakeExtractor("haiku"), fb) == "processed"
        d.refresh_from_db()
        dup = next(i for i in d.validation_issues if i["code"] == "duplicate_document")
        assert f"#{orig.pk}" in dup["message"] and d.review_level == "required"
        assert fb.calls == []          # un duplicado no se arregla con otro modelo
        assert d.status == "pending"   # nunca se aprueba solo

    def test_reprocessing_does_not_flag_itself_as_duplicate(self, client_a):
        d = new_doc(client_a)
        run(d)
        Document.all_objects.filter(pk=d.pk).update(processing_status="uploaded")
        run(d)
        d.refresh_from_db()
        assert d.validation_issues == []
