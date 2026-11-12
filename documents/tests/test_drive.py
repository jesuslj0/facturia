"""Vista «Archivo» (Drive): árbol virtual de carpetas derivado de los datos del documento."""
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from documents.models import Document
from documents.selectors import drive_selector as drive
from documents.selectors.drive_selector import DrivePath, DriveSelector, InvalidDrivePath
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


@pytest.fixture
def supplier(client_entity):
    return f.CompanyFactory(client=client_entity, name="Proveedor S.L.")


def make_doc(client, supplier, **kwargs):
    defaults = dict(client=client, company=supplier, flow="out", issue_date=date(2026, 2, 15),
                    document_type="invoice", processing_status="processed")
    defaults.update(kwargs)
    return f.DocumentFactory(**defaults)


def names(folders):
    return [fo.name for fo in folders]


def leaf_ids(client, ruta, filters=None):
    return set(DriveSelector.documents(client, DrivePath.parse(ruta), filters).values_list("pk", flat=True))


class TestDrivePath:
    def test_root_and_levels(self):
        assert DrivePath.parse("").level == "root"
        assert DrivePath.parse("compras/").level == "flow"
        assert DrivePath.parse("compras/2026/").level == "year"
        assert DrivePath.parse("compras/2026/T1/").level == "quarter"
        assert DrivePath.parse("compras/2026/T1/7/").level == "company"
        assert DrivePath.parse("compras/2026/T1/7/abonos/").level == "group"
        assert DrivePath.parse("sin-clasificar/").level == "unclassified"

    def test_ruta_roundtrip(self):
        for raw in ("", "ventas/", "ventas/2026/T4/", "compras/2026/T1/7/otros/", "sin-clasificar/"):
            assert DrivePath.parse(raw).ruta == raw

    @pytest.mark.parametrize("raw", [
        "abc/", "compras/abc/", "compras/26/", "compras/2026/T9/", "compras/2026/T0/", "compras/2026/1/",
        "compras/2026/T1/x/", "compras/2026/T1/7/zzz/", "compras/2026/T1/7/facturas/extra/",
        "sin-clasificar/otra/", "compras/0000/", "compras/２０２６/",
    ])
    def test_invalid_paths(self, raw):
        with pytest.raises(InvalidDrivePath):
            DrivePath.parse(raw)

    def test_flow_mapping(self):
        """Compras = gasto (`out`), Ventas = ingreso (`in`)."""
        assert drive.FLOW_FOLDERS["compras"][1] == "out"
        assert drive.FLOW_FOLDERS["ventas"][1] == "in"
        assert DrivePath.parse("compras/").flow_code == "out"
        assert DrivePath.parse("ventas/").flow_code == "in"

    def test_all_document_types_have_a_group(self):
        """Un tipo nuevo no puede desaparecer del Drive: o está en TYPE_GROUPS o cae en «Otros»."""
        types = {key for key, _ in Document.TYPE_CHOICES}
        assert types == set(drive.KNOWN_TYPES)
        assert all(drive.group_of(t) != drive.OTHERS_SLUG for t in types)
        assert drive.group_of("tipo_nuevo") == drive.OTHERS_SLUG


