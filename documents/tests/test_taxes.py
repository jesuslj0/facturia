from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from documents.services import taxes


class TestRounding:
    def test_percentage_half_up(self):
        assert taxes.percentage_of("10.05", 21) == D("2.11")  # 2.1105 -> 2.11
        assert taxes.percentage_of("0.50", 21) == D("0.11")   # 0.105 -> 0.11 (half-up)
        assert taxes.percentage_of(100, 0) == D("0.00")

    def test_accepts_float_and_str_without_binary_error(self):
        assert taxes.percentage_of(0.1 + 0.2, 10) == D("0.03")


class TestExpectedTotal:
    def test_vat_only(self):
        assert taxes.expected_total(100, vat=21) == D("121.00")

    def test_with_withholding_subtracts(self):
        # Profesional: base 1000, IVA 21%, IRPF 15% -> 1000 + 210 - 150
        vat = taxes.percentage_of(1000, 21)
        irpf = taxes.percentage_of(1000, 15)
        assert taxes.expected_total(1000, vat=vat, withholding=irpf) == D("1060.00")

    def test_with_surcharge(self):
        vat = taxes.percentage_of(100, 21)
        re = taxes.percentage_of(100, "5.2")
        assert taxes.expected_total(100, vat=vat, surcharge=re) == D("126.20")


class TestTotalsMatch:
    def test_within_tolerance(self):
        assert taxes.totals_match("121.01", "121.00")
        assert taxes.totals_match("121.02", "121.00")

    def test_outside_tolerance(self):
        assert not taxes.totals_match("121.03", "121.00")
        assert not taxes.totals_match("100", "121")

    def test_custom_tolerance(self):
        assert taxes.totals_match("121.50", "121.00", tolerance="0.50")


class TestSummarize:
    def test_sums_by_kind_and_computes_total(self):
        lines = [
            NS(kind="vat", amount=D("21.00")),
            NS(kind="vat", amount=D("4.00")),
            NS(kind="withholding", amount=D("15.00")),
        ]
        s = taxes.summarize(lines)
        assert s == {"vat": D("25.00"), "surcharge": D("0.00"), "withholding": D("15.00")}
        assert taxes.expected_total_from_lines(100, lines) == D("110.00")

    def test_empty(self):
        assert taxes.expected_total_from_lines(50, []) == D("50.00")
