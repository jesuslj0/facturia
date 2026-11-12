"""Vista «Archivo» (estilo Drive): árbol de carpetas **virtual**, calculado a partir de los datos.

No se guarda ninguna carpeta: la ruta de un documento sale de su flujo, su fecha de emisión, su
tercero y su tipo. Un documento al que le falte algún dato (o que aún no se haya procesado) va a
«Sin clasificar» en lugar de desaparecer.

    Compras | Ventas  →  año  →  trimestre  →  empresa  →  grupo de tipo (Facturas, Albaranes…)

No confundir con `Folder` (agrupación **manual**): aquí «carpeta» es derivada. `Folder`,
categoría y etiqueta son filtros transversales, no forman parte de la ruta.
"""
import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, ExtractQuarter, ExtractYear

from documents.models import Company, Document, Folder
from documents.services import folders as folder_service
from documents.services.signs import signed_amount

from .document_selector import DocumentSelector, quarter_range

# Primer nivel. ATENCIÓN: en el modelo `flow="in"` es Ingreso (venta) y `flow="out"` es Gasto (compra).
FLOW_FOLDERS = {
    "compras": ("Compras", "out"),
    "ventas": ("Ventas", "in"),
}
FLOW_BY_CODE = {code: slug for slug, (_, code) in FLOW_FOLDERS.items()}

UNCLASSIFIED_SLUG = "sin-clasificar"
UNCLASSIFIED_LABEL = "Sin clasificar"

# «Mis carpetas»: árbol de carpetas manuales (`Folder`), aparte del árbol derivado.
MANUAL_SLUG = "mis-carpetas"
MANUAL_LABEL = "Mis carpetas"

# Única fuente de verdad de la agrupación de tipos: slug de la URL -> (etiqueta, tipos de Document.TYPE_CHOICES).
TYPE_GROUPS = {
    "facturas": ("Facturas", ["invoice"]),
    "albaranes": ("Albaranes", ["delivery"]),
    "abonos": ("Abonos", ["corrected_invoice", "delivery_credit_note"]),
    "tickets": ("Tickets", ["receipt"]),
    "presupuestos": ("Presupuestos", ["quote"]),
}
# Red de seguridad: un tipo nuevo que no esté en TYPE_GROUPS cae aquí y no desaparece del Drive.
OTHERS_SLUG = "otros"
OTHERS_LABEL = "Otros"
GROUP_LABELS = {slug: label for slug, (label, _) in TYPE_GROUPS.items()} | {OTHERS_SLUG: OTHERS_LABEL}
KNOWN_TYPES = [t for _, types in TYPE_GROUPS.values() for t in types]

# Filtros transversales admitidos en cualquier nivel (mismos nombres de parámetro que el listado).
DRIVE_FILTERS = ("status", "folder", "tag")

# Un documento solo entra en el árbol si tiene todos los datos de la ruta y ya está procesado.
CLASSIFIED = Q(
    issue_date__isnull=False,
    company__isnull=False,
    flow__in=[code for _, code in FLOW_FOLDERS.values()],
    processing_status="processed",
)

_ASCII_YEAR = re.compile(r"[0-9]{4}", re.ASCII)
_ASCII_QUARTER = re.compile(r"T([1-4])", re.ASCII)
_ASCII_ID = re.compile(r"[0-9]{1,9}", re.ASCII)


class InvalidDrivePath(ValueError):
    """La ruta de la URL no existe en el árbol (la vista la convierte en 404)."""


def group_of(document_type) -> str:
    """Slug del grupo de tipo al que pertenece un tipo de documento."""
    for slug, (_, types) in TYPE_GROUPS.items():
        if document_type in types:
            return slug
    return OTHERS_SLUG


def _group_q(slug) -> Q:
    if slug == OTHERS_SLUG:
        return ~Q(document_type__in=KNOWN_TYPES)
    return Q(document_type__in=TYPE_GROUPS[slug][1])


