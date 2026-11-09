import base64

import anthropic
import httpx2 as httpx
import pytest

from documents.services.extraction import (
    ConfigurationError, ExtractionInput, InvalidRequestError, InvalidResponseError,
    ProviderTimeoutError, ProviderUnavailableError, RateLimitedError, RefusedError,
    UnsupportedInputError,
)
from documents.services.extraction.claude import ClaudeExtractor
from documents.services.extraction.prompts import PROMPT_VERSION
from documents.services.extraction.schemas import ExtractionResult
from documents.tests.fakes import FakeAnthropic, fake_response, make_result

PDF = ExtractionInput(content=b"%PDF-1.4 x", mime_type="application/pdf", client_name="Mi Empresa", client_tax_id="A87654321")


def _http_error(cls, status, headers=None):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req, headers=headers or {}), body=None)


def extractor(fake, **kw):
    return ClaudeExtractor("claude-haiku-5-5", client=fake, **kw)


class TestRequestShape:
    def test_pdf_goes_as_document_block_with_cached_system_and_schema(self):
        fake = FakeAnthropic(fake_response(make_result()))
        out = extractor(fake, effort="low", max_tokens=4000).extract(PDF)
        call = fake.calls[0]
        assert call["model"] == "claude-haiku-5-5" and call["max_tokens"] == 4000
        assert call["output_format"] is ExtractionResult
        assert call["output_config"] == {"effort": "low"}
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
        # nada variable (NIF del cliente) en el system cacheado
        assert "A87654321" not in call["system"][0]["text"]
        content = call["messages"][0]["content"]
        assert content[0]["type"] == "document" and content[0]["source"]["media_type"] == "application/pdf"
        assert base64.b64decode(content[0]["source"]["data"]) == PDF.content
        assert content[1]["type"] == "text" and "A87654321" in content[1]["text"]
        assert out.prompt_version == PROMPT_VERSION

    def test_image_block_and_no_forbidden_params(self):
        fake = FakeAnthropic(fake_response(make_result()))
        extractor(fake).extract(ExtractionInput(content=b"\xff\xd8\xff", mime_type="image/jpeg"))
        call = fake.calls[0]
        assert call["messages"][0]["content"][0]["type"] == "image"
        # Modelos 5.5: sin temperature/top_p, sin tool_choice forzado, sin thinking explícito
        for forbidden in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):
            assert forbidden not in call

    def test_unsupported_mime(self):
        with pytest.raises(UnsupportedInputError):
            extractor(FakeAnthropic()).extract(ExtractionInput(content=b"x", mime_type="image/heic"))


class TestSuccess:
    def test_returns_result_usage_and_request_id(self):
        r = make_result()
        out = extractor(FakeAnthropic(fake_response(r))).extract(PDF)
        assert out.result == r and out.model == "claude-haiku-5-5"
        assert (out.usage.input_tokens, out.usage.output_tokens) == (1200, 300)
        assert out.request_id == "req_1" and out.stop_reason == "end_turn"


class TestFailures:
    def test_missing_api_key(self):
        with pytest.raises(ConfigurationError):
            ClaudeExtractor("claude-haiku-5-5", api_key=None).extract(PDF)

    def test_no_parsed_output_is_invalid_response_and_keeps_usage(self):
        with pytest.raises(InvalidResponseError) as ei:
            extractor(FakeAnthropic(fake_response(parsed=None))).extract(PDF)
        assert ei.value.fallback_eligible and ei.value.usage.input_tokens == 1200

    def test_truncated_output(self):
        with pytest.raises(InvalidResponseError, match="max_tokens"):
            extractor(FakeAnthropic(fake_response(make_result(), stop_reason="max_tokens"))).extract(PDF)

    def test_refusal(self):
        with pytest.raises(RefusedError) as ei:
            extractor(FakeAnthropic(fake_response(None, stop_reason="refusal"))).extract(PDF)
        assert ei.value.fallback_eligible and not ei.value.retryable

    def test_schema_validation_error(self):
        try:
            ExtractionResult.model_validate({"document_type": "nope"})
        except Exception as ve:
            err = ve
        with pytest.raises(InvalidResponseError):
            extractor(FakeAnthropic(error=err)).extract(PDF)

    def test_rate_limit_is_retryable_with_retry_after(self):
        err = _http_error(anthropic.RateLimitError, 429, {"retry-after": "17"})
        with pytest.raises(RateLimitedError) as ei:
            extractor(FakeAnthropic(error=err)).extract(PDF)
        assert ei.value.retryable and ei.value.retry_after == 17.0 and not ei.value.fallback_eligible

    def test_timeout_is_retryable(self):
        err = anthropic.APITimeoutError(request=httpx.Request("POST", "https://x"))
        with pytest.raises(ProviderTimeoutError) as ei:
            extractor(FakeAnthropic(error=err)).extract(PDF)
        assert ei.value.retryable

    def test_connection_error_is_retryable(self):
        err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        with pytest.raises(ProviderUnavailableError):
            extractor(FakeAnthropic(error=err)).extract(PDF)

    @pytest.mark.parametrize("status", [500, 503, 529])
    def test_server_errors_are_retryable(self, status):
        err = _http_error(anthropic.APIStatusError, status)
        with pytest.raises(ProviderUnavailableError):
            extractor(FakeAnthropic(error=err)).extract(PDF)

    def test_bad_request_not_retryable(self):
        err = _http_error(anthropic.BadRequestError, 400)
        with pytest.raises(InvalidRequestError) as ei:
            extractor(FakeAnthropic(error=err)).extract(PDF)
        assert not ei.value.retryable and not ei.value.fallback_eligible

    def test_auth_error_is_configuration(self):
        err = _http_error(anthropic.AuthenticationError, 401)
        with pytest.raises(ConfigurationError):
            extractor(FakeAnthropic(error=err)).extract(PDF)

    def test_error_messages_do_not_leak_content(self):
        err = _http_error(anthropic.RateLimitError, 429)
        with pytest.raises(RateLimitedError) as ei:
            extractor(FakeAnthropic(error=err)).extract(PDF)
        assert "%PDF" not in str(ei.value)
