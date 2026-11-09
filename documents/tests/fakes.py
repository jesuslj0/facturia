"""Dobles de prueba para la extracción (sin red ni claves)."""
from types import SimpleNamespace

from documents.services.extraction import ExtractionOutput, ExtractionResult, Usage
from documents.services.extraction.prompts import PROMPT_VERSION
from documents.services.extraction.schemas import Confidence, Party, TaxLine


def make_result(**over) -> ExtractionResult:
    base = dict(
        document_type="invoice",
        issuer=Party(name="Proveedor SL", tax_id="B12345678", address=None),
        recipient=Party(name="Mi Empresa SA", tax_id="A87654321", address=None),
        document_number="F-001",
        issue_date="2026-03-15",
        currency="EUR",
        base_amount="100.00",
        tax_lines=[TaxLine(kind="vat", rate="21", base="100.00", amount="21.00")],
        total_amount="121.00",
        iban=None,
        lines=[],
        confidence=Confidence(overall=0.95, issuer=0.95, document_number=0.95, date=0.95, amounts=0.95, total=0.95),
        notes=None,
    )
    base.update(over)
    return ExtractionResult(**base)


class FakeExtractor:
    """Devuelve (o lanza) lo que se le indique, en orden, y registra las llamadas."""

    def __init__(self, model="fake-primary", responses=None):
        self.model = model
        self.responses = list(responses or [make_result()])
        self.calls = []

    def extract(self, inp):
        self.calls.append(inp)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return ExtractionOutput(
            result=item, model=self.model, prompt_version=PROMPT_VERSION,
            usage=Usage(input_tokens=1000, output_tokens=200), request_id="req_fake", stop_reason="end_turn",
        )


class FakeAnthropic:
    """Imita `anthropic.Anthropic().messages.parse` para probar ClaudeExtractor."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def fake_response(parsed=None, stop_reason="end_turn", usage=None, model="claude-haiku-5-5"):
    usage = usage or SimpleNamespace(
        input_tokens=1200, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, usage=usage, model=model, _request_id="req_1")
