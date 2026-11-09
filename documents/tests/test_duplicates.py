import pytest

from documents.services.duplicates import find_duplicate_by_hash, find_duplicate_by_number
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


def test_find_by_hash_same_tenant_only():
    d = f.DocumentFactory()
    f.DocumentFileFactory(document=d, sha256="a" * 64)
    assert find_duplicate_by_hash(d.client, "a" * 64) == d
    assert find_duplicate_by_hash(f.ClientFactory(), "a" * 64) is None
    assert find_duplicate_by_hash(d.client, "b" * 64) is None


def test_find_by_number_requires_number_and_issuer():
    c = f.ClientFactory()
    co = f.CompanyFactory(client=c, tax_id="B12345674")
    d = f.DocumentFactory(client=c, company=co, document_number="X-1", flow="out")
    kw = dict(flow="out", issuer_tax_id="B12345674")
    assert find_duplicate_by_number(c, document_number="x-1", **kw) == d          # sin distinguir mayúsculas
    assert find_duplicate_by_number(c, document_number="  X-1 ", **kw) == d
    assert find_duplicate_by_number(c, document_number=None, **kw) is None
    assert find_duplicate_by_number(c, flow="out", issuer_tax_id=None, document_number="X-1") is None
    assert find_duplicate_by_number(c, document_number="X-1", flow="out", issuer_tax_id="A82018474") is None
    assert find_duplicate_by_number(c, document_number="X-1", exclude_pk=d.pk, **kw) is None


def test_old_rectified_versions_are_not_duplicates():
    c = f.ClientFactory()
    co = f.CompanyFactory(client=c, tax_id="B12345674")
    f.DocumentFactory(client=c, company=co, document_number="X-1", flow="out", is_current=False)
    assert find_duplicate_by_number(c, flow="out", issuer_tax_id="B12345674", document_number="X-1") is None
