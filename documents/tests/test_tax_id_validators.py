import pytest

from documents.validators import check_tax_id, clean_tax_id, is_valid_tax_id


class TestDni:
    @pytest.mark.parametrize("v", ["12345678Z", "00000000T", "77777777B", "12345678z", "12.345.678-Z"])
    def test_valid(self, v):
        c = check_tax_id(v)
        assert c.kind == "dni" and c.valid is True

    @pytest.mark.parametrize("v", ["12345678A", "12345678T", "00000000A"])
    def test_wrong_letter(self, v):
        assert check_tax_id(v).valid is False


class TestNie:
    @pytest.mark.parametrize("v", ["X0000000T", "Y0000000Z", "X1234567L", "x-0000000-t"])
    def test_valid(self, v):
        c = check_tax_id(v)
        assert c.kind == "nie" and c.valid is True

    def test_wrong_letter(self):
        assert check_tax_id("X0000000A").valid is False


class TestCif:
    # CIF reales de empresas del IBEX (verificados de forma independiente del algoritmo)
    @pytest.mark.parametrize("v", ["A82018474", "A39000013", "A48010615", "A15022510", "A28015865", "G28029007", "Q2826000H", "B12345674"])
    def test_valid(self, v):
        c = check_tax_id(v)
        assert c.kind == "cif" and c.valid is True

    @pytest.mark.parametrize("v", ["B12345678", "A82018475", "A39000014", "B12345670"])
    def test_wrong_control_digit(self, v):
        assert check_tax_id(v).valid is False

    def test_letter_only_types_reject_digit_control(self):
        # Q2826000H es válido con letra; con el dígito equivalente (8) no, porque Q exige letra
        assert check_tax_id("Q28260008").valid is False

    def test_digit_only_types_reject_letter_control(self):
        # A82018474: control 4 (dígito); la letra equivalente (D) no vale para la clase A
        assert check_tax_id("A8201847D").valid is False

    def test_mixed_types_accept_either(self):
        # G28029007: clase G admite dígito (7) o letra (G)
        assert check_tax_id("G2802900G").valid is True


class TestOtherFormats:
    def test_es_prefix_is_stripped(self):
        assert clean_tax_id("ESB12345674") == "B12345674"
        assert check_tax_id("ES B-12345674").valid is True

    def test_foreign_vat_is_not_verifiable_not_invalid(self):
        for v in ("FR12345678901", "DE123456789", "PT501964843"):
            c = check_tax_id(v)
            assert c.kind == "foreign" and c.valid is None

    def test_special_spanish_nif_not_verifiable(self):
        assert check_tax_id("K1234567L").valid is None

    @pytest.mark.parametrize("v", ["B1234567", "B123456789A", "B1234567890"])
    def test_spanish_looking_but_malformed_is_invalid(self, v):
        assert check_tax_id(v).valid is False

    @pytest.mark.parametrize("v", ["1234567", "501964843"])
    def test_only_digits_may_be_foreign_so_not_invalid(self, v):
        assert check_tax_id(v).valid is None

    def test_garbage_is_unverifiable_not_invalid(self):
        assert check_tax_id("N/A").valid is None

    @pytest.mark.parametrize("v", [None, "", "   "])
    def test_empty(self, v):
        assert check_tax_id(v) is None and is_valid_tax_id(v) is False
