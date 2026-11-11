"""Pruebas contra la API REAL de Claude. Excluidas por defecto.

    pytest -m live_api -s documents/tests/test_extraction_live.py

Cuestan dinero (céntimos) y requieren ANTHROPIC_API_KEY en el entorno/.env.
Usan los documentos de ejemplo versionados en media/documents/.
"""
from pathlib import Path

import pytest
from django.conf import settings

from documents.services.extraction import ExtractionInput
from documents.services.extraction.claude import ClaudeExtractor
from documents.services.extraction.normalize import normalize
from documents.services.extraction.pricing import estimate_cost

pytestmark = pytest.mark.live_api
SAMPLES = Path(settings.BASE_DIR) / "media" / "documents"


@pytest.fixture(scope="module")
def api_key():
    key = settings.ANTHROPIC_API_KEY
    if not key:
        pytest.skip("ANTHROPIC_API_KEY no configurada")
    return key


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-sonnet-5-5"])
@pytest.mark.parametrize("sample,mime", [
    ("FacturaSencillaEjemplo.pdf", "application/pdf"),
    ("modelo-factura.png", "image/png"),
])
def test_real_extraction(api_key, model, sample, mime):
    path = SAMPLES / sample
    if not path.exists():
        pytest.skip(f"Falta {path}")
    ext = ClaudeExtractor(model, api_key=api_key, effort="low" if "haiku" in model else "medium")
    out = ext.extract(ExtractionInput(content=path.read_bytes(), mime_type=mime))
    n = normalize(out.result)
    print(f"\n{model} {sample}: tipo={n.kind} nº={n.document_number} fecha={n.issue_date} "
          f"base={n.base_amount} total={n.total_amount} conf={n.confidence_global:.2f} "
          f"tokens in/out={out.usage.input_tokens}/{out.usage.output_tokens} "
          f"cache_read={out.usage.cache_read_tokens} coste≈${estimate_cost(out.model, out.usage)}")
    assert out.result.document_type in {"invoice", "receipt", "quote", "delivery_note", "credit_note", "other"}
    assert out.usage.input_tokens > 0