@dataclass(frozen=True)
class DrivePath:
    """Posición en el árbol. Se construye con `parse()`, que valida cada tramo."""

    flow: str | None = None  # slug: "compras" | "ventas"
    year: int | None = None
    quarter: int | None = None
    company_id: int | None = None
    group: str | None = None
    unclassified: bool = False
    manual: bool = False  # dentro de «Mis carpetas»
    folder_id: int | None = None  # carpeta manual abierta (None = raíz de «Mis carpetas»)

    @classmethod
    def parse(cls, raw: str | None) -> "DrivePath":
        stripped = (raw or "").strip("/")
        if not stripped:
            return cls()
        parts = stripped.split("/")
        if parts == [UNCLASSIFIED_SLUG]:
            return cls(unclassified=True)
        if parts[0] == MANUAL_SLUG:
            if len(parts) == 1:
                return cls(manual=True)
            if len(parts) == 2 and _ASCII_ID.fullmatch(parts[1]):
                return cls(manual=True, folder_id=int(parts[1]))
            raise InvalidDrivePath(raw)
        if len(parts) > 5 or parts[0] not in FLOW_FOLDERS:
            raise InvalidDrivePath(raw)
        values = {"flow": parts[0]}
        if len(parts) > 1:
            if not _ASCII_YEAR.fullmatch(parts[1]) or int(parts[1]) < 1:
                raise InvalidDrivePath(raw)
            values["year"] = int(parts[1])
        if len(parts) > 2:
            match = _ASCII_QUARTER.fullmatch(parts[2])
            if not match:
                raise InvalidDrivePath(raw)
            values["quarter"] = int(match.group(1))
        if len(parts) > 3:
            if not _ASCII_ID.fullmatch(parts[3]):
                raise InvalidDrivePath(raw)
            values["company_id"] = int(parts[3])
        if len(parts) > 4:
            if parts[4] not in GROUP_LABELS:
                raise InvalidDrivePath(raw)
            values["group"] = parts[4]
        return cls(**values)

    @property
    def level(self) -> str:
        if self.unclassified:
            return "unclassified"
        if self.manual:
            return "folder" if self.folder_id is not None else "manual"
        if self.group:
            return "group"
        if self.company_id is not None:
            return "company"
        if self.quarter:
            return "quarter"
        if self.year:
            return "year"
        if self.flow:
            return "flow"
        return "root"

    @property
    def is_leaf(self) -> bool:
        """Carpeta sin hijas derivadas: solo documentos."""
        return self.level in ("group", "unclassified")

    @property
    def shows_documents(self) -> bool:
        """Niveles que listan documentos (las carpetas manuales abiertas también muestran subcarpetas)."""
        return self.level in ("group", "unclassified", "folder")

    @property
    def flow_code(self) -> str | None:
        return FLOW_FOLDERS[self.flow][1] if self.flow else None

    @property
    def ruta(self) -> str:
        """Tramo de URL con barra final ('' en la raíz)."""
        if self.unclassified:
            return f"{UNCLASSIFIED_SLUG}/"
        if self.manual:
            return f"{MANUAL_SLUG}/" + (f"{self.folder_id}/" if self.folder_id is not None else "")
        parts = [self.flow, self.year, f"T{self.quarter}" if self.quarter else None, self.company_id, self.group]
        return "".join(f"{p}/" for p in parts if p is not None)

    def date_range(self):
        """(inicio, fin) del año o trimestre de la ruta; (None, None) si aún no hay año."""
        if self.quarter:
            return quarter_range(f"{self.year}-T{self.quarter}")
        if self.year:
            return date(self.year, 1, 1), date(self.year, 12, 31)
        return None, None


@dataclass(frozen=True)
class DriveFolder:
    name: str
    ruta: str  # ruta completa de la carpeta (para `{% url 'documents:drive' ruta=… %}`)
    count: int
    total: Decimal | None  # None en «Sin clasificar»: sin fecha o flujo el importe no es fiable
    pending_count: int
    icon: str = "folder"
    folder_id: int | None = None  # solo carpetas manuales (para renombrar/eliminar)
    subfolders: int = 0  # nº de subcarpetas (solo manuales)


def parse_filters(params) -> dict:
    """Filtros transversales a partir de `request.GET` (solo los permitidos)."""
    return {key: params[key] for key in DRIVE_FILTERS if params.get(key)}


