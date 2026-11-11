"""Clasificación y archivo de documentos: tipo, empresa, categoría, carpeta y etiquetas (H6).

Todo se resuelve contra el cliente del documento: un id de otro tenant se ignora.
"""
from documents.models import Company, DocumentCategory, Folder, Tag

MAX_TAGS = 20


def parse_tag_names(raw: str) -> list[str]:
    """«a, b,, A» -> ['a', 'b'] (sin vacíos ni duplicados, sin distinguir mayúsculas)."""
    seen, out = set(), []
    for part in (raw or "").split(","):
        name = " ".join(part.split())[:50]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out[:MAX_TAGS]


def apply_organization(document, data) -> None:
    """Aplica al documento (sin guardar) los campos de organización presentes en `data`."""
    client = document.client

    if data.get("document_type") in dict(document.TYPE_CHOICES):
        document.document_type = data["document_type"]

    if "company" in data and data.get("company"):
        company = Company.objects.filter(client=client, pk=_int(data["company"])).first()
        if company is not None:
            document.company = company

    if "category" in data:
        document.category = DocumentCategory.objects.filter(
            client=client, pk=_int(data.get("category"))
        ).first()

    if "folder" in data or data.get("new_folder"):
        folder = None
        new_name = " ".join((data.get("new_folder") or "").split())[:100]
        if new_name:
            folder = Folder.objects.filter(client=client, name__iexact=new_name).first() \
                or Folder.objects.create(client=client, name=new_name)
        elif data.get("folder"):
            folder = Folder.objects.filter(client=client, pk=_int(data["folder"])).first()
        document.folder = folder


def set_tags(document, raw: str) -> None:
    """Sustituye las etiquetas del documento (crea las que no existan). Requiere pk."""
    tags = []
    for name in parse_tag_names(raw):
        tag = Tag.objects.filter(client=document.client, name__iexact=name).first() \
            or Tag.objects.create(client=document.client, name=name)
        tags.append(tag)
    document.tags.set(tags)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
