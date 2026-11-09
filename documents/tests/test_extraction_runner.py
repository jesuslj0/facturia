from decimal import Decimal as D

import pytest

from documents.services.extraction import (
    InvalidResponseError, ProviderTimeoutError, RateLimitedError, RefusedError, run_extraction,
)
from documents.services.extraction.prompts import PROMPT_VERSION
from documents.tests import factories as f
from documents.tests.fakes import FakeExtractor, make_result

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.4 x"


@pytest.fixture
def doc():
    c = f.ClientFactory(tax_id="A87654321")
    return f.DocumentFactory(client=c)


def low_conf():
    r = make_result()
    r.confidence.overall = 0.5
    return r


def run(doc, primary, fallback=None, **kw):
    return run_extraction(doc, PDF, "application/pdf", extractor=primary, fallback=fallback, **kw)


def test_success_records_run_with_tokens_cost_and_raw(doc):
    out = run(doc, FakeExtractor("claude-haiku-5-5"))
    assert not out.used_fallback and out.normalized.flow == "out"
    r = doc.extraction_runs.get()
    assert (r.status, r.attempt, r.is_fallback, r.model) == ("succeeded", 1, False, "claude-haiku-5-5")
    assert (r.input_tokens, r.output_tokens) == (1000, 200)
    assert r.cost_usd == D("0.000200") and r.confidence == D("0.9500")
    assert r.raw_response["parsed"]["document_number"] == "F-001" and r.raw_response["request_id"] == "req_fake"
    assert r.prompt_version == PROMPT_VERSION and r.started_at and r.finished_at


def test_client_context_is_sent_to_extractor(doc):
    p = FakeExtractor()
    run(doc, p)
    assert p.calls[0].client_tax_id == "A87654321" and p.calls[0].client_name == doc.client.name


def test_high_confidence_does_not_call_fallback(doc):
    fb = FakeExtractor("claude-sonnet-5-5")
    run(doc, FakeExtractor(), fb)
    assert fb.calls == [] and doc.extraction_runs.count() == 1


def test_low_confidence_triggers_fallback_and_uses_it(doc):
    p, fb = FakeExtractor("haiku", [low_conf()]), FakeExtractor("sonnet")
    out = run(doc, p, fb)
    assert out.used_fallback and out.run.model == "sonnet" and out.run.is_fallback
    runs = list(doc.extraction_runs.order_by("attempt"))
    assert [(r.model, r.attempt, r.is_fallback, r.status) for r in runs] == [
        ("haiku", 1, False, "succeeded"), ("sonnet", 2, True, "succeeded")]


def test_invalid_response_triggers_fallback(doc):
    p = FakeExtractor("haiku", [InvalidResponseError("mal")])
    out = run(doc, p, FakeExtractor("sonnet"))
    assert out.used_fallback
    first = doc.extraction_runs.get(attempt=1)
    assert first.status == "failed" and first.error_code == "invalid_response"


def test_refusal_triggers_fallback(doc):
    assert run(doc, FakeExtractor("haiku", [RefusedError("no")]), FakeExtractor("sonnet")).used_fallback


def test_validator_problems_trigger_fallback(doc):
    seen = []
    def validator(n):
        seen.append(n)
        return ["cuadre"] if len(seen) == 1 else []
    out = run(doc, FakeExtractor("haiku"), FakeExtractor("sonnet"), validator=validator)
    assert out.used_fallback and len(seen) == 1


def test_fallback_fails_but_primary_ok_keeps_primary(doc):
    p = FakeExtractor("haiku", [low_conf()])
    fb = FakeExtractor("sonnet", [InvalidResponseError("mal")])
    out = run(doc, p, fb)
    assert not out.used_fallback and out.run.model == "haiku"
    assert doc.extraction_runs.get(attempt=2).status == "failed"


@pytest.mark.parametrize("exc", [RateLimitedError("429", retry_after=5), ProviderTimeoutError("t")])
def test_retryable_errors_do_not_use_fallback_and_are_reraised(doc, exc):
    fb = FakeExtractor("sonnet")
    with pytest.raises(type(exc)):
        run(doc, FakeExtractor("haiku", [exc]), fb)
    assert fb.calls == []
    r = doc.extraction_runs.get()
    assert r.status == "failed" and r.error_code == exc.code


def test_primary_fails_without_fallback_raises(doc):
    with pytest.raises(InvalidResponseError):
        run(doc, FakeExtractor("haiku", [InvalidResponseError("mal")]), None)
    assert doc.extraction_runs.count() == 1


def test_both_fail_raises_and_records_both(doc):
    with pytest.raises(InvalidResponseError):
        run(doc, FakeExtractor("h", [InvalidResponseError("a")]), FakeExtractor("s", [InvalidResponseError("b")]))
    assert doc.extraction_runs.filter(status="failed").count() == 2


def test_failed_run_stores_usage_of_billed_attempt(doc):
    from documents.services.extraction import Usage
    err = InvalidResponseError("mal", usage=Usage(input_tokens=500, output_tokens=50))
    with pytest.raises(InvalidResponseError):
        run(doc, FakeExtractor("claude-haiku-5-5", [err]))
    r = doc.extraction_runs.get()
    assert (r.input_tokens, r.output_tokens) == (500, 50) and r.cost_usd == D("0.000075")


def test_attempts_keep_counting_across_calls(doc):
    run(doc, FakeExtractor())
    run(doc, FakeExtractor())
    assert list(doc.extraction_runs.order_by("attempt").values_list("attempt", flat=True)) == [1, 2]


def test_build_extractors_from_settings(settings):
    from documents.services.extraction import build_extractors
    settings.ANTHROPIC_API_KEY = "sk-test"
    p, fb = build_extractors()
    assert (p.model, fb.model) == ("claude-haiku-5-5", "claude-sonnet-5-5")
    settings.EXTRACTION_FALLBACK_MODEL = ""
    assert build_extractors()[1] is None