def unclassified_reason(document) -> str:
    """Motivo (legible) por el que un documento está en «Sin clasificar»."""
    if document.is_processing:
        return "Procesando"
    if document.processing_status == "failed":
        return "Error de extracción"
    reasons = []
    if document.flow not in FLOW_BY_CODE:
        reasons.append("Flujo por revisar")
    if document.issue_date is None:
        reasons.append("Sin fecha")
    if document.company_id is None:
        reasons.append("Sin tercero")
    return ", ".join(reasons)


def manual_ruta(folder_id=None) -> str:
    return DrivePath(manual=True, folder_id=folder_id).ruta


def breadcrumbs(path: DrivePath, company: Company | None = None, folder: Folder | None = None) -> list[tuple[str, str]]:
    """[(etiqueta, ruta)] desde la raíz hasta la carpeta actual."""
    crumbs = [("Archivo", "")]
    if path.manual:
        crumbs.append((MANUAL_LABEL, manual_ruta()))
        crumbs += [(f.name, manual_ruta(f.pk)) for f in folder_service.ancestors(folder)]
        return crumbs
    if path.unclassified:
        return crumbs + [(UNCLASSIFIED_LABEL, path.ruta)]
    if path.flow:
        crumbs.append((FLOW_FOLDERS[path.flow][0], DrivePath(flow=path.flow).ruta))
    if path.year:
        crumbs.append((str(path.year), DrivePath(path.flow, path.year).ruta))
    if path.quarter:
        crumbs.append((f"T{path.quarter}", DrivePath(path.flow, path.year, path.quarter).ruta))
    if path.company_id is not None:
        name = company.name if company else str(path.company_id)
        crumbs.append((name, DrivePath(path.flow, path.year, path.quarter, path.company_id).ruta))
    if path.group:
        crumbs.append((GROUP_LABELS[path.group], path.ruta))
    return crumbs


def _stats() -> dict:
    zero = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))
    return {
        "n": Count("pk"),
        # Una rectificativa resta siempre (services/signs.py).
        "amount": Coalesce(Sum(signed_amount("total_amount")), zero),
        "pending": Count("pk", filter=Q(status="pending")),
    }


def _folder(name, ruta, row, icon="folder", total=True) -> DriveFolder:
    return DriveFolder(
        name=name, ruta=ruta, count=row["n"], total=row["amount"] if total else None,
        pending_count=row["pending"], icon=icon,
    )


_EMPTY = {"n": 0, "amount": Decimal("0.00"), "pending": 0}