class TestTree:
    def test_processed_document_appears_without_any_action(self, client_entity, supplier):
        doc = make_doc(client_entity, supplier)
        assert doc.pk in leaf_ids(client_entity, f"compras/2026/T1/{supplier.pk}/facturas/")

    def test_tree_levels_and_counts(self, client_entity, supplier):
        make_doc(client_entity, supplier)
        make_doc(client_entity, supplier, issue_date=date(2026, 5, 2))
        make_doc(client_entity, supplier, flow="in", issue_date=date(2025, 11, 2))
        root = DriveSelector.children(client_entity, DrivePath.parse(""))
        assert names(root) == ["Compras", "Ventas", "Mis carpetas"]  # sin «Sin clasificar» si no hay sueltos
        assert [fo.count for fo in root] == [2, 1, 0]
        assert names(DriveSelector.children(client_entity, DrivePath.parse("compras/"))) == ["2026"]
        # trimestres: más reciente primero
        assert names(DriveSelector.children(client_entity, DrivePath.parse("compras/2026/"))) == ["T2", "T1"]
        companies = DriveSelector.children(client_entity, DrivePath.parse("compras/2026/T1/"))
        assert names(companies) == ["Proveedor S.L."] and companies[0].ruta == f"compras/2026/T1/{supplier.pk}/"
        groups = DriveSelector.children(client_entity, DrivePath.parse(f"compras/2026/T1/{supplier.pk}/"))
        assert names(groups) == ["Facturas"] and groups[0].ruta.endswith("/facturas/")

    @pytest.mark.parametrize("issue, quarter, year", [
        (date(2026, 3, 31), "T1", "2026"),
        (date(2026, 4, 1), "T2", "2026"),
        (date(2026, 12, 31), "T4", "2026"),
        (date(2027, 1, 1), "T1", "2027"),
    ])
    def test_quarter_boundaries(self, client_entity, supplier, issue, quarter, year):
        doc = make_doc(client_entity, supplier, issue_date=issue)
        ruta = f"compras/{year}/{quarter}/{supplier.pk}/facturas/"
        assert leaf_ids(client_entity, ruta) == {doc.pk}
        other = {"T1": "T2", "T2": "T1", "T4": "T1"}[quarter]
        assert leaf_ids(client_entity, f"compras/{year}/{other}/{supplier.pk}/facturas/") == set()

    def test_changing_date_company_or_type_moves_the_document(self, client_entity, supplier):
        doc = make_doc(client_entity, supplier)
        other = f.CompanyFactory(client=client_entity, name="Otro")
        here = f"compras/2026/T1/{supplier.pk}/facturas/"
        assert doc.pk in leaf_ids(client_entity, here)

        doc.issue_date = date(2026, 7, 1)
        doc.save()
        assert doc.pk not in leaf_ids(client_entity, here)
        assert doc.pk in leaf_ids(client_entity, f"compras/2026/T3/{supplier.pk}/facturas/")

        doc.company = other
        doc.save()
        assert doc.pk in leaf_ids(client_entity, f"compras/2026/T3/{other.pk}/facturas/")

        doc.document_type = "delivery"
        doc.save()
        assert doc.pk in leaf_ids(client_entity, f"compras/2026/T3/{other.pk}/albaranes/")

    def test_type_groups(self, client_entity, supplier):
        docs = {t: make_doc(client_entity, supplier, document_type=t, document_number=t)
                for t, _ in Document.TYPE_CHOICES}
        base = f"compras/2026/T1/{supplier.pk}/"
        assert leaf_ids(client_entity, base + "abonos/") == {docs["corrected_invoice"].pk, docs["delivery_credit_note"].pk}
        assert leaf_ids(client_entity, base + "tickets/") == {docs["receipt"].pk}
        assert leaf_ids(client_entity, base + "presupuestos/") == {docs["quote"].pk}
        assert leaf_ids(client_entity, base + "albaranes/") == {docs["delivery"].pk}
        groups = DriveSelector.children(client_entity, DrivePath.parse(base))
        assert names(groups) == ["Facturas", "Albaranes", "Abonos", "Tickets", "Presupuestos"]
        assert [g.count for g in groups] == [1, 1, 2, 1, 1]

    def test_unknown_type_falls_into_otros(self, client_entity, supplier):
        doc = make_doc(client_entity, supplier)
        Document.all_objects.filter(pk=doc.pk).update(document_type="tipo_nuevo")
        base = f"compras/2026/T1/{supplier.pk}/"
        assert names(DriveSelector.children(client_entity, DrivePath.parse(base))) == ["Otros"]
        assert leaf_ids(client_entity, base + "otros/") == {doc.pk}
        assert leaf_ids(client_entity, base + "facturas/") == set()

    def test_flow_separates_purchases_and_sales(self, client_entity, supplier):
        buy = make_doc(client_entity, supplier, flow="out")
        sell = make_doc(client_entity, supplier, flow="in")
        assert leaf_ids(client_entity, f"compras/2026/T1/{supplier.pk}/facturas/") == {buy.pk}
        assert leaf_ids(client_entity, f"ventas/2026/T1/{supplier.pk}/facturas/") == {sell.pk}


