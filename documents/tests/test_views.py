from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from documents.models import Document


@pytest.mark.django_db
class TestDocumentViews:
    def test_document_list_requires_login(self, client):
        response = client.get(reverse("documents:list"))

        assert response.status_code == 302
        assert "/login/" in response.url

    def test_document_list_shows_only_current_client_documents(self, auth_client, document):
        response = auth_client.get(reverse("documents:list"))

        assert response.status_code == 200
        assert list(response.context["documents"]) == [document]
        assert response.context["client"] == document.client

    def test_document_detail_post_approve_redirects_and_updates_document(self, auth_client, document):
        response = auth_client.post(reverse("documents:detail", kwargs={"pk": document.pk}), data={"action": "approve"})
        document.refresh_from_db()

        assert response.status_code == 302
        assert response.url == reverse("documents:detail", kwargs={"pk": document.pk})
        assert document.status == "approved"

    def test_document_detail_save_invalid_amount_sets_error_message(self, auth_client, document):
        response = auth_client.post(
            reverse("documents:detail", kwargs={"pk": document.pk}),
            data={"action": "save", "base_amount": "abc"},
            follow=True,
        )

        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert "Importe inválido" in messages[0]

    def test_document_export_returns_csv_for_filtered_queryset(self, auth_client, approved_document):
        response = auth_client.get(reverse("documents:export"))

        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        assert "Número documento" in response.content.decode("utf-8")

    def test_document_export_preview_builds_summary(self, auth_client, approved_document):
        response = auth_client.get(reverse("documents:export_preview"))

        assert response.status_code == 200
        assert response.context["documents_count"] == 1
        assert response.context["providers_count"] == 1
        assert response.context["summary"]["grand_total"] == Decimal("121")

    def test_document_rectify_view_redirects_non_rectifiable_document(self, auth_client, document):
        response = auth_client.get(reverse("documents:rectify", kwargs={"pk": document.pk}), follow=True)

        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert response.redirect_chain[-1][0] == reverse("documents:detail", kwargs={"pk": document.pk})
        assert any("no puede ser rectificado" in message.lower() for message in messages)

    def test_document_rectify_view_creates_new_version(self, auth_client, approved_document):
        response = auth_client.post(
            reverse("documents:rectify", kwargs={"pk": approved_document.pk}),
            data={
                "base_amount": "150.00",
                "tax_amount": "31.50",
                "tax_percentage": "21.00",
                "total_amount": "181.50",
                "issue_date": "2026-03-10",
                "document_number": "INV-002",
                "company": approved_document.company_id,
                "rectification_reason": "Importe corregido",
            },
        )

        new_doc = Document.objects.exclude(pk=approved_document.pk).get()
        assert response.status_code == 302
        assert response.url == reverse("documents:detail", kwargs={"pk": new_doc.pk})
        assert new_doc.version == 2
        assert new_doc.rectification_reason == "Importe corregido"

    def test_metrics_dashboard_view_uses_service_outputs(self, auth_client):
        fake_metrics = {
            "period": {"start": "2026-03-01", "end": "2026-03-31", "start_formatted": "1 marzo 2026", "end_formatted": "31 marzo 2026", "is_current_month": False},
            "documents": {"total": 1},
        }
        with patch("documents.views.MetricsService.get_user_metrics", return_value=fake_metrics), patch(
            "documents.views.MetricsService.get_historical_metrics", return_value={"total": 1}
        ):
            response = auth_client.get("/metrics/dashboard/?start=2026-03-01&end=2026-03-31")

        assert response.status_code == 200
        assert response.context["documents"]["total"] == 1
        assert response.context["historical_metrics"] == {"total": 1}
