"""Terceros: no se duplican por mayúsculas, tildes, comas, forma jurídica ni formato de NIF."""
from io import StringIO

import pytest
from django.core.management import call_command

from documents.company_names import display_name, name_key
from documents.models import Company
from documents.services.companies import get_or_create_company
from documents.tests import factories as f
from documents.validators import clean_tax_id


class TestCleanTaxId:
    @pytest.mark.parametrize("raw", [
        "B96148028", "b96148028", "B/96148028", "B-96.148.028", " B 96148028 ",
        "ESB96148028", "ES B96148028", "ES-B96148028", "NIF: B96148028", "CIF:B96148028", "N.I.F.: B96148028",
    ])
    def test_variants_collapse_to_one_form(self, raw):
        assert clean_tax_id(raw) == "B96148028"

    def test_foreign_vat_keeps_its_prefix(self):
        assert clean_tax_id("FR 12 345678901") == "FR12345678901"

    def test_empty(self):
        assert clean_tax_id(None) == "" and clean_tax_id("  ") == ""


class TestNameKey:
    @pytest.mark.parametrize("a,b", [
        ("TOP RECAMBIOS SL", "TOP RECAMBIOS, S.L."),
        ("Repuestos Serca S.L.U.", "REPUESTOS SERCA, S.L.U."),
        ("Informática Fuentealbilla, S.L.", "INFORMATICA FUENTEALBILLA SL"),
        ("Neumáticos Andrés S.A.U.", "neumaticos andres s.a.u"),
        ("Pérez & Hijos, S.L.", "PEREZ Y HIJOS SL"),
        ("  Taller   Paco  ", "taller paco"),
    ])
    def test_same_company_same_key(self, a, b):
        assert name_key(a) == name_key(b)

    def test_different_names_differ(self):
        assert name_key("Repuestos Serca") != name_key("Repuestos Sanz")

    def test_word_order_is_not_guessed(self):
        assert name_key("García Juan") != name_key("Juan García")

    def test_legal_form_alone_is_kept(self):
        assert name_key("S.L.") == "s l"

    def test_display_name_cleans_spaces_and_commas(self):
        assert display_name('  "Empresa ,S.L." , ') == "Empresa, S.L."
        assert display_name("TOP RECAMBIOS, S.L.") == "TOP RECAMBIOS, S.L."


@pytest.mark.django_db
class TestGetOrCreateCompany:
    def setup_method(self):
        self.client = f.ClientFactory()

    def _goc(self, name, tax_id, **kw):
        return get_or_create_company(client=self.client, name=name, tax_id=tax_id, **kw)

    def test_same_nif_in_different_formats_is_one_company(self):
        a = self._goc("TOP RECAMBIOS SL", "B96148028")
        b = self._goc("Top Recambios, S.L.", "B/96148028")
        c = self._goc("Otro nombre", "ES B96148028")
        assert a.pk == b.pk == c.pk and Company.objects.filter(client=self.client).count() == 1

    def test_same_name_in_different_spelling_is_one_company(self):
        a = self._goc("Repuestos Serca S.L.U.", None)
        b = self._goc("REPUESTOS SERCA, S.L.U.", None)
        c = self._goc("Repuestos Sérca SLU", None)
        assert a.pk == b.pk == c.pk

    def test_nif_is_added_to_a_company_found_by_name(self):
        a = self._goc("Repuestos Serca S.L.U.", None, is_provider=True)
        b = self._goc("REPUESTOS SERCA, S.L.U.", "ES-B54193594")
        assert a.pk == b.pk
        b.refresh_from_db()
        assert b.tax_id == "B54193594"
        # y la siguiente vez ya se encuentra por NIF aunque cambie el nombre
        assert self._goc("Serca", "B54.193.594").pk == a.pk

    def test_same_name_with_different_nif_is_another_company(self):
        a = self._goc("Talleres Pérez", "B11111111")
        b = self._goc("TALLERES PEREZ, S.L.", "B22222222")
        assert a.pk != b.pk

    def test_name_without_nif_matches_company_with_nif(self):
        a = self._goc("Top Recambios SL", "B96148028")
        assert self._goc("TOP RECAMBIOS, S.L.", None).pk == a.pk

    def test_roles_are_added_not_replaced(self):
        a = self._goc("Top Recambios", "B96148028", is_provider=True)
        b = self._goc("TOP RECAMBIOS SL", "B96148028", is_customer=True)
        b.refresh_from_db()
        assert a.pk == b.pk and b.is_provider and b.is_customer

    def test_companies_of_other_clients_are_not_matched(self):
        other = f.ClientFactory()
        a = get_or_create_company(client=other, name="Top Recambios", tax_id="B96148028")
        b = self._goc("Top Recambios", "B96148028")
        assert a.pk != b.pk

    def test_save_keeps_key_and_canonical_nif(self):
        c = Company.objects.create(client=self.client, name=" Top  Recambios, S.L. ", tax_id="b/96148028")
        assert c.tax_id == "B96148028" and c.name == "Top Recambios, S.L." and c.name_key == "top recambios"


@pytest.mark.django_db
class TestMergeCommand:
    def _make_dups(self):
        client = f.ClientFactory()
        a = Company.objects.create(client=client, name="TOP RECAMBIOS SL", tax_id="B96148028")
        # NIF mal formateado guardado "a mano" (como antes de este cambio)
        b = Company.objects.create(client=client, name="TOP RECAMBIOS, S.L.", tax_id="B11111111")
        Company.objects.filter(pk=b.pk).update(tax_id="B/96148028")
        c = Company.objects.create(client=client, name="Repuestos Serca S.L.U.", tax_id=None)
        d = Company.objects.create(client=client, name="REPUESTOS SERCA, S.L.U.", tax_id="B54193594")
        e = Company.objects.create(client=client, name="Talleres Pérez", tax_id="B33333333")
        g = Company.objects.create(client=client, name="Talleres Perez SL", tax_id="B44444444")
        return client, a, b, c, d, e, g

    def test_dry_run_changes_nothing(self):
        client, *_ = self._make_dups()
        out = StringIO()
        call_command("merge_companies", stdout=out)
        assert Company.objects.filter(client=client).count() == 6
        assert "Se fusionarían: 2" in out.getvalue()

    def test_apply_merges_and_reassigns_documents(self):
        client, a, b, c, d, e, g = self._make_dups()
        doc_b = f.DocumentFactory(client=client, company=b)
        doc_c = f.DocumentFactory(client=client, company=c)
        call_command("merge_companies", "--apply", stdout=StringIO())

        assert Company.objects.filter(client=client).count() == 4
        assert set(Company.objects.filter(client=client).values_list("pk", flat=True)) == {a.pk, d.pk, e.pk, g.pk}
        doc_b.refresh_from_db(); doc_c.refresh_from_db()
        assert doc_b.company_id == a.pk and doc_c.company_id == d.pk
        # el mismo nombre con NIF distinto NO se fusiona
        assert Company.objects.filter(pk__in=[e.pk, g.pk]).count() == 2
