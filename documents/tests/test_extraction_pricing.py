from decimal import Decimal as D

from documents.services.extraction import Usage
from documents.services.extraction.pricing import estimate_cost


def test_haiku_cost():
    # 10.000 in * 0.10/M + 1.000 out * 0.50/M = 0.001 + 0.0005
    assert estimate_cost("claude-haiku-5-5", Usage(input_tokens=10_000, output_tokens=1_000)) == D("0.001500")


def test_sonnet_cost_with_cache():
    u = Usage(input_tokens=1_000, output_tokens=500, cache_read_tokens=10_000, cache_creation_tokens=2_000)
    # in 1000*2 + out 500*10 + read 10000*2*0.1 + write 2000*2*1.25  (todo /1e6)
    assert estimate_cost("claude-sonnet-5-5", u) == D("0.014000")


def test_haiku_long_prompt_uses_higher_tier():
    low = estimate_cost("claude-haiku-5-5", Usage(input_tokens=100_000))
    high = estimate_cost("claude-haiku-5-5", Usage(input_tokens=100_001))
    assert low == D("0.010000") and high > low * 4


def test_unknown_model_is_none():
    assert estimate_cost("otro-ocr", Usage(input_tokens=1)) is None


def test_settings_override(settings):
    settings.EXTRACTION_PRICING = {"otro-ocr": {"in": D("1"), "out": D("1")}}
    assert estimate_cost("otro-ocr", Usage(input_tokens=1_000_000)) == D("1.000000")
