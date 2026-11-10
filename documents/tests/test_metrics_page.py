"""Página de Métricas: constructor de datos y vista."""
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from documents.services.metrics_page import build_page, g, pct, presets, previous_period
from documents.services.metrics_service import MetricsService
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


def metrics(**over):
    base = {
        "documents": {"total": 10, "approved": 6, "pending": 3, "rejected": 1, "confidence_average": 91.2,
                      "auto_approval_rate": 40.0, "manual_approval_rate": 20.0},
        "financials": {
            "combined": {"income": 1000.0, "expense": 400.0, "profit": 600.0, "profit_margin": 60.0},
            "documents": {"income": 800.0, "expense": 300.0, "profit": 500.0, "profit_margin": 62.5,
                          "vat": {"collected": 168.0, "paid": 63.0, "balance": 105.0},
                          "withholding": {"suffered": 12.0, "applied": 0.0}, "surcharge": {"collected": 0.0, "paid": 0.0}},
            "movements": {"income": 200.0, "expense": 100.0, "profit": 100.0, "profit_margin": 50.0, "count": 4},
        },
        "charts": {"income_expense_monthly": [{"period": "Nov 2026", "income": 1, "expense": 2, "profit": -1}],
                   "by_quarter": [{"period": "2026-T4", "income": 1.0, "expense": 2.0}],
                   "by_company": [{"id": 1, "name": "ACME", "income": 600.0, "expense": 0.0, "count": 3},
                                  {"id": 2, "name": "Beta", "income": 0.0, "expense": 300.0, "count": 1}]},
        "status_distribution": {"auto_approved": 4, "manual_approved": 2, "pending": 3, "rejected": 1},
        "extraction": {"runs": 5, "documents": 4, "cost_usd": 0.02, "cost_per_document": 0.005},
    }
    base.update(over)
    return base


PERIOD = {"start": date(2026, 11, 1), "end": date(2026, 11, 20)}


class TestHelpers:
    def test_g_and_pct_never_fail(self):
        assert g({"a": {"b": 3}}, "a", "b") == 3 and g({}, "a", "b") == 0 and g({"a": None}, "a", default=7) == 7
        assert g("no-dict", "x") == 0
        assert pct(1, 0) == 0.0 and pct(1, 4) == 25.0

    def test_previous_period_same_length(self):
        assert previous_period(date(2026, 11, 1), date(2026, 11, 20)) == (date(2026, 10, 12), date(2026, 10, 31))

    def test_presets_mark_active(self):
        ps = presets(date(2026, 11, 20), date(2026, 11, 1), date(2026, 11, 20))
        assert [p["label"] for p in ps if p["active"]] == ["Este mes"]
        assert ps[1]["start"] == date(2026, 10, 1) and ps[1]["end"] == date(2026, 10, 31)
        assert ps[2]["start"] == date(2026, 10, 1)            # trimestre T4
        assert "start=2026-11-01&end=2026-11-20" in ps[0]["query"]


class TestBuildPage:
    def test_hero_and_deltas_against_previous(self):
        prev = metrics()
        prev["financials"]["combined"] = {"income": 500.0, "expense": 400.0, "profit": 100.0}
        page = build_page(metrics(), {}, PERIOD, prev)
        h = page["hero"]
        assert h["profit"] == 600.0 and h["tone"] == "success"
        assert h["delta_profit"]["pct"] == 500.0 and h["delta_profit"]["tone"] == "success"
        assert h["delta_income"]["pct"] == 100.0
        assert h["delta_expense"]["dir"] == "flat" and h["income_pct"] + h["expense_pct"] == pytest.approx(100, abs=0.2)

    def test_negative_profit_is_danger(self):
        m = metrics()
        m["financials"]["combined"] = {"income": 100.0, "expense": 300.0, "profit": -200.0}
        assert build_page(m, {}, PERIOD)["hero"]["tone"] == "danger"

    def test_sources_vat_funnel_companies(self):
        page = build_page(metrics(), {"total": 10}, PERIOD)
        assert [s["key"] for s in page["sources"]] == ["combined", "documents", "movements"]
        assert page["sources"][2]["extra_value"] == 4
        v = page["vat"]
        assert v["to_pay"] and v["tone"] == "warning" and v["collected_pct"] == 100.0 and v["paid_pct"] == 37.5
        assert v["has_extras"] and v["withholding_suffered"] == 12.0
        assert [x["count"] for x in page["funnel"]] == [6, 3, 1] and page["funnel_total"] == 10
        assert "status=approved" in page["funnel"][0]["url"] and "date_from=2026-11-01" in page["funnel"][0]["url"]
        assert [c["tone"] for c in page["companies"]] == ["success", "danger"] and page["companies"][0]["pct"] == 100.0
        assert [s["value"] for s in page["chart_data"]["status"]] == [4, 2, 3, 1]

    def test_vat_to_compensate(self):
        m = metrics()
        m["financials"]["documents"]["vat"] = {"collected": 10.0, "paid": 50.0, "balance": -40.0}
        v = build_page(m, {}, PERIOD)["vat"]
        assert not v["to_pay"] and v["tone"] == "info" and v["abs_balance"] == 40.0

    def test_empty_and_partial_inputs(self):
        page = build_page({}, {}, {})
        assert page["hero"]["profit"] == 0 and page["funnel_total"] == 0 and page["companies"] == []
        assert not page["automation"]["has_decisions"] and page["automation"]["extraction"] is None
        assert not page["has_monthly"] and not page["has_quarters"]
        build_page({"documents": {"total": 1}}, {}, PERIOD)       # el mismo formato que simula test_views


