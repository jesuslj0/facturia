from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
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
from .selectors import drive_selector as drive
from .selectors.document_selector import DocumentSelector
from .services import DocumentService
from .services.dashboard_service import DashboardService
from .services.metrics_page import build_page, presets, previous_period
from datetime import date
from django.contrib.auth import get_user_model
from .filters.document_filters import get_filtered_documents, get_exportable_documents
from documents.models import Company
from .forms import DocumentRectificationForm, DocumentUploadForm
from .models import Tag
from .services import folders as folder_service
from .services import upload as upload_service
from billing_ai import listing
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
        context["folders"] = folder_service.with_labels(client)
        context["tags"] = Tag.objects.filter(client=client)
        context["quarters"] = DocumentSelector.available_quarters(client)
        context["processing_count"] = DocumentSelector.processing_count(client)
        context["processing_choices"] = Document.PROCESSING_CHOICES
        context.update(self._filter_ui(context))

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
    
    

    def _filter_ui(self, context):
        """Pestañas de estado, chips de filtros activos y paginación para la plantilla."""
        request = self.request
        names = lambda qs: {str(o.pk): o.name for o in qs}  # noqa: E731
        types = dict(Document.TYPE_CHOICES)
        quarter_labels = {k: v for k, v in context["quarters"]}
        spec = [
            ("q", "Búsqueda", None, False),
            ("status", "Estado", {"pending": "Pendientes", "approved": "Aprobados", "rejected": "Rechazados"}, False),
            ("document_type", "Tipo", types, True),
            ("flow", "Flujo", {"in": "Venta", "out": "Compra", "unknown": "Por revisar"}, True),
            ("company", "Empresa", None, True),
            ("folder", "Carpeta", {str(f.pk): f.label for f in context["folders"]}, True),
            ("tag", "Etiqueta", names(context["tags"]), True),
            ("quarter", "Trimestre", quarter_labels, True),
            ("review_level", "Revisión", {"auto": "Auto", "manual": "Manual", "recommended": "Recomendada", "required": "Obligatoria"}, True),
            ("processing", "Extracción", {"active": "En proceso", "failed": "Con error", "processed": "Procesados"}, True),
            ("doc_status", "Archivo", {"archived": "Archivados", "all": "Todos (con archivados)"}, True),
            ("date_from", "Desde", listing.pretty, True),
            ("date_to", "Hasta", listing.pretty, True),
        ]
        filters = listing.active_filters(request, spec)
        page_obj = context.get("page_obj")
        return {
            "status_tabs": listing.status_tabs(request, [
                ("", "Todos"), ("pending", "Pendientes"), ("approved", "Aprobados"), ("rejected", "Rechazados"),
            ]),
            "active_filters": filters,
            "panel_filter_count": sum(1 for f in filters if f["in_panel"]),
            "page_numbers": listing.page_window(page_obj) if page_obj and page_obj.paginator.num_pages > 1 else [],
        }


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

        # --- Organización (carpeta y etiquetas): vale en cualquier estado ---
        if action == "organize":
            return organize_document(request, self.object)

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
        context["folders"] = folder_service.with_labels(client)
        context["document_types"] = Document.TYPE_CHOICES
        context["tag_names"] = ", ".join(t.name for t in document.tags.all())
        context["all_tag_names"] = list(Tag.objects.filter(client=client).values_list("name", flat=True))
        context["tax_lines"] = document.tax_lines.all()
        invoice_lines = list(document.lines.all())
        context["invoice_lines"] = invoice_lines
        # Filtrar líneas por página solo si es PDF y todas las líneas saben su página
        context["lines_by_page"] = bool(
            document.is_pdf and invoice_lines and all(l.page for l in invoice_lines)
        )
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



def _save_error(exc):
    """Mensaje legible para un fallo al guardar los datos del formulario de revisión."""
    if isinstance(exc, ValidationError):
        return "Datos no válidos: " + "; ".join(exc.messages)
    return "Importe inválido en uno de los campos."


def approve_document(request, document):
    # El formulario de revisión se envía junto con la aprobación: primero se guardan los cambios
    # sin guardar (flujo, importes…) y luego se aprueba. Un POST solo con `action` aprueba tal cual.
    if "flow" in request.POST:
        try:
            DocumentService.update_from_form(document=document, user=request.user, data=request.POST)
        except (ValueError, ValidationError) as exc:
            messages.error(request, _save_error(exc))
            return redirect("documents:detail", pk=document.pk)

    blockers = document.approval_blockers()
    if blockers:
        messages.warning(request, "No se puede aprobar: falta " + ", ".join(blockers) + ".")
        return redirect("documents:detail", pk=document.pk)

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
    except (ValueError, ValidationError) as exc:
        messages.error(request, _save_error(exc))
        return redirect("documents:detail", pk=document.pk)

    messages.success(request, "Cambios guardados correctamente.")
    return redirect("documents:detail", pk=document.pk)

def organize_document(request, document):
    if not document.can_organize:
        messages.warning(request, "El documento se está procesando; espera a que termine.")
        return redirect("documents:detail", pk=document.pk)
    try:
        DocumentService.organize(document, user=request.user, data=request.POST)
    except (ValueError, ValidationError) as exc:
        messages.error(request, _save_error(exc))
        return redirect("documents:detail", pk=document.pk)
    messages.success(request, "Organización guardada.")
    return redirect("documents:detail", pk=document.pk)

