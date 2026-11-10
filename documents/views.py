from django.conf import settings
from django.shortcuts import redirect, get_object_or_404
from .models import Document
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, ListView, DetailView, TemplateView, FormView
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models.functions import Coalesce
from django.db.models import DecimalField, Sum, Count
from finance.models import FinancialMovement
from datetime import datetime
from .selectors.document_selector import DocumentSelector
from .services import DocumentService
from django.contrib.auth import get_user_model
from .filters.document_filters import get_filtered_documents, get_exportable_documents
from documents.models import Company
from .forms import DocumentRectificationForm, DocumentUploadForm
from .models import DocumentCategory, Folder, Tag
from .services import upload as upload_service
from django.urls import reverse
from billing_ai.storage import private_file_response

User = get_user_model()

class DocumentListView(LoginRequiredMixin, ListView): 
    template_name = "private/documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 20
    
    def get_queryset(self):
        return get_filtered_documents(
            self.request,
            base_qs=DocumentSelector.for_client(self.request.user.client)
            .select_related("company", "folder")
            .prefetch_related("tags"),
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        page_obj = context.get("page_obj")
        first_doc = page_obj.object_list.first() if page_obj else None

        context["client"] = first_doc.client if first_doc else None
        context["document_types"] = Document.TYPE_CHOICES
        client = self.request.user.client
        context["companies"] = Company.objects.filter(client=client).order_by("name")
        context["folders"] = Folder.objects.filter(client=client)
        context["tags"] = Tag.objects.filter(client=client)
        context["categories"] = DocumentCategory.objects.filter(client=client)
        context["quarters"] = DocumentSelector.available_quarters(client)
        context["processing_count"] = DocumentSelector.processing_count(client)
        context["processing_choices"] = Document.PROCESSING_CHOICES

        # Querystring sin page (preserva sort/order para paginación y exports)
        querydict = self.request.GET.copy()
        querydict.pop("page", None)
        context["querystring"] = querydict.urlencode()

        # Querystring sin page/sort/order para construir links de ordenación
        sort_dict = self.request.GET.copy()
        sort_dict.pop("page", None)
        sort_dict.pop("sort", None)
        sort_dict.pop("order", None)
        context["sort_base"] = sort_dict.urlencode()

        context["sort"] = self.request.GET.get("sort", "date")
        context["order"] = self.request.GET.get("order", "desc")
        return context
    
    

class DocumentDetailView(LoginRequiredMixin, DetailView):
    template_name = "private/documents/document_detail.html"
    context_object_name = "document"

    def get_queryset(self):
        client = self.request.user.client
        return DocumentSelector.detail_queryset(client)
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        action = request.POST.get("action")

        # --- Reintentar la extracción de un documento fallido ---
        if action == "retry":
            if upload_service.retry_processing(self.object):
                messages.success(request, "Documento enviado de nuevo a extracción.")
            else:
                messages.warning(request, "Este documento no se puede reprocesar.")
            return redirect("documents:detail", pk=self.object.pk)

        # Mientras se extrae, los datos no son definitivos
        if self.object.is_processing and action in ("approve", "reject", "save"):
            messages.warning(request, "El documento se está procesando; espera a que termine.")
            return redirect("documents:detail", pk=self.object.pk)

        # --- Aprobar ---
        if action == "approve" and self.object.status == "pending":
            return approve_document(request, self.object)

        # --- Rechazar ---
        if action == "reject" and self.object.status == "pending":
            rejection_reason = request.POST.get("rejection_reason")
            return reject_document(request, self.object, rejection_reason)

        # --- Guardar cambios ---
        if action == "save":
            return save_document(request, self.object)
        
        # --- Archivar ---
        if action == "archive" and self.object.status in ["approved", "rejected"]:
            return archive_document(request, self.object)
        
        # --- Desarchivar ---
        if action == "unarchive" and self.object.is_archived:
            return unarchive_document(request, self.object)
        
        if action == "rectify" and self.object.status in ["approved", "rejected"] and not self.object.is_archived:
            return redirect("documents:rectify", pk=self.object.pk)

        # Si no hay acción reconocida, redirigir
        messages.warning(request, "Acción no reconocida.")
        return redirect("documents:detail", pk=self.object.pk)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.object

        root = document.parent_document or document

        all_versions = (
            DocumentSelector.version_history(document)
            .exclude(pk=document.pk)
        )

        previous_versions = all_versions.filter(version__lt=document.version).order_by("-version")
        next_versions = all_versions.filter(version__gt=document.version).order_by("version")

        context["previous_versions"] = previous_versions
        context["next_versions"] = next_versions
        context["has_previous_versions"] = previous_versions.exists()
        context["has_next_versions"] = next_versions.exists()
        context["root_document"] = root
        context["has_versions"] = previous_versions.exists() or next_versions.exists()

        client = self.request.user.client
        context["companies"] = Company.objects.filter(client=client).order_by("name")
        context["folders"] = Folder.objects.filter(client=client)
        context["categories"] = DocumentCategory.objects.filter(client=client)
        context["document_types"] = Document.TYPE_CHOICES
        context["tag_names"] = ", ".join(t.name for t in document.tags.all())
        context["all_tag_names"] = list(Tag.objects.filter(client=client).values_list("name", flat=True))
        context["tax_lines"] = document.tax_lines.all()
        context["invoice_lines"] = document.lines.all()
        context["issues"] = sorted(
            document.validation_issues or [],
            key=lambda i: {"error": 0, "warning": 1}.get(i.get("severity"), 2),
        )
        context["issue_fields"] = {i.get("field") for i in document.validation_issues or [] if i.get("field")}
        context["processing_error"] = self._processing_error(document)
        context["next_pending"] = (
            DocumentSelector.pending(client)
            .filter(is_archived=False, processing_status__in=("processed", "failed"))
            .exclude(pk=document.pk)
            .order_by("created_at", "pk")
            .first()
        )

        return context

    @staticmethod
    def _processing_error(document):
        if document.processing_status != "failed":
            return None
        run = document.extraction_runs.filter(status="failed").first()
        return {
            "code": run.error_code if run else "",
            "message": (run.error_message if run else "") or "No se pudo extraer el documento.",
        }


def approve_document(request, document):
    DocumentService.approve(document, user=request.user)
    messages.success(request, "El documento ha sido aprobado.")
    return redirect("documents:detail", pk=document.pk)

def reject_document(request, document, reason=None):
    DocumentService.reject(document, user=request.user, reason=reason)
    messages.success(request, "El documento ha sido rechazado.")
    return redirect("documents:detail", pk=document.pk)

def save_document(request, document):
    try:
        DocumentService.update_from_form(
            document=document,
            user=request.user,
            data=request.POST
        )
    except ValueError:
        messages.error(request, "Importe inválido en uno de los campos.")
        return redirect("documents:detail", pk=document.pk)

    messages.success(request, "Cambios guardados correctamente.")
    return redirect("documents:detail", pk=document.pk)

def archive_document(request, document): 
    DocumentService.archive(document, user=request.user)
    messages.success(request, "Documento archivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

def unarchive_document(request, document):
    DocumentService.unarchive(document, user=request.user)
    messages.warning(request, "Documento desarchivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

class DashboardView(LoginRequiredMixin,TemplateView):
    template_name="private/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        client = self.request.user.client
        client = client if client else None

        qs = DocumentSelector.pending(client)
        today = timezone.now().date()
        month_start = today.replace(day=1)

        movement_qs = FinancialMovement.objects.filter(
            client=client,
            date__gte=month_start,
            date__lte=today,
            is_active=True,
        )

        pending_count = qs.count()
        required_count = qs.filter(review_level="required").count() or 0
        recommended_count = qs.filter(review_level="recommended").count() or 0

        income_total = movement_qs.filter(movement_type="income").aggregate(
            total=Coalesce(Sum("amount"), 0, output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"]
        expense_total = movement_qs.filter(movement_type="expense").aggregate(
            total=Coalesce(Sum("amount"), 0, output_field=DecimalField(max_digits=12, decimal_places=2))
        )["total"]
        balance = income_total - expense_total

        unreconciled_count = movement_qs.filter(is_reconciled=False).count()

        top_expense_categories = (
            movement_qs.filter(movement_type="expense")
            .values("category__name", "category__icon")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:3]
        )

        context = {
            "pending_documents": qs.order_by("-created_at")[:10],
            "pending_count": pending_count,
            "required_review_count": required_count,
            "recommended_review_count": recommended_count,
            "client": client,
            "finance_period_label": f"{month_start.strftime('%d/%m/%Y')} - {today.strftime('%d/%m/%Y')}",
            "finance_income_total": income_total,
            "finance_expense_total": expense_total,
            "finance_balance": balance,
            "unreconciled_movements_count": unreconciled_count,
            "recent_movements": movement_qs.select_related("category")[:5],
            "top_expense_categories": top_expense_categories,
        }

        return context
    
from .utils import export_invoices_to_pdf, export_to_csv, export_to_excel, build_pdf_context
class DocumentExportView(LoginRequiredMixin, View):

    def get_exportable_queryset(self, ids=None):
        client = self.request.user.client

        base_qs = DocumentSelector.for_client(client)

        qs = get_filtered_documents(self.request, base_qs=base_qs)

        if ids:
            qs = qs.filter(id__in=ids)
        
        qs = get_exportable_documents(qs)

        return qs
    
    def get(self, request):
        qs = self.get_exportable_queryset()
        return export_to_csv(qs)
    
    def post(self, request):
        ids = request.POST.getlist("ids")
        fmt = request.POST.get("format", "csv")

        qs = self.get_exportable_queryset(ids=ids)

        if fmt == "pdf":
            context = build_pdf_context(qs, request)

            return export_invoices_to_pdf(
                qs, 
                base_url=request.build_absolute_uri("/"),
                **context,
            )
        
        if fmt == "xlsx":
            return export_to_excel(qs)
        return export_to_csv(qs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context
    
    
from django.db.models import Sum, Min, Max, Avg, Count
from .services.signs import signed_amount
class DocumentExportPreviewView(LoginRequiredMixin, ListView):
    template_name = "private/documents/document_export_preview.html"

    def get_exportable_queryset(self, ids=None):
        client = self.request.user.client

        base_qs = DocumentSelector.for_client(client)

        qs = get_filtered_documents(self.request, base_qs=base_qs)

        if ids:
            qs = qs.filter(id__in=ids)

        exportable_qs = get_exportable_documents(base_qs=qs)
        non_exportable_qs = qs.exclude(id__in=exportable_qs.values_list("id", flat=True))

        self.non_exportable_count = non_exportable_qs.count()

        return exportable_qs

    def get_queryset(self):
        ids = self.request.GET.getlist("ids")
        return self.get_exportable_queryset(ids=ids)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        qs = self.get_queryset()

        selected_format = self.request.GET.get("format", "xlsx")

        context["documents_count"] = qs.count()
        context["providers_count"] = qs.values("company").distinct().count()

        flow_counts = {
            item["flow"]: item["cnt"]
            for item in qs.values("flow").annotate(cnt=Count("flow"))
        }
        in_count = flow_counts.get("in", 0)
        out_count = flow_counts.get("out", 0)
        context["companies_label"] = "Clientes" if in_count > out_count else "Proveedores"
        
        context["selected_format"] = selected_format
        context["selected_ids"] = self.request.GET.getlist("ids")

        if selected_format == "pdf":
            context["pdf_context"] = build_pdf_context(qs, self.request)

        summary = qs.aggregate(
            base_total=Sum(signed_amount("base_amount")),
            tax_total=Sum(signed_amount("tax_amount")),
            grand_total=Sum(signed_amount("total_amount")),
            min_date=Min("issue_date"),
            max_date=Max("issue_date"),
            avg_confidence=Avg("confidence_global"),
        )

        summary["min_date"] = format_date(summary["min_date"], format="d MMMM y", locale="es")
        summary["max_date"] = format_date(summary["max_date"], format="d MMMM y", locale="es")
        context["summary"] = summary
        context["non_exportable_count"] = self.non_exportable_count

        context["sort"] = self.request.GET.get("sort", "date")
        context["order"] = self.request.GET.get("order", "desc")
        sort_dict = self.request.GET.copy()
        sort_dict.pop("sort", None)
        sort_dict.pop("order", None)
        context["sort_base"] = sort_dict.urlencode()

        return context
    
class DocumentPDFPreviewView(LoginRequiredMixin, View):
    def get(self, request):
        ids = request.GET.getlist("ids")
        client = request.user.client

        qs = DocumentSelector.for_client(client)
        qs = get_filtered_documents(request, base_qs=qs)
        if ids:
            qs = qs.filter(id__in=ids)

        qs = get_exportable_documents(base_qs=qs)

        pdf_context = build_pdf_context(qs, request)

        return export_invoices_to_pdf(
            request,
            base_url=request.build_absolute_uri("/"),
            **pdf_context,
            inline=True,
        )

from .services import MetricsService
from babel.dates import format_date
from django.utils import timezone

class MetricsDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "private/metrics/dashboard.html"

    def get_dashboard_metrics(self, request):
        start = request.GET.get("start")
        end = request.GET.get("end")
        today = timezone.now().date()

        def _date(value, default):
            try:
                return parse_date(value or "") or default
            except ValueError:
                return default

        start = _date(start, today.replace(day=1))
        end = _date(end, today)
        if start > end:
            start, end = end, start

        first_day_of_month = today.replace(day=1)
        is_current_month = (
            start == first_day_of_month and end == today
        )

        metrics = MetricsService.get_user_metrics(
            user=request.user,
            start=start,
            end=end
        )

        # Formato bonito español
        metrics["period"] = {
            "start": start,
            "end": end,
            "start_formatted": format_date(start, format="d MMMM y", locale="es"),
            "end_formatted": format_date(end, format="d MMMM y", locale="es"),
            "is_current_month": is_current_month, 
        }

        return metrics

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metrics = self.get_dashboard_metrics(self.request)
        context.update(metrics)

        historical_metrics = MetricsService.get_historical_metrics(self.request.user)

        client = self.request.user.client
        context["client"] = client if client else None
        context["period"] = {
            "start": metrics["period"]["start"],
            "end": metrics["period"]["end"],
            "start_formatted": metrics["period"]["start_formatted"],
            "end_formatted": metrics["period"]["end_formatted"],
            "is_current_month": metrics["period"]["is_current_month"]
        }
        context["historical_metrics"] = historical_metrics

        return context


class DocumentRectifyView(LoginRequiredMixin, FormView):
    template_name = "private/documents/document_rectify.html"
    form_class = DocumentRectificationForm

    def dispatch(self, request, *args, **kwargs):
        self.document = get_object_or_404(
            DocumentSelector.detail_queryset(request.user.client),
            pk=kwargs.get("pk")
        )

        if self.document.status not in ["approved", "rejected"] or self.document.is_archived:
            messages.warning(request, "Este documento no puede ser rectificado.")
            return redirect("documents:detail", pk=self.document.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["client"] = self.request.user.client
        return kwargs

    def get_initial(self):
        initial = {
            "base_amount": self.document.base_amount,
            "tax_amount": self.document.tax_amount,
            "tax_percentage": self.document.tax_percentage,
            "total_amount": self.document.total_amount,
            "issue_date": self.document.issue_date.strftime("%Y-%m-%d") if self.document.issue_date else None,
            "document_number": self.document.document_number,
            "company": self.document.company,
        }
        return initial

    def form_valid(self, form):
        new_doc = DocumentService.rectify(
            document=self.document,
            user=self.request.user,
            reason=form.cleaned_data["rectification_reason"],
            form_data=form.cleaned_data
        )
        messages.success(self.request, f"Documento rectificado (v{new_doc.version})")
        return redirect("documents:detail", pk=new_doc.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["companies"] = Company.objects.filter(client=self.request.user.client).order_by("name")
        context["document"] = self.document
        context["is_rectification"] = True
        return context

class DocumentFileView(LoginRequiredMixin, View):
    """Entrega el archivo original solo si pertenece al cliente del usuario."""

    def get(self, request, pk):
        document = get_object_or_404(
            Document.all_objects.only("id", "client_id", "file", "original_name"),
            pk=pk,
            client=request.user.client,
        )
        return private_file_response(document.file, download_name=document.original_name or None)



class DocumentUploadView(LoginRequiredMixin, FormView):
    """Subida multi-archivo (selector, arrastrar o cámara del móvil)."""
    template_name = "private/documents/document_upload.html"
    form_class = DocumentUploadForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["max_mb"] = settings.UPLOAD_MAX_FILE_MB
        context["max_pages"] = settings.EXTRACTION_MAX_PAGES
        context["processing_count"] = DocumentSelector.processing_count(self.request.user.client)
        return context

    def form_valid(self, form):
        client, user = self.request.user.client, self.request.user
        results = upload_service.upload_many(
            client=client, user=user, files=form.cleaned_data["files"], origin="upload",
        ) + upload_service.upload_many(
            client=client, user=user, files=form.cleaned_data["photos"], origin="mobile",
        )
        created = [r for r in results if r.status == upload_service.CREATED]
        if created:
            messages.success(self.request, f"{len(created)} documento(s) subido(s); se están procesando.")
        for r in results:
            if r.status == upload_service.DUPLICATE:
                messages.warning(self.request, f"«{r.name}»: {r.message}")
            elif r.status == upload_service.REJECTED:
                messages.error(self.request, f"«{r.name}»: {r.message}")
        if created:
            return redirect(f"{reverse('documents:list')}?processing=active")
        return redirect("documents:upload")