class TestView:
    url = "/metrics/dashboard/"

    def test_requires_login(self, client):
        assert client.get(self.url).status_code == 302

    def test_empty_account_renders(self, auth_client):
        body = auth_client.get(self.url).content.decode()
        assert "Beneficio del periodo" in body and "No hay facturas aprobadas" in body
        assert "Sin decisiones en el periodo" in body

    def test_renders_with_data_and_presets(self, auth_client, user):
        today = date.today()
        f.DocumentFactory(client=user.client, status="approved", flow="in", issue_date=today, base_amount=D("1000"),
                          tax_amount=D("210"), total_amount=D("1210"), review_level="manual")
        f.DocumentFactory(client=user.client, status="approved", flow="out", issue_date=today, base_amount=D("400"),
                          tax_amount=D("84"), total_amount=D("484"))
        r = auth_client.get(self.url)
        body = r.content.decode()
        assert r.context["hero"]["profit"] == 600.0 and r.context["vat"]["to_pay"]
        for text in ("Desglose por origen", "IVA del periodo", "Por trimestre", "Principales terceros",
                     "Documentos del periodo", "Automatización", "Este mes", "Mes anterior"):
            assert text in body
        assert 'id="metrics-data"' in body and 'data-tab="movements"' in body
        assert body.count('class="preset active"') == 1

    def test_custom_range_and_swapped_dates(self, auth_client):
        r = auth_client.get(self.url, {"start": "2026-03-31", "end": "2026-03-01"})
        assert r.status_code == 200 and r.context["period"]["start"] == date(2026, 3, 1)
        assert not any(p["active"] for p in r.context["presets"])

    def test_labels_in_spanish(self, user):
        f.DocumentFactory(client=user.client, status="approved", flow="in", issue_date=date(2026, 2, 3))
        m = MetricsService.get_user_metrics(user, date(2026, 1, 1), date(2026, 3, 31))
        assert m["charts"]["income_expense_monthly"][0]["period"] == "Feb 2026"
        m = MetricsService.get_user_metrics(user, date(2026, 2, 1), date(2026, 2, 28))
        assert m["charts"]["income_expense_monthly"][0]["period"] == "3 Feb"

    def test_other_tenant_data_not_shown(self, auth_client, other_user):
        f.DocumentFactory(client=other_user.client, status="approved", flow="in", issue_date=date.today(),
                          base_amount=D("77777"), tax_amount=D("0"), total_amount=D("77777"))
        assert "77.777" not in auth_client.get(self.url).content.decode()


class TestHeroTone:
    def test_negative_profit_renders_danger_tone(self, auth_client, user):
        from documents.tests import factories as fx
        fx.DocumentFactory(client=user.client, status="approved", flow="out", issue_date=date.today(),
                           base_amount=D("500"), tax_amount=D("0"), total_amount=D("500"))
        body = auth_client.get("/metrics/dashboard/").content.decode()
        hero = body.split('class="panel hero-kpi')[1].split(">")[0]
        assert "tone-danger" in hero and "tone-success" not in hero

    def test_positive_profit_renders_success_tone(self, auth_client, user):
        from documents.tests import factories as fx
        fx.DocumentFactory(client=user.client, status="approved", flow="in", issue_date=date.today(),
                           base_amount=D("500"), tax_amount=D("0"), total_amount=D("500"))
        hero = auth_client.get("/metrics/dashboard/").content.decode().split('class="panel hero-kpi')[1].split(">")[0]
        assert "tone-success" in hero