def archive_document(request, document): 
    DocumentService.archive(document, user=request.user)
    messages.success(request, "Documento archivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

def unarchive_document(request, document):
    DocumentService.unarchive(document, user=request.user)
    messages.warning(request, "Documento desarchivado correctamente.")
    return redirect("documents:detail", pk=document.pk)

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "private/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(DashboardService.build(self.request.user))
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

        # Presentación: héroe, desglose por origen, IVA, embudo, automatización, gráficos
        start, end = metrics["period"]["start"], metrics["period"]["end"]
        previous = None
        if isinstance(start, date) and isinstance(end, date):
            p_start, p_end = previous_period(start, end)
            previous = MetricsService.get_user_metrics(user=self.request.user, start=p_start, end=p_end)
        page = build_page(metrics, historical_metrics, context["period"], previous)
        if isinstance(start, date) and isinstance(end, date):
            page["presets"] = presets(timezone.now().date(), start, end)
        context.update(page)

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
        client = self.request.user.client
        context["processing_count"] = DocumentSelector.processing_count(client)
        context["recent_documents"] = DocumentSelector.for_client(client).order_by("-created_at", "-pk")[:5]
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


class DocumentDriveView(LoginRequiredMixin, TemplateView):
    """Vista «Archivo»: documentos en carpetas virtuales derivadas de sus datos (ver drive_selector)."""

    template_name = "private/documents/document_drive.html"
    paginate_by = 20

    def get_context_data(self, ruta="", **kwargs):
        context = super().get_context_data(**kwargs)
        request, client = self.request, self.request.user.client
        try:
            path = drive.DrivePath.parse(ruta)
            company = drive.DriveSelector.company(client, path)
            current_folder = drive.DriveSelector.folder(client, path)
        except drive.InvalidDrivePath:
            raise Http404("Carpeta inexistente")
        filters = drive.parse_filters(request.GET)

        page_obj = None
        if path.shows_documents:
            page_obj = Paginator(drive.DriveSelector.documents(client, path, filters), self.paginate_by).get_page(
                request.GET.get("page")
            )
            if path.unclassified:
                for doc in page_obj:
                    doc.drive_reason = drive.unclassified_reason(doc)

        folders = folder_service.with_labels(client)
        tags = Tag.objects.filter(client=client)
        active_filters = listing.active_filters(request, [
            ("status", "Estado", {"pending": "Pendientes", "approved": "Aprobados", "rejected": "Rechazados"}, False),
            ("folder", "Carpeta", {str(f.pk): f.label for f in folders}, True),
            ("tag", "Etiqueta", {str(t.pk): t.name for t in tags}, True),
        ])
        context.update(
            path=path,
            company=company,
            current_folder=current_folder,
            breadcrumbs=drive.breadcrumbs(path, company, current_folder),
            folders_here=drive.DriveSelector.children(client, path, filters),
            documents=page_obj,
            page_obj=page_obj,
            page_numbers=listing.page_window(page_obj) if page_obj and page_obj.paginator.num_pages > 1 else [],
            is_paginated=bool(page_obj and page_obj.paginator.num_pages > 1),
            folders=folders,
            tags=tags,
            status_tabs=listing.status_tabs(request, [
                ("", "Todos"), ("pending", "Pendientes"), ("approved", "Aprobados"), ("rejected", "Rechazados"),
            ]),
            active_filters=active_filters,
            querystring=listing.qs_without(request),
        )
        return context


class DriveFolderActionView(LoginRequiredMixin, View):
    """Crear, renombrar y eliminar carpetas manuales («Mis carpetas»). Siempre redirige al Archivo."""

    def post(self, request):
        client = request.user.client
        action = request.POST.get("action")
        target = None  # carpeta manual a la que volver (None = raíz de «Mis carpetas»)
        try:
            if action == "create":
                parent = self._folder(request, "parent") if request.POST.get("parent") else None
                target = parent
                created = folder_service.create_folder(client, request.POST.get("name"), parent)
                messages.success(request, f"Carpeta «{created.name}» creada.")
            elif action == "rename":
                folder = self._folder(request, "folder")
                target = folder.parent
                folder_service.rename_folder(folder, request.POST.get("name"))
                messages.success(request, "Carpeta renombrada.")
            elif action == "delete":
                folder = self._folder(request, "folder")
                target = folder.parent
                count = folder_service.delete_folder(folder)
                messages.success(
                    request,
                    "Carpeta eliminada." + (f" {count} documento(s) han quedado sin carpeta." if count else ""),
                )
            else:
                messages.warning(request, "Acción no reconocida.")
        except folder_service.FolderError as exc:
            messages.error(request, str(exc))
        return redirect("documents:drive", ruta=drive.manual_ruta(target.pk if target else None))

    def _folder(self, request, field):
        folder = folder_service.get_folder(request.user.client, request.POST.get(field))
        if folder is None:
            raise Http404("Carpeta inexistente")
        return folder