class TestUnclassified:
    @pytest.mark.parametrize("changes, reason", [
        ({"flow": "unknown"}, "Flujo por revisar"),
        ({"issue_date": None}, "Sin fecha"),
        ({"company": None}, "Sin tercero"),
        ({"processing_status": "failed"}, "Error de extracción"),
        ({"processing_status": "processing"}, "Procesando"),
        ({"processing_status": "queued"}, "Procesando"),
    ])
    def test_missing_data_goes_to_unclassified(self, client_entity, supplier, changes, reason):
        doc = make_doc(client_entity, supplier, **changes)
        assert leaf_ids(client_entity, "sin-clasificar/") == {doc.pk}
        assert drive.unclassified_reason(DriveSelector.documents(client_entity, DrivePath.parse("sin-clasificar/")).get()) == reason
        # no aparece en ninguna carpeta del árbol
        for slug in ("compras", "ventas"):
            assert DriveSelector.children(client_entity, DrivePath.parse(f"{slug}/")) == []

    def test_unclassified_folder_has_no_total_and_hides_when_empty(self, client_entity, supplier):
        assert names(DriveSelector.children(client_entity, DrivePath.parse(""))) == ["Compras", "Ventas", "Mis carpetas"]
        make_doc(client_entity, supplier, issue_date=None)
        root = DriveSelector.children(client_entity, DrivePath.parse(""))
        loose = root[-1]
        assert (loose.name, loose.count, loose.total, loose.ruta) == ("Sin clasificar", 1, None, "sin-clasificar/")

    def test_fixing_the_data_moves_it_into_the_tree(self, client_entity, supplier):
        doc = make_doc(client_entity, supplier, issue_date=None)
        assert leaf_ids(client_entity, "sin-clasificar/") == {doc.pk}
        doc.issue_date = date(2026, 1, 10)
        doc.save()
        assert leaf_ids(client_entity, "sin-clasificar/") == set()
        assert doc.pk in leaf_ids(client_entity, f"compras/2026/T1/{supplier.pk}/facturas/")


class TestScope:
    def test_archived_and_old_versions_are_hidden(self, client_entity, supplier):
        archived = make_doc(client_entity, supplier)
        archived.is_archived = True
        archived.save()
        old = make_doc(client_entity, supplier)
        Document.all_objects.filter(pk=old.pk).update(is_current=False)
        keep = make_doc(client_entity, supplier)
        assert leaf_ids(client_entity, f"compras/2026/T1/{supplier.pk}/facturas/") == {keep.pk}
        assert DriveSelector.children(client_entity, DrivePath.parse("compras/"))[0].count == 1

    def test_pending_approved_rejected_all_appear_and_filter(self, client_entity, supplier):
        docs = {s: make_doc(client_entity, supplier, status=s) for s in ("pending", "approved", "rejected")}
        ruta = f"compras/2026/T1/{supplier.pk}/facturas/"
        assert leaf_ids(client_entity, ruta) == {d.pk for d in docs.values()}
        assert leaf_ids(client_entity, ruta, {"status": "approved"}) == {docs["approved"].pk}
        folder = DriveSelector.children(client_entity, DrivePath.parse("compras/"))
        assert folder[0].pending_count == 1

    def test_cross_filters_folder_tag(self, client_entity, supplier):
        folder = f.Folder.objects.create(client=client_entity, name="Gestoría")
        tag = f.Tag.objects.create(client=client_entity, name="Urgente")
        a = make_doc(client_entity, supplier, folder=folder)
        b = make_doc(client_entity, supplier)
        b.tags.add(tag)
        c = make_doc(client_entity, supplier)
        ruta = f"compras/2026/T1/{supplier.pk}/facturas/"
        assert leaf_ids(client_entity, ruta, {"folder": str(folder.pk)}) == {a.pk}
        assert leaf_ids(client_entity, ruta, {"tag": str(tag.pk)}) == {b.pk}
        assert leaf_ids(client_entity, ruta, {"tag": "x"}) == set()
        assert c.pk in leaf_ids(client_entity, ruta)

    def test_signed_totals_credit_notes_subtract(self, client_entity, supplier):
        make_doc(client_entity, supplier, total_amount=D("121.00"))
        make_doc(client_entity, supplier, document_type="corrected_invoice", total_amount=D("21.00"))
        make_doc(client_entity, supplier, document_type="corrected_invoice", total_amount=D("-10.00"))  # IA: negativo
        flow = DriveSelector.children(client_entity, DrivePath.parse("compras/"))[0]
        assert flow.total == D("121.00") - D("21.00") - D("10.00")
        assert flow.count == 3

    def test_no_amounts_empty_tax_id_and_empty_folder(self, client_entity):
        nameless = f.CompanyFactory(client=client_entity, name="Sin NIF", tax_id=None)
        make_doc(client_entity, nameless, total_amount=None, base_amount=None, tax_amount=None)
        folder = DriveSelector.children(client_entity, DrivePath.parse("compras/"))[0]
        assert (folder.count, folder.total) == (1, D("0.00"))
        assert names(DriveSelector.children(client_entity, DrivePath.parse("compras/2026/T1/"))) == ["Sin NIF"]
        assert DriveSelector.children(client_entity, DrivePath.parse("compras/2020/")) == []
        assert leaf_ids(client_entity, f"compras/2026/T1/{nameless.pk}/tickets/") == set()


