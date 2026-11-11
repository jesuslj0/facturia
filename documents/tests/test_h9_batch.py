"""H9: extracción diferida con la Batch API (cliente de Anthropic simulado)."""
from decimal import Decimal as D
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from documents.management.commands import collect_batch, submit_batch  # noqa: F401
from documents.models import Document, ExtractionBatch, ExtractionRun
from documents.services.extraction import batch as b
from documents.services.extraction.base import Usage
from documents.services.extraction.claude import ClaudeExtractor
from documents.services.extraction.pricing import estimate_cost
from documents.tests.fakes import make_result
from documents.tests.test_processing import client_a, new_doc, pdf  # noqa: F401

pytestmark = pytest.mark.django_db


class FakeBatches:
    def __init__(self, results=None, ended=True, fail_create=False):
        self.created, self.results_by_id, self.ended, self.fail_create = [], results or {}, ended, fail_create

    def create(self, requests):
        if self.fail_create:
            raise RuntimeError("api caída")
        self.created.append(requests)
        return NS(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id):
        return NS(processing_status="ended" if self.ended else "in_progress")

    def results(self, batch_id):
        return iter(self.results_by_id.get(batch_id, []))


def api(**kw):
    return NS(messages=NS(batches=FakeBatches(**kw)))


def ok_entry(doc, result=None, **over):
    text = (result or make_result()).model_dump_json()
    msg = NS(
        content=[NS(type="text", text=text)], model="claude-haiku-5-5", stop_reason="end_turn",
        usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )
    msg.__dict__.update(over)
    return NS(custom_id=b.custom_id(doc.pk), result=NS(type="succeeded", message=msg))


def bad_entry(doc, kind="errored"):
    return NS(custom_id=b.custom_id(doc.pk), result=NS(type=kind, error=NS(error=NS(type="overloaded_error"))))


@pytest.fixture
def extractor():
    return ClaudeExtractor("claude-haiku-5-5", api_key="x")


class TestParamsAndPricing:
    def test_batch_params_use_same_prompt_and_json_schema(self, extractor):
        from documents.services.extraction.base import ExtractionInput
        p = extractor.batch_params(ExtractionInput(content=pdf(), mime_type="application/pdf"))
        assert p["model"] == "claude-haiku-5-5"
        assert p["output_config"]["format"]["type"] == "json_schema"
        assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert p["messages"][0]["content"][0]["type"] == "document"

    def test_batch_cost_is_half(self):
        u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert estimate_cost("claude-sonnet-5-5", u, batch=True) * 2 == estimate_cost("claude-sonnet-5-5", u)


class TestSubmit:
    def test_submits_and_marks_batched(self, client_a, extractor):
        d1, d2 = new_doc(client_a), new_doc(client_a, status="failed")
        done = new_doc(client_a, status="processed")
        a = api()
        r = b.submit_batches(api_client=a, extractor=extractor)
        assert (r.batches, r.submitted) == (1, 2)
        sent = {x["custom_id"] for x in a.messages.batches.created[0]}
        assert sent == {b.custom_id(d1.pk), b.custom_id(d2.pk)}
        for d in (d1, d2):
            d.refresh_from_db()
            assert d.processing_status == "batched" and d.is_processing
        done.refresh_from_db()
        assert done.processing_status == "processed"
        batch = ExtractionBatch.objects.get()
        assert batch.request_count == 2 and batch.runs.filter(status="running").count() == 2

    def test_api_failure_releases_documents(self, client_a, extractor):
        d = new_doc(client_a)
        with pytest.raises(RuntimeError):
            b.submit_batches(api_client=api(fail_create=True), extractor=extractor)
        d.refresh_from_db()
        assert d.processing_status == "uploaded"
        assert not ExtractionBatch.objects.exists()

    def test_corrupt_file_fails_without_stopping_the_rest(self, client_a, extractor):
        bad = new_doc(client_a, data=b"%PDF-1.4 roto")
        good = new_doc(client_a)
        r = b.submit_batches(api_client=api(), extractor=extractor)
        assert (r.submitted, r.failed) == (1, 1)
        bad.refresh_from_db(); good.refresh_from_db()
        assert bad.processing_status == "failed" and good.processing_status == "batched"

    def test_splits_in_chunks(self, client_a, extractor):
        for _ in range(3):
            new_doc(client_a)
        with patch.object(b, "MAX_REQUESTS_PER_BATCH", 2):
            a = api()
            r = b.submit_batches(api_client=a, extractor=extractor)
        assert r.batches == 2 and [len(x) for x in a.messages.batches.created] == [2, 1]

    def test_filters_by_client_and_limit(self, client_a, extractor):
        other = new_doc(__import__("documents.tests.factories", fromlist=["x"]).ClientFactory())
        mine = [new_doc(client_a) for _ in range(3)]
        r = b.submit_batches(client=client_a, limit=2, api_client=api(), extractor=extractor)
        assert r.submitted == 2
        other.refresh_from_db()
        assert other.processing_status == "uploaded"

    def test_celery_pipeline_ignores_batched_documents(self, client_a, extractor):
        from documents.services import processing
        d = new_doc(client_a)
        b.submit_batches(api_client=api(), extractor=extractor)
        assert processing.claim_document(d.pk) is None
        assert processing.enqueue_processing(d) is False


