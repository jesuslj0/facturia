"""Carpetas manuales anidadas («Mis carpetas» del Archivo). Todo se resuelve contra el cliente.

La carpeta padre se fija al crear y no se cambia, así que no puede haber ciclos.
"""
from django.db import transaction

from documents.models import Document, Folder

MAX_DEPTH = 5  # niveles máximos de anidación (la carpeta raíz es el nivel 1)
MAX_NAME = 100
SEPARATOR = " / "


class FolderError(ValueError):
    """Operación de carpeta no válida; el mensaje se muestra al usuario."""


def clean_name(raw) -> str:
    name = " ".join((raw or "").split())[:MAX_NAME]
    if not name:
        raise FolderError("Escribe un nombre para la carpeta.")
    return name


def get_folder(client, pk):
    """Carpeta del cliente o None (también si el id no es válido o es de otro cliente)."""
    try:
        return Folder.objects.filter(client=client, pk=int(pk)).first()
    except (TypeError, ValueError):
        return None


def ancestors(folder) -> list:
    """Cadena de carpetas desde la raíz hasta `folder` (incluida)."""
    chain, seen = [], set()
    while folder is not None and folder.pk not in seen:
        seen.add(folder.pk)
        chain.append(folder)
        folder = folder.parent
    return chain[::-1]


def depth(folder) -> int:
    return len(ancestors(folder))


def with_labels(client) -> list:
    """Todas las carpetas del cliente con `.label` = ruta completa («Inmuebles / Calle X»), ordenadas por ella."""
    folders = list(Folder.objects.filter(client=client))
    by_id = {f.pk: f for f in folders}

    def label(folder):
        names, seen = [], set()
        while folder is not None and folder.pk not in seen:
            seen.add(folder.pk)
            names.append(folder.name)
            folder = by_id.get(folder.parent_id)
        return SEPARATOR.join(reversed(names))

    for f in folders:
        f.label = label(f)
    return sorted(folders, key=lambda f: f.label.lower())


def _sibling_exists(client, parent, name, exclude_pk=None) -> bool:
    qs = Folder.objects.filter(client=client, parent=parent, name__iexact=name)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


@transaction.atomic
def create_folder(client, name, parent=None) -> Folder:
    name = clean_name(name)
    if parent is not None:
        if parent.client_id != client.pk:
            raise FolderError("La carpeta padre no existe.")
        if depth(parent) >= MAX_DEPTH:
            raise FolderError(f"No se pueden anidar más de {MAX_DEPTH} niveles de carpetas.")
    if _sibling_exists(client, parent, name):
        raise FolderError("Ya existe una carpeta con ese nombre aquí.")
    return Folder.objects.create(client=client, parent=parent, name=name)


@transaction.atomic
def rename_folder(folder, name) -> Folder:
    name = clean_name(name)
    if _sibling_exists(folder.client, folder.parent, name, exclude_pk=folder.pk):
        raise FolderError("Ya existe una carpeta con ese nombre aquí.")
    folder.name = name
    folder.save(update_fields=["name"])
    return folder


@transaction.atomic
def delete_folder(folder) -> int:
    """Borra una carpeta sin subcarpetas; sus documentos quedan sin carpeta. Devuelve cuántos eran."""
    if folder.children.exists():
        raise FolderError("La carpeta tiene subcarpetas: elimínalas o vacíalas antes.")
    count = Document.all_objects.filter(folder=folder).count()  # incluye archivados
    folder.delete()  # Document.folder es SET_NULL
    return count
