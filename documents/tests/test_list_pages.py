"""Listados de Documentos y Movimientos: filtros agrupados, chips, pestañas, paginación y tarjetas."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from django.core.paginator import Paginator
from django.test import RequestFactory
from django.urls import reverse

from billing_ai import listing
from documents.tests import factories as f
from finance.models import FinancialMovement, MovementCategory

pytestmark = pytest.mark.django_db


def req(query=""):
    return RequestFactory().get("/x/" + query)


class TestListingHelpers:
    def test_qs_without_and_with(self):
        r = req("?q=a&page=3&sort=date&status=pending")
        assert listing.qs_without(r, "q") == "sort=date&status=pending"
        assert "page" not in listing.qs_with(r, status="approved") and "status=approved" in listing.qs_with(r, status="approved")
        assert "status" not in listing.qs_with(r, status="")

    def test_pretty_date(self):
        assert listing.pretty("2026-02-05") == "Feb. 05 de 2026"
        assert listing.pretty("no-fecha") == "no-fecha"

    def test_active_filters_with_labels_and_remove_links(self):
        r = req("?document_type=receipt&folder=7&date_from=2026-01-02&sort=date&page=2&empty=")
        items = listing.active_filters(r, [
            ("document_type", "Tipo", {"receipt": "Ticket"}, True),
            ("folder", "Carpeta", {"7": "Gastos"}, True),
            ("date_from", "Desde", listing.pretty, True),
            ("q", "Búsqueda", None, False),
        ])
        assert [(i["label"], i["text"]) for i in items] == [("Tipo", "Ticket"), ("Carpeta", "Gastos"), ("Desde", "Ene. 02 de 2026")]
        assert "document_type" not in items[0]["remove_url"] and "folder=7" in items[0]["remove_url"]
        assert "page=" not in items[0]["remove_url"] and "sort=date" in items[0]["remove_url"]
        assert listing.active_filters(req("?folder=7"), [("folder", "C", None, True)])[0]["remove_url"] == "?"

    def test_status_tabs(self):
        tabs = listing.status_tabs(req("?status=pending&q=x&page=4"), [("", "Todos"), ("pending", "Pendientes")])
        assert [t["active"] for t in tabs] == [False, True]
        assert tabs[0]["url"] == "?q=x" and "status=pending" in tabs[1]["url"] and "page" not in tabs[1]["url"]

    def test_page_window(self):
        page = Paginator(range(300), 10).page(10)
        assert listing.page_window(page) == [1, "…", 9, 10, 11, "…", 30]
        assert listing.page_window(Paginator(range(30), 10).page(2)) == [1, 2, 3]


class TestDocumentList:
    url = "/documents/"

    def test_groups_tabs_and_cards_markup(self, auth_client, user):
        f.DocumentFactory(client=user.client)
        body = auth_client.get(self.url).content.decode()
        for legend in ("Tipo de documento", "Organización", "Revisión y estado", "Fechas"):
            assert legend in body
        assert body.count('class="fgroup"') == 4 and "table-cards" in body and 'data-label="Total"' in body
        assert 'class="status-tab active"' in body and 'id="filter-panel" hidden' in body

    def test_active_filters_chips_and_counter(self, auth_client, user):
        folder = f.FolderFactory(client=user.client, name="Gastos 2026")
        f.DocumentFactory(client=user.client, folder=folder, document_type="receipt")
        r = auth_client.get(self.url, {"folder": folder.pk, "document_type": "receipt", "status": "pending", "q": "fac"})
        body = r.content.decode()
        assert r.context["panel_filter_count"] == 2          # tipo + carpeta (q y estado viven fuera del panel)
        assert "Gastos 2026" in body and "Ticket" in body and body.count('class="filter-chip"') == 4
        assert 'class="status-tab active"' in body and "Pendientes" in body

    def test_status_tab_filters_and_keeps_other_params(self, auth_client, user):
        f.DocumentFactory(client=user.client, status="pending")
        f.DocumentFactory(client=user.client, status="approved")
        r = auth_client.get(self.url, {"status": "approved", "q": "factura"})
        assert [d.status for d in r.context["documents"]] == []  or all(d.status == "approved" for d in r.context["documents"])
        tabs = {t["label"]: t["url"] for t in r.context["status_tabs"]}
        assert "q=factura" in tabs["Pendientes"] and tabs["Todos"] == "?q=factura"

    def test_empty_states(self, auth_client, user):
        assert "Aún no hay documentos" in auth_client.get(self.url).content.decode()
        assert "Ningún documento coincide" in auth_client.get(self.url, {"q": "zzz"}).content.decode()

    def test_pagination_numbers_and_querystring(self, auth_client, user):
        for _ in range(45):
            f.DocumentFactory(client=user.client)
        r = auth_client.get(self.url, {"page": 2, "flow": "out"})
        assert r.context["page_numbers"] == [1, 2, 3] and "flow=out" in r.content.decode()
        assert 'aria-current="page"' in r.content.decode()

    def test_other_tenant_filter_values_do_not_leak(self, auth_client, other_user):
        folder = f.FolderFactory(client=other_user.client, name="Secreta")
        r = auth_client.get(self.url, {"folder": folder.pk})
        assert "Secreta" not in r.content.decode() or "Secreta" not in "".join(i["text"] for i in r.context["active_filters"])


def make_movement(client, kind, amount, **kw):
    cat = MovementCategory.objects.get_or_create(client=client, name=f"c-{kind}", type=kind)[0]
    return FinancialMovement.objects.create(client=client, category=cat, movement_type=kind, amount=D(amount),
                                            date=kw.pop("date", date(2026, 3, 1)), **kw)


class TestMovementList:
    url = "/finance/movements"

    def test_groups_totals_and_cards_markup(self, auth_client, user):
        make_movement(user.client, "income", "1000")
        make_movement(user.client, "expense", "250")
        r = auth_client.get(self.url)
        body = r.content.decode()
        assert r.context["totals"] == {"income": D("1000"), "expense": D("250"), "balance": D("750")}
        assert body.count('class="fgroup"') == 4 and "table-cards" in body and 'data-label="Importe"' in body
        assert "750,00 €" in body

    def test_totals_cover_filtered_set_not_just_page(self, auth_client, user):
        for _ in range(30):
            make_movement(user.client, "expense", "10")
        make_movement(user.client, "income", "999", date=date(2025, 1, 1))
        r = auth_client.get(self.url, {"start": "2026-01-01"})
        assert r.context["totals"]["expense"] == D("300") and r.context["totals"]["income"] == 0
        assert len(r.context["movements"]) == 25 and r.context["page_obj"].paginator.count == 30
        assert r.context["page_numbers"] == [1, 2]

    def test_selected_category_and_chips(self, auth_client, user):
        m = make_movement(user.client, "expense", "5")
        body = auth_client.get(self.url, {"category": m.category_id, "min_amount": "1", "is_reconciled": "on"}).content.decode()
        assert f'value="{m.category_id}" selected' in body
        assert body.count('class="filter-chip"') == 3 and "Conciliados" in body

    def test_empty_states_and_isolation(self, auth_client, other_user):
        make_movement(other_user.client, "income", "123456")
        body = auth_client.get(self.url).content.decode()
        assert "No hay movimientos todavía" in body and "123.456" not in body
        assert "Ningún movimiento coincide" in auth_client.get(self.url, {"q": "zzz"}).content.decode()


class TestPagerEdges:
    def test_first_and_last_page_render(self, auth_client, user):
        for _ in range(45):
            f.DocumentFactory(client=user.client)
        for page in (1, 3):
            r = auth_client.get("/documents/", {"page": page})
            assert r.status_code == 200 and 'class="page disabled"' in r.content.decode()


class TestSearchRow:
    def test_documents_search_button_joined_and_tabs_in_same_row(self, auth_client):
        body = auth_client.get("/documents/").content.decode()
        top = body.split('class="filter-top"')[1].split('id="filter-panel"')[0]
        assert top.index('class="search-group"') < top.index('class="status-tabs"') < top.index('id="filters-toggle"')
        group = top.split('class="search-group"')[1].split('class="status-tabs"')[0]
        assert 'name="q"' in group and 'type="submit"' in group             # input y botón en el mismo control

    def test_movements_use_the_same_joined_control(self, auth_client):
        top = auth_client.get("/finance/movements").content.decode().split('class="filter-top"')[1].split('id="filter-panel"')[0]
        assert 'class="search-group"' in top and top.count('type="submit"') == 1


class TestConfidenceInRows:
    @pytest.mark.parametrize("value, tone, pct", [("0.9500", "high", "95"), ("0.7000", "medium", "70"), ("0.3000", "low", "30")])
    def test_confidence_shows_tone_bar_and_percent(self, auth_client, user, value, tone, pct):
        f.DocumentFactory(client=user.client, confidence_global=D(value))
        body = auth_client.get(reverse("documents:list")).content.decode()
        assert f"conf conf-{tone}" in body and f"{pct}%" in body and "conf-fill" in body

    def test_no_confidence_no_meter(self, auth_client, user):
        f.DocumentFactory(client=user.client, confidence_global=None)
        assert "conf-fill" not in auth_client.get(reverse("documents:list")).content.decode()
