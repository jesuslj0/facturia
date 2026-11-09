import io

import pytest
from PIL import Image
from pypdf import PdfWriter

from documents.services import preprocess as pp
from documents.services.preprocess import (
    CorruptFile, EncryptedPdf, FileTooLarge, TooManyPages, UnsupportedFileType,
    detect_mime, load_and_preprocess, preprocess, record_file_metadata,
)
from documents.tests import factories as f


def make_pdf(pages=1, password=None):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if password:
        w.encrypt(password)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def make_img(fmt="PNG", size=(120, 60), mode="RGB", color="white", exif_orientation=None, **save):
    img = Image.new(mode, size, color)
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        save["exif"] = exif
    b = io.BytesIO()
    img.save(b, format=fmt, **save)
    return b.getvalue()


def opened(data):
    return Image.open(io.BytesIO(data))


class TestDetectMime:
    @pytest.mark.parametrize("data,expected", [
        (make_pdf(), "application/pdf"), (make_img("PNG"), "image/png"),
        (make_img("JPEG"), "image/jpeg"), (make_img("WEBP"), "image/webp"),
        (make_img("GIF"), "image/gif"), (make_img("HEIF"), "image/heic"),
    ])
    def test_by_content(self, data, expected):
        assert detect_mime(data) == expected

    @pytest.mark.parametrize("data", [b"", b"MZ\x90\x00 exe", b"<html>", b"PK\x03\x04 zip"])
    def test_unknown(self, data):
        assert detect_mime(data) is None


class TestPdf:
    def test_valid_pdf_is_passed_through_unchanged(self):
        data = make_pdf(3)
        out = preprocess(data)
        assert out.content == data and out.mime_type == "application/pdf"
        assert out.page_count == 3 and not out.converted

    def test_too_many_pages_is_rejected_not_truncated(self):
        with pytest.raises(TooManyPages, match="21"):
            preprocess(make_pdf(21), max_pages=20)
        assert preprocess(make_pdf(20), max_pages=20).page_count == 20

    def test_password_protected(self):
        with pytest.raises(EncryptedPdf):
            preprocess(make_pdf(1, password="secreto"))

    def test_owner_only_encryption_with_empty_user_password_opens(self):
        w = PdfWriter()
        w.add_blank_page(width=100, height=100)
        w.encrypt(user_password="", owner_password="dueño")
        b = io.BytesIO(); w.write(b)
        assert preprocess(b.getvalue()).page_count == 1

    @pytest.mark.parametrize("data", [b"%PDF-1.4 esto no es un pdf", b"%PDF-1.4\n%%EOF", make_pdf(2)[:150]])
    def test_corrupt(self, data):
        with pytest.raises(CorruptFile):
            preprocess(data)


