"""Inicio: servicio de datos y vista."""
import re
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.urls import reverse

from documents.models import DocumentAuditLog
from documents.services.dashboard_service import (
    DashboardService, add_months, delta, greeting, sparkline,
)
from documents.tests import factories as f
from finance.models import FinancialMovement, MovementCategory

pytestmark = pytest.mark.django_db
TODAY = date(2026, 11, 20)


def mv(client, kind, amount, d, reconciled=True, cat=None, **kw):
    cat = cat or MovementCategory.objects.get_or_create(client=client, name=f"c-{kind}", type=kind,
                                                        defaults={"color": "#112233", "icon": "fa-solid fa-tag"})[0]
    return FinancialMovement.objects.create(client=client, category=cat, movement_type=kind, amount=D(amount),
                                            date=d, is_reconciled=reconciled, **kw)


class TestHelpers:
    def test_add_months_across_years(self):
        assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
        assert add_months(date(2026, 11, 20), 3) == date(2027, 2, 1)

    def test_delta_tone_depends_on_meaning(self):
        assert delta(D(120), D(100))["tone"] == "success" and delta(D(120), D(100))["dir"] == "up"
        assert delta(D(120), D(100), higher_is_good=False)["tone"] == "danger"
        assert delta(D(80), D(100), higher_is_good=False)["tone"] == "success"
        assert delta(D(5), D(0)) is None
        assert delta(D(100), D(100))["dir"] == "flat"

    def test_sparkline(self):
        assert sparkline([1]) == ""
        pts = sparkline([0, 5, 10]).split()
        assert len(pts) == 3 and pts[0].startswith("0.0,") and pts[2].startswith("100.0,")
        assert sparkline([3, 3, 3])  # serie plana: no divide por cero

    def test_greeting(self):
        class T:  # noqa: D401
            def __init__(self, h): self.hour = h
        assert greeting(T(9)) == "Buenos días" and greeting(T(16)) == "Buenas tardes" and greeting(T(22)) == "Buenas noches"


class TestFinance:
    def test_series_totals_and_comparison_same_period(self, user):
        c = user.client
        mv(c, "income", "1000", date(2026, 11, 5))
        mv(c, "expense", "400", date(2026, 11, 10))
        mv(c, "income", "500", date(2026, 10, 3))       # dentro del tramo comparable (1-20 oct)
        mv(c, "income", "9999", date(2026, 10, 28))     # fuera del tramo: no cuenta en la comparación
        mv(c, "expense", "50", date(2026, 6, 1))        # fuera de la ventana de 6 meses
        data = DashboardService.finance(c, TODAY)
        k = {x["key"]: x for x in data["kpis"]}
        assert k["income"]["value"] == D(1000) and k["expense"]["value"] == D(400) and k["balance"]["value"] == D(600)
        assert k["income"]["delta"]["pct"] == 100.0      # 1000 vs 500
        assert data["chart"]["labels"] == ["Jun", "Jul", "Ago", "Sep", "Oct", "Nov"]
        assert data["chart"]["income"][-1] == 1000.0 and data["chart"]["income"][-2] == 10499.0
        assert data["chart"]["expense"][0] == 50.0

    def test_inactive_and_other_tenant_excluded(self, user, other_user):
        mv(user.client, "income", "100", date(2026, 11, 2), is_active=False)
        mv(other_user.client, "income", "700", date(2026, 11, 2))
        k = {x["key"]: x for x in DashboardService.finance(user.client, TODAY)["kpis"]}
        assert k["income"]["value"] == D(0) and k["income"]["delta"] is None

    def test_top_expenses_sorted_with_relative_pct(self, user):
        c = user.client
        big = MovementCategory.objects.create(client=c, name="Alquiler", type="expense", color="#aa0000")
        small = MovementCategory.objects.create(client=c, name="Café", type="expense")
        mv(c, "expense", "800", date(2026, 11, 3), cat=big)
        mv(c, "expense", "200", date(2026, 11, 4), cat=small)
        mv(c, "expense", "999", date(2026, 10, 4), cat=small)    # otro mes
        top = DashboardService.top_expenses(c, TODAY)
        assert [t["name"] for t in top] == ["Alquiler", "Café"] and [t["pct"] for t in top] == [100.0, 25.0]