class DriveSelector:
    @staticmethod
    def scope(client, filters: dict | None = None):
        """Documentos visibles en el Drive: del cliente, vigentes, sin archivar y con los filtros aplicados."""
        return DocumentSelector.filtered(client, filters or {}, base_qs=DocumentSelector.for_client(client))

    @staticmethod
    def company(client, path: DrivePath) -> Company | None:
        """Tercero de la ruta. Si no es de este cliente lanza `InvalidDrivePath` (404, no carpeta vacía)."""
        if path.company_id is None:
            return None
        company = Company.objects.filter(client=client, pk=path.company_id).first()
        if company is None:
            raise InvalidDrivePath(path.ruta)
        return company

    @staticmethod
    def folder(client, path: DrivePath) -> Folder | None:
        """Carpeta manual de la ruta. Si no es de este cliente lanza `InvalidDrivePath` (404)."""
        if path.folder_id is None:
            return None
        found = folder_service.get_folder(client, path.folder_id)
        if found is None:
            raise InvalidDrivePath(path.ruta)
        return found

    @staticmethod
    def _manual_children(client, path: DrivePath, filters) -> list[DriveFolder]:
        folders = list(Folder.objects.filter(client=client, parent_id=path.folder_id))
        rows = {
            r["folder_id"]: r
            for r in DriveSelector.scope(client, filters).filter(folder__in=folders)
            .order_by().values("folder_id").annotate(**_stats())
        }
        subs = dict(
            Folder.objects.filter(client=client, parent__in=folders).order_by()
            .values_list("parent_id").annotate(n=Count("pk"))
        )
        return [
            DriveFolder(
                name=f.name, ruta=manual_ruta(f.pk), count=rows.get(f.pk, _EMPTY)["n"], total=None,
                pending_count=rows.get(f.pk, _EMPTY)["pending"], folder_id=f.pk, subfolders=subs.get(f.pk, 0),
            )
            for f in sorted(folders, key=lambda f: f.name.lower())
        ]

    @staticmethod
    def children(client, path: DrivePath, filters: dict | None = None) -> list[DriveFolder]:
        """Carpetas hijas del nivel actual: una sola consulta agrupada por nivel (sin N+1)."""
        qs = DriveSelector.scope(client, filters)
        level = path.level
        if level in ("group", "unclassified"):
            return []
        if level in ("manual", "folder"):
            return DriveSelector._manual_children(client, path, filters)

        if level == "root":
            rows = {
                r["flow"]: r
                for r in qs.filter(CLASSIFIED).order_by().values("flow").annotate(**_stats())
            }
            folders = [
                _folder(label, f"{slug}/", rows.get(code, _EMPTY))
                for slug, (label, code) in FLOW_FOLDERS.items()
            ]
            manual = qs.filter(folder__isnull=False).order_by().aggregate(**_stats())
            folders.append(_folder(MANUAL_LABEL, manual_ruta(), manual, total=False))
            loose = qs.exclude(CLASSIFIED).order_by().aggregate(**_stats())
            if loose["n"]:
                folders.append(_folder(UNCLASSIFIED_LABEL, f"{UNCLASSIFIED_SLUG}/", loose, icon="warning", total=False))
            return folders

        classified = qs.filter(CLASSIFIED, flow=path.flow_code)
        if level == "flow":
            rows = classified.order_by().annotate(y=ExtractYear("issue_date")).values("y").annotate(**_stats())
            return [
                _folder(str(r["y"]), DrivePath(path.flow, r["y"]).ruta, r)
                for r in sorted(rows, key=lambda r: r["y"], reverse=True)
            ]

        start, end = path.date_range()
        classified = classified.filter(issue_date__gte=start, issue_date__lte=end)
        if level == "year":
            rows = classified.order_by().annotate(q=ExtractQuarter("issue_date")).values("q").annotate(**_stats())
            return [
                _folder(f"T{r['q']}", DrivePath(path.flow, path.year, r["q"]).ruta, r)
                for r in sorted(rows, key=lambda r: r["q"], reverse=True)
            ]

        if level == "quarter":
            rows = classified.order_by().values("company_id", "company__name").annotate(**_stats())
            return [
                _folder(
                    r["company__name"], DrivePath(path.flow, path.year, path.quarter, r["company_id"]).ruta, r,
                )
                for r in sorted(rows, key=lambda r: (r["company__name"].lower(), r["company_id"]))
            ]

        # level == "company": agrupar los tipos en sus grupos (y los desconocidos en «Otros»)
        rows = classified.filter(company_id=path.company_id).order_by().values("document_type").annotate(**_stats())
        merged: dict[str, dict] = {}
        for r in rows:
            acc = merged.setdefault(group_of(r["document_type"]), dict(_EMPTY))
            for key in _EMPTY:
                acc[key] += r[key]
        return [
            _folder(GROUP_LABELS[slug], replace(path, group=slug).ruta, merged[slug])
            for slug in GROUP_LABELS
            if slug in merged
        ]

    @staticmethod
    def documents(client, path: DrivePath, filters: dict | None = None):
        """Documentos de una carpeta hoja (grupo de tipo o «Sin clasificar»); vacío en cualquier otro nivel."""
        qs = DriveSelector.scope(client, filters).select_related("company", "folder").prefetch_related("tags")
        if path.manual:
            if path.folder_id is None:
                return qs.none()
            return qs.filter(folder_id=path.folder_id).order_by("-issue_date", "-pk")
        if path.unclassified:
            return qs.exclude(CLASSIFIED).order_by("-created_at", "-pk")
        if not path.group:
            return qs.none()
        start, end = path.date_range()
        return (
            qs.filter(CLASSIFIED, flow=path.flow_code, company_id=path.company_id,
                      issue_date__gte=start, issue_date__lte=end)
            .filter(_group_q(path.group))
            .order_by("-issue_date", "-pk")
        )