class TestCollect:
    def submit(self, client_a, extractor, n=1, **kw):
        docs = [new_doc(client_a) for _ in range(n)]
        a = api(**kw)
        b.submit_batches(api_client=a, extractor=extractor)
        return docs, a

    def test_not_ended_leaves_everything(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor, ended=False)
        r = b.collect_batches(api_client=a)
        assert r.pending_batches == 1 and r.applied == 0
        d.refresh_from_db()
        assert d.processing_status == "batched"

    def test_applies_result_with_half_price(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor)
        a.messages.batches.results_by_id["msgbatch_1"] = [ok_entry(d)]
        r = b.collect_batches(api_client=a)
        assert (r.collected_batches, r.applied, r.requeued) == (1, 1, 0)
        d.refresh_from_db()
        assert d.processing_status == "processed"
        assert d.document_number == "F-001" and d.total_amount == D("121.00")
        assert d.tax_lines.count() == 1
        run = d.extraction_runs.get()
        assert run.status == "succeeded" and run.batch.status == "collected"
        assert run.cost_usd == estimate_cost("claude-haiku-5-5", Usage(1000, 200), batch=True)

    def test_collection_is_idempotent(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor)
        a.messages.batches.results_by_id["msgbatch_1"] = [ok_entry(d)]
        b.collect_batches(api_client=a)
        r = b.collect_batches(api_client=a)
        assert r.collected_batches == 0 and d.extraction_runs.count() == 1

    @pytest.mark.parametrize("kind", ["errored", "expired", "canceled"])
    def test_failed_entry_goes_back_to_normal_pipeline(self, client_a, extractor, kind):
        (d,), a = self.submit(client_a, extractor)
        a.messages.batches.results_by_id["msgbatch_1"] = [bad_entry(d, kind)]
        with patch("documents.tasks.process_document.delay") as delay, \
                patch("django.db.transaction.on_commit", lambda fn: fn()):
            r = b.collect_batches(api_client=a)
        assert r.requeued == 1 and r.applied == 0
        run = d.extraction_runs.get()
        assert run.status == "failed" and run.error_code == f"batch_{kind}"
        d.refresh_from_db()
        assert d.processing_status == "queued"
        delay.assert_called_once_with(d.pk)

    def test_invalid_json_is_requeued(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor)
        entry = ok_entry(d)
        entry.result.message.content = [NS(type="text", text="{no es json")]
        a.messages.batches.results_by_id["msgbatch_1"] = [entry]
        with patch("documents.tasks.process_document.delay"), patch("django.db.transaction.on_commit", lambda fn: fn()):
            r = b.collect_batches(api_client=a)
        assert r.requeued == 1
        assert d.extraction_runs.get().error_code == "invalid_response"

    def test_missing_result_is_requeued(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor)
        with patch("documents.tasks.process_document.delay"), patch("django.db.transaction.on_commit", lambda fn: fn()):
            r = b.collect_batches(api_client=a)
        assert r.requeued == 1 and d.extraction_runs.get().error_code == "missing_result"

    def test_document_changed_meanwhile_is_not_overwritten(self, client_a, extractor):
        (d,), a = self.submit(client_a, extractor)
        Document.all_objects.filter(pk=d.pk).update(processing_status="processed", document_number="MANUAL")
        a.messages.batches.results_by_id["msgbatch_1"] = [ok_entry(d)]
        r = b.collect_batches(api_client=a)
        assert r.applied == 0
        d.refresh_from_db()
        assert d.document_number == "MANUAL"

    def test_no_batches_does_not_need_api_key(self, settings):
        settings.ANTHROPIC_API_KEY = None
        assert b.collect_batches().collected_batches == 0

    def test_usage_report_includes_batch_runs(self, client_a, extractor):
        from documents.services.usage import extraction_usage
        (d,), a = self.submit(client_a, extractor)
        a.messages.batches.results_by_id["msgbatch_1"] = [ok_entry(d)]
        b.collect_batches(api_client=a)
        assert extraction_usage(client_a)["runs"] == 1


class TestCommands:
    def test_dry_run(self, client_a):
        from io import StringIO
        from django.core.management import call_command
        new_doc(client_a)
        out = StringIO()
        call_command("submit_batch", "--dry-run", stdout=out)
        assert "1 documentos" in out.getvalue()
        assert Document.all_objects.filter(processing_status="batched").count() == 0

    def test_collect_command_without_batches(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("collect_batch", stdout=out)
        assert "Lotes recogidos: 0" in out.getvalue()