class TestTenantIsolation:
    def test_selector_does_not_leak_other_clients(self, client_entity, other_client_entity, supplier):
        mine = make_doc(client_entity, supplier)
        theirs_company = f.CompanyFactory(client=other_client_entity, name="Ajeno")
        make_doc(other_client_entity, theirs_company)
        assert names(DriveSelector.children(client_entity, DrivePath.parse("compras/2026/T1/"))) == ["Proveedor S.L."]
        assert names(DriveSelector.children(other_client_entity, DrivePath.parse("compras/2026/T1/"))) == ["Ajeno"]
        assert leaf_ids(other_client_entity, f"compras/2026/T1/{supplier.pk}/facturas/") == set()
        assert mine.pk not in leaf_ids(other_client_entity, "sin-clasificar/")

    def test_company_of_another_client_is_404_in_selector(self, client_entity, other_client_entity):
        foreign = f.CompanyFactory(client=other_client_entity)
        with pytest.raises(InvalidDrivePath):
            DriveSelector.company(client_entity, DrivePath.parse(f"compras/2026/T1/{foreign.pk}/"))


class TestViews:
    def url(self, ruta=""):
        return reverse("documents:drive", kwargs={"ruta": ruta}) if ruta else reverse("documents:drive")

    def test_requires_login(self, client):
        response = client.get(self.url())
        assert response.status_code == 302 and "login" in response.url

    def test_urls(self):
        assert self.url() == "/documents/archivo/"
        assert self.url("compras/2026/T1/") == "/documents/archivo/compras/2026/T1/"

    def test_root_renders_folders(self, auth_client, client_entity, supplier):
        make_doc(client_entity, supplier)
        response = auth_client.get(self.url())
        assert response.status_code == 200
        body = response.content.decode()
        assert "Compras" in body and "Ventas" in body

    def test_walk_down_to_leaf_shows_the_document(self, auth_client, client_entity, supplier):
        doc = make_doc(client_entity, supplier, original_name="mi-factura.pdf")
        for ruta in ("compras/", "compras/2026/", "compras/2026/T1/", f"compras/2026/T1/{supplier.pk}/"):
            assert auth_client.get(self.url(ruta)).status_code == 200
        response = auth_client.get(self.url(f"compras/2026/T1/{supplier.pk}/facturas/"))
        assert response.status_code == 200
        assert "mi-factura.pdf" in response.content.decode()
        assert doc in list(response.context["documents"])

    def test_unclassified_view_shows_reason(self, auth_client, client_entity, supplier):
        make_doc(client_entity, supplier, issue_date=None, original_name="sin-fecha.pdf")
        response = auth_client.get(self.url("sin-clasificar/"))
        assert response.status_code == 200
        assert "sin-fecha.pdf" in response.content.decode()
        assert "Sin fecha" in response.content.decode()

    def test_empty_folder_of_own_company_is_200(self, auth_client, supplier):
        assert auth_client.get(self.url(f"compras/2026/T1/{supplier.pk}/facturas/")).status_code == 200

    @pytest.mark.parametrize("ruta", ["abc/", "compras/abc/", "compras/2026/T9/", "compras/2026/T1/1/zzz/", "compras/0000/"])
    def test_invalid_path_is_404(self, auth_client, ruta):
        assert auth_client.get(self.url(ruta)).status_code == 404

    def test_company_of_another_tenant_is_404(self, auth_client, other_client_entity):
        foreign = f.CompanyFactory(client=other_client_entity)
        make_doc(other_client_entity, foreign)
        assert auth_client.get(self.url(f"compras/2026/T1/{foreign.pk}/")).status_code == 404
        assert auth_client.get(self.url(f"compras/2026/T1/{foreign.pk}/facturas/")).status_code == 404

    def test_other_tenant_documents_not_visible(self, auth_client, other_client_entity):
        foreign = f.CompanyFactory(client=other_client_entity, name="Empresa Ajena")
        make_doc(other_client_entity, foreign)
        body = auth_client.get(self.url("compras/2026/T1/")).content.decode()
        assert "Empresa Ajena" not in body

    def test_filters_are_applied_in_view(self, auth_client, client_entity, supplier):
        make_doc(client_entity, supplier, status="approved", original_name="aprobada.pdf")
        make_doc(client_entity, supplier, status="pending", original_name="pendiente.pdf")
        ruta = f"compras/2026/T1/{supplier.pk}/facturas/"
        body = auth_client.get(self.url(ruta) + "?status=approved").content.decode()
        assert "aprobada.pdf" in body and "pendiente.pdf" not in body

    def test_sidebar_links_to_drive(self, auth_client):
        assert reverse("documents:drive") in auth_client.get(self.url()).content.decode()
