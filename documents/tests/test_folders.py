"""Carpetas manuales anidadas («Mis carpetas» del Archivo)."""
import pytest
from django.contrib.messages import get_messages
from django.db import IntegrityError, transaction
from django.urls import reverse

from documents.models import Document, Folder
from documents.selectors import drive_selector as drive
from documents.selectors.drive_selector import DrivePath, DriveSelector, InvalidDrivePath
from documents.services import folders as svc
from documents.tests import factories as f

pytestmark = pytest.mark.django_db

ACTION = "documents:drive_folder"


def texts(response):
    return [m.message for m in get_messages(response.wsgi_request)]


class TestService:
    def test_create_nested_and_labels(self, client_entity):
        a = svc.create_folder(client_entity, "Inmuebles")
        b = svc.create_folder(client_entity, "  Calle   X ", a)
        assert b.name == "Calle X" and b.parent == a
        assert [x.label for x in svc.with_labels(client_entity)] == ["Inmuebles", "Inmuebles / Calle X"]
        assert svc.ancestors(b) == [a, b]

    def test_name_required_and_unique_among_siblings_only(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        with pytest.raises(svc.FolderError):
            svc.create_folder(client_entity, "   ")
        with pytest.raises(svc.FolderError, match="Ya existe"):
            svc.create_folder(client_entity, "a")  # sin distinguir mayúsculas
        svc.create_folder(client_entity, "X", a)
        with pytest.raises(svc.FolderError, match="Ya existe"):
            svc.create_folder(client_entity, "x", a)
        # el mismo nombre en otra rama sí vale
        other = svc.create_folder(client_entity, "B")
        assert svc.create_folder(client_entity, "X", other).name == "X"

    def test_db_constraints_back_up_uniqueness(self, client_entity):
        a = Folder.objects.create(client=client_entity, name="A")
        with pytest.raises(IntegrityError), transaction.atomic():
            Folder.objects.create(client=client_entity, name="A")
        Folder.objects.create(client=client_entity, name="S", parent=a)
        with pytest.raises(IntegrityError), transaction.atomic():
            Folder.objects.create(client=client_entity, name="S", parent=a)

    def test_depth_limit(self, client_entity):
        folder = None
        for i in range(svc.MAX_DEPTH):
            folder = svc.create_folder(client_entity, f"n{i}", folder)
        with pytest.raises(svc.FolderError, match="niveles"):
            svc.create_folder(client_entity, "demasiado", folder)

    def test_parent_of_another_client_is_rejected(self, client_entity, other_client_entity):
        foreign = Folder.objects.create(client=other_client_entity, name="Ajena")
        with pytest.raises(svc.FolderError):
            svc.create_folder(client_entity, "X", foreign)
        assert svc.get_folder(client_entity, foreign.pk) is None
        assert svc.get_folder(client_entity, "abc") is None

    def test_rename(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        svc.create_folder(client_entity, "B")
        assert svc.rename_folder(a, "Nueva").name == "Nueva"
        with pytest.raises(svc.FolderError, match="Ya existe"):
            svc.rename_folder(a, "b")
        assert svc.rename_folder(a, "NUEVA").name == "NUEVA"  # su propio nombre no choca consigo misma

    def test_delete_blocked_with_subfolders_and_keeps_documents_otherwise(self, client_entity):
        parent = svc.create_folder(client_entity, "P")
        child = svc.create_folder(client_entity, "C", parent)
        with pytest.raises(svc.FolderError, match="subcarpetas"):
            svc.delete_folder(parent)
        doc = f.DocumentFactory(client=client_entity, folder=child)
        archived = f.DocumentFactory(client=client_entity, folder=child)
        Document.all_objects.filter(pk=archived.pk).update(is_archived=True)
        assert svc.delete_folder(child) == 2
        doc.refresh_from_db()
        assert doc.folder is None and Document.all_objects.get(pk=archived.pk).folder is None
        svc.delete_folder(parent)
        assert not Folder.objects.exists()

    def test_detail_new_folder_goes_to_root_even_if_nested_name_exists(self, auth_client, client_entity):
        from documents.services import organization
        nested = svc.create_folder(client_entity, "Gastos", svc.create_folder(client_entity, "Raíz"))
        doc = f.DocumentFactory(client=client_entity, status="pending")
        organization.apply_organization(doc, {"new_folder": "gastos"})
        assert doc.folder != nested and doc.folder.parent is None


class TestDrivePathManual:
    def test_parse_and_ruta(self):
        assert DrivePath.parse("mis-carpetas/").level == "manual"
        assert DrivePath.parse("mis-carpetas/7/").level == "folder"
        for raw in ("mis-carpetas/", "mis-carpetas/7/"):
            assert DrivePath.parse(raw).ruta == raw
        assert DrivePath.parse("mis-carpetas/7/").shows_documents
        assert not DrivePath.parse("mis-carpetas/").shows_documents

    @pytest.mark.parametrize("raw", ["mis-carpetas/abc/", "mis-carpetas/1/2/", "mis-carpetas/-1/"])
    def test_invalid(self, raw):
        with pytest.raises(InvalidDrivePath):
            DrivePath.parse(raw)


class TestSelector:
    def test_root_has_my_folders_entry_with_count(self, client_entity):
        folder = svc.create_folder(client_entity, "A")
        f.DocumentFactory(client=client_entity, folder=folder)
        f.DocumentFactory(client=client_entity)
        mine = [fo for fo in DriveSelector.children(client_entity, DrivePath.parse("")) if fo.name == "Mis carpetas"][0]
        assert (mine.ruta, mine.count, mine.total) == ("mis-carpetas/", 1, None)

    def test_children_counts_and_subfolders(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        b = svc.create_folder(client_entity, "B")
        svc.create_folder(client_entity, "A1", a)
        f.DocumentFactory(client=client_entity, folder=a)
        f.DocumentFactory(client=client_entity, folder=a, status="pending")
        root = DriveSelector.children(client_entity, DrivePath.parse("mis-carpetas/"))
        assert [(x.name, x.count, x.subfolders, x.folder_id) for x in root] == [("A", 2, 1, a.pk), ("B", 0, 0, b.pk)]
        inner = DriveSelector.children(client_entity, DrivePath.parse(f"mis-carpetas/{a.pk}/"))
        assert [x.name for x in inner] == ["A1"]

    def test_documents_are_direct_only_and_include_unclassified(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        sub = svc.create_folder(client_entity, "Sub", a)
        direct = f.DocumentFactory(client=client_entity, folder=a)
        loose = f.DocumentFactory(client=client_entity, folder=a, issue_date=None)  # sin clasificar en el árbol derivado
        f.DocumentFactory(client=client_entity, folder=sub)
        ids = set(DriveSelector.documents(client_entity, DrivePath.parse(f"mis-carpetas/{a.pk}/")).values_list("pk", flat=True))
        assert ids == {direct.pk, loose.pk}
        assert not DriveSelector.documents(client_entity, DrivePath.parse("mis-carpetas/")).exists()

    def test_archived_hidden_and_filters_apply(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        keep = f.DocumentFactory(client=client_entity, folder=a, status="approved")
        f.DocumentFactory(client=client_entity, folder=a, status="pending")
        gone = f.DocumentFactory(client=client_entity, folder=a)
        Document.all_objects.filter(pk=gone.pk).update(is_archived=True)
        path = DrivePath.parse(f"mis-carpetas/{a.pk}/")
        assert DriveSelector.documents(client_entity, path).count() == 2
        assert list(DriveSelector.documents(client_entity, path, {"status": "approved"})) == [keep]

    def test_foreign_folder_is_invalid_and_not_listed(self, client_entity, other_client_entity):
        foreign = Folder.objects.create(client=other_client_entity, name="Ajena")
        f.DocumentFactory(client=other_client_entity, folder=foreign)
        with pytest.raises(InvalidDrivePath):
            DriveSelector.folder(client_entity, DrivePath.parse(f"mis-carpetas/{foreign.pk}/"))
        assert DriveSelector.children(client_entity, DrivePath.parse("mis-carpetas/")) == []

    def test_breadcrumbs(self, client_entity):
        a = svc.create_folder(client_entity, "A")
        b = svc.create_folder(client_entity, "B", a)
        crumbs = drive.breadcrumbs(DrivePath.parse(f"mis-carpetas/{b.pk}/"), None, b)
        assert crumbs == [("Archivo", ""), ("Mis carpetas", "mis-carpetas/"), ("A", f"mis-carpetas/{a.pk}/"),
                          ("B", f"mis-carpetas/{b.pk}/")]


class TestViews:
    def drive_url(self, ruta):
        return reverse("documents:drive", kwargs={"ruta": ruta})

    def test_manual_pages_render(self, auth_client, client_entity):
        a = svc.create_folder(client_entity, "Inmuebles")
        svc.create_folder(client_entity, "Calle X", a)
        f.DocumentFactory(client=client_entity, folder=a, original_name="en-carpeta.pdf")
        assert "Inmuebles" in auth_client.get(self.drive_url("mis-carpetas/")).content.decode()
        body = auth_client.get(self.drive_url(f"mis-carpetas/{a.pk}/")).content.decode()
        assert "Calle X" in body and "en-carpeta.pdf" in body

    def test_foreign_or_unknown_folder_is_404(self, auth_client, other_client_entity):
        foreign = Folder.objects.create(client=other_client_entity, name="Ajena")
        assert auth_client.get(self.drive_url(f"mis-carpetas/{foreign.pk}/")).status_code == 404
        assert auth_client.get(self.drive_url("mis-carpetas/99999/")).status_code == 404

    def test_create_rename_delete_flow(self, auth_client, client_entity):
        r = auth_client.post(reverse(ACTION), {"action": "create", "name": "Pendiente gestoría"}, follow=True)
        folder = Folder.objects.get(name="Pendiente gestoría")
        assert folder.parent is None and r.redirect_chain[-1][0] == self.drive_url("mis-carpetas/")

        r = auth_client.post(reverse(ACTION), {"action": "create", "name": "2026", "parent": folder.pk})
        child = Folder.objects.get(name="2026")
        assert child.parent == folder and r.url == self.drive_url(f"mis-carpetas/{folder.pk}/")

        auth_client.post(reverse(ACTION), {"action": "rename", "folder": child.pk, "name": "Año 2026"})
        child.refresh_from_db()
        assert child.name == "Año 2026"

        r = auth_client.post(reverse(ACTION), {"action": "delete", "folder": folder.pk}, follow=True)
        assert Folder.objects.filter(pk=folder.pk).exists()
        assert any("subcarpetas" in t for t in texts(r))

        auth_client.post(reverse(ACTION), {"action": "delete", "folder": child.pk})
        auth_client.post(reverse(ACTION), {"action": "delete", "folder": folder.pk})
        assert not Folder.objects.exists()

    def test_errors_are_messages_not_500(self, auth_client, client_entity):
        svc.create_folder(client_entity, "A")
        r = auth_client.post(reverse(ACTION), {"action": "create", "name": "a"}, follow=True)
        assert r.status_code == 200 and any("Ya existe" in t for t in texts(r))
        r = auth_client.post(reverse(ACTION), {"action": "create", "name": ""}, follow=True)
        assert any("nombre" in t for t in texts(r))
        r = auth_client.post(reverse(ACTION), {"action": "nada"}, follow=True)
        assert r.status_code == 200

    def test_tenant_isolation_on_actions(self, auth_client, client_entity, other_client_entity):
        foreign = Folder.objects.create(client=other_client_entity, name="Ajena")
        for data in ({"action": "rename", "folder": foreign.pk, "name": "Hack"},
                     {"action": "delete", "folder": foreign.pk},
                     {"action": "create", "name": "X", "parent": foreign.pk}):
            assert auth_client.post(reverse(ACTION), data).status_code == 404
        foreign.refresh_from_db()
        assert foreign.name == "Ajena" and not Folder.objects.filter(client=client_entity).exists()

    def test_actions_require_login_and_post(self, client, auth_client):
        assert client.post(reverse(ACTION), {"action": "create", "name": "X"}).status_code == 302
        assert auth_client.get(reverse(ACTION)).status_code == 405

    def test_detail_select_shows_full_path_labels(self, auth_client, client_entity):
        a = svc.create_folder(client_entity, "Inmuebles")
        svc.create_folder(client_entity, "Calle X", a)
        doc = f.DocumentFactory(client=client_entity, status="pending")
        body = auth_client.get(reverse("documents:detail", kwargs={"pk": doc.pk})).content.decode()
        assert "Inmuebles / Calle X" in body
        assert 'name="category"' not in body