class TestImages:
    def test_small_clean_jpeg_and_png_pass_through(self):
        for fmt, mime in (("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")):
            data = make_img(fmt)
            out = preprocess(data)
            assert out.content == data and out.mime_type == mime and not out.converted
            assert (out.width, out.height) == (120, 60)

    def test_heic_is_converted_to_jpeg(self):
        out = preprocess(make_img("HEIF", size=(80, 40)))
        assert out.mime_type == "image/jpeg" and out.original_mime_type == "image/heic" and out.converted
        assert detect_mime(out.content) == "image/jpeg" and opened(out.content).size == (80, 40)
        assert any("HEIC" in n for n in out.notes)

    def test_exif_rotation_is_applied_and_exif_removed(self):
        # orientation 6 = girar 90° → 120x60 pasa a 60x120
        out = preprocess(make_img("JPEG", size=(120, 60), exif_orientation=6))
        img = opened(out.content)
        assert img.size == (60, 120) and not img.getexif()
        assert out.converted and (out.width, out.height) == (60, 120)

    def test_exif_without_rotation_is_stripped(self):
        out = preprocess(make_img("JPEG", exif_orientation=1))
        assert out.converted and not opened(out.content).getexif()

    def test_oversized_image_is_downscaled_keeping_ratio(self):
        out = preprocess(make_img("PNG", size=(3000, 1500)), max_side=2000)
        assert opened(out.content).size == (2000, 1000) and out.mime_type == "image/jpeg"

    def test_transparency_is_flattened_on_white(self):
        data = make_img("PNG", mode="RGBA", color=(0, 0, 0, 0), size=(10, 10))
        out = preprocess(data, max_side=5)  # fuerza reprocesado
        px = opened(out.content).convert("RGB").getpixel((1, 1))
        assert all(c > 240 for c in px)

    def test_animated_gif_uses_first_frame(self):
        frames = [Image.new("RGB", (20, 20), c) for c in ("red", "blue")]
        b = io.BytesIO()
        frames[0].save(b, format="GIF", save_all=True, append_images=frames[1:])
        out = preprocess(b.getvalue())
        assert out.mime_type == "image/jpeg" and any("fotograma" in n for n in out.notes)

    def test_image_over_api_limit_is_recompressed(self):
        import os
        noise = Image.frombytes("RGB", (600, 600), os.urandom(600 * 600 * 3))
        b = io.BytesIO(); noise.save(b, format="PNG")
        data = b.getvalue()
        assert len(data) > 300_000
        out = preprocess(data, max_image_bytes=300_000)
        assert len(out.content) <= 300_000 and out.mime_type == "image/jpeg"

    def test_cannot_shrink_enough(self):
        import os
        noise = Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3))
        b = io.BytesIO(); noise.save(b, format="PNG")
        with pytest.raises(FileTooLarge):
            preprocess(b.getvalue(), max_image_bytes=2000)

    def test_corrupt_image(self):
        with pytest.raises(CorruptFile):
            preprocess(make_img("PNG")[:40])
        with pytest.raises(CorruptFile):
            preprocess(b"\xff\xd8\xff\xe0 basura")

    def test_decompression_bomb(self, monkeypatch):
        monkeypatch.setattr(pp, "MAX_IMAGE_PIXELS", 1000)
        with pytest.raises(FileTooLarge):
            preprocess(make_img("PNG", size=(200, 200)))


class TestLimits:
    def test_file_too_large(self):
        with pytest.raises(FileTooLarge):
            preprocess(make_pdf(), max_bytes=100)

    def test_unsupported_type(self):
        with pytest.raises(UnsupportedFileType):
            preprocess(b"MZ\x90\x00 not a doc")

    def test_default_limits_come_from_settings(self, settings):
        settings.EXTRACTION_MAX_PAGES = 1
        with pytest.raises(TooManyPages):
            preprocess(make_pdf(2))
        settings.UPLOAD_MAX_FILE_MB = 0
        with pytest.raises(FileTooLarge):
            preprocess(make_pdf(1))

    def test_error_codes_are_distinct(self):
        codes = {c.code for c in (UnsupportedFileType, FileTooLarge, TooManyPages, CorruptFile, EncryptedPdf)}
        assert len(codes) == 5


@pytest.mark.django_db
class TestDocumentIntegration:
    def _doc(self, data, name="f.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return f.DocumentFactory(file=SimpleUploadedFile(name, data))

    def test_load_and_preprocess_reads_from_storage(self):
        doc = self._doc(make_pdf(2))
        pre = load_and_preprocess(doc)
        assert pre.page_count == 2 and pre.mime_type == "application/pdf"

    def test_size_checked_before_reading(self, settings):
        doc = self._doc(make_pdf(1))
        settings.UPLOAD_MAX_FILE_MB = 0
        with pytest.raises(FileTooLarge):
            load_and_preprocess(doc)

    def test_missing_file(self):
        doc = self._doc(make_pdf(1))
        doc.file.storage.delete(doc.file.name)
        with pytest.raises(CorruptFile):
            load_and_preprocess(doc)

    def test_record_file_metadata_updates_document_file(self):
        doc = self._doc(make_pdf(4))
        df = f.DocumentFileFactory(document=doc, mime_type="", sha256="d" * 64)
        record_file_metadata(doc, load_and_preprocess(doc))
        df.refresh_from_db()
        assert (df.mime_type, df.page_count) == ("application/pdf", 4)

    def test_record_file_metadata_without_documentfile_is_noop(self):
        doc = self._doc(make_pdf(1))
        record_file_metadata(doc, load_and_preprocess(doc))  # no lanza


def test_output_is_always_accepted_by_the_extractor():
    from documents.services.extraction.base import SUPPORTED_MIME_TYPES
    for data in (make_pdf(), make_img("HEIF"), make_img("PNG"), make_img("GIF"), make_img("JPEG", exif_orientation=3)):
        assert preprocess(data).mime_type in SUPPORTED_MIME_TYPES