class TestDocuments:
    def test_funnel_attention_and_isolation(self, user, other_user):
        c = user.client
        f.DocumentFactory(client=c, status="pending", review_level="required")
        f.DocumentFactory(client=c, status="pending", review_level="recommended")
        f.DocumentFactory(client=c, status="approved")
        f.DocumentFactory(client=c, status="pending", processing_status="processing")
        f.DocumentFactory(client=c, status="pending", processing_status="failed")
        f.DocumentFactory(client=c, status="approved", is_archived=True)      # archivados fuera
        f.DocumentFactory(client=other_user.client, status="pending", review_level="required")
        mv(c, "income", "10", TODAY, reconciled=False)
        data = DashboardService.documents(c)
        counts = {s["key"]: s["count"] for s in data["funnel"]}
        assert counts == {"processing": 1, "failed": 1, "review": 2, "approved": 1, "rejected": 0}
        assert data["funnel_total"] == 5 and data["pending_count"] == 2 and data["processing_count"] == 1
        assert sum(s["pct"] for s in data["funnel"]) == pytest.approx(100, abs=0.2)
        labels = {a["label"]: a["count"] for a in data["attention"]}
        assert labels["Documentos con revisión obligatoria"] == 1 and labels["Extracciones con error"] == 1
        assert labels["Movimientos sin conciliar"] == 1

    def test_empty_account(self, user):
        data = DashboardService.documents(user.client)
        assert data["funnel_total"] == 0 and data["attention"] == [] and data["pending_count"] == 0

    def test_activity_texts_and_tenant(self, user, other_user):
        d = f.DocumentFactory(client=user.client, document_number="FAC-1")
        DocumentAuditLog(document=d, user=user, action="approved").save()
        DocumentAuditLog(document=d, user=None, action="approved", changes={"auto": True}).save()
        DocumentAuditLog(document=d, user=None, action="extracted", changes={"failed": True}).save()
        DocumentAuditLog(document=f.DocumentFactory(client=other_user.client), user=None, action="created").save()
        acts = DashboardService.activity(user.client)
        assert [a["verb"] for a in acts] == ["Falló la extracción de", "Se aprobó automáticamente", "Aprobaste"]
        assert acts[0]["tone"] == "danger" and acts[2]["who"] == user.username and acts[2]["label"] == "FAC-1"


class TestView:
    def test_requires_login(self, client):
        assert client.get(reverse("dashboard")).status_code == 302

    def test_renders_all_sections_with_data(self, auth_client, user):
        c = user.client
        today = date.today()
        mv(c, "income", "1500", today.replace(day=1))
        mv(c, "expense", "300", today.replace(day=1), reconciled=False)
        f.DocumentFactory(client=c, status="pending", review_level="required")
        d = f.DocumentFactory(client=c, status="approved")
        DocumentAuditLog(document=d, user=user, action="approved").save()
        body = auth_client.get(reverse("dashboard")).content.decode()
        for text in ("Requiere tu atención", "Estado de los documentos", "Top gastos del mes", "Actividad reciente",
                     "Ingresos y gastos", "Documentos pendientes", "Últimos movimientos", "Subir documentos"):
            assert text in body
        assert 'id="home-chart"' in body and "<polyline" in body and "funnel-seg" in body
        assert re.search(r"Buen(os días|as tardes|as noches), ", body)

    def test_empty_states_do_not_break(self, auth_client):
        body = auth_client.get(reverse("dashboard")).content.decode()
        assert "Todo al día" in body and "Aún no hay documentos" in body and "Sin gastos registrados" in body

    def test_autorefresh_only_while_processing(self, auth_client, user):
        assert "data-autorefresh" not in auth_client.get(reverse("dashboard")).content.decode()
        f.DocumentFactory(client=user.client, status="pending", processing_status="queued")
        assert 'data-autorefresh="6"' in auth_client.get(reverse("dashboard")).content.decode()

    def test_other_tenant_data_never_shown(self, auth_client, other_user):
        mv(other_user.client, "income", "123456", date.today().replace(day=1))
        f.DocumentFactory(client=other_user.client, original_name="secreto.pdf", status="pending")
        body = auth_client.get(reverse("dashboard")).content.decode()
        assert "secreto.pdf" not in body and "123.456" not in body
