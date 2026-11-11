"""Preprocesado de archivos antes de la extracción.

- Detecta el tipo real por contenido (nunca por extensión ni por el MIME del cliente).
- PDF: se envía tal cual (Claude lo lee de forma nativa, multipágina incluida);
  solo se valida (no cifrado, no corrupto, nº de páginas dentro del límite).
- Imágenes: HEIC/HEIF → JPEG, corrección de rotación EXIF, límite de lado/peso,
  se elimina el EXIF (GPS, dispositivo). Si no hace falta tocar nada se envía tal cual.
- Nunca se trunca en silencio: si excede los límites se rechaza con un error claro.

El archivo original NO se modifica: esto solo prepara los bytes que se envían al proveedor.
"""
import io
import logging
from dataclasses import dataclass, field

import pillow_heif
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

pillow_heif.register_heif_opener()

# Protección frente a «bombas de descompresión» (imágenes diminutas en bytes y enormes en píxeles).
MAX_IMAGE_PIXELS = 80_000_000

PDF = "application/pdf"
JPEG, PNG, WEBP, GIF = "image/jpeg", "image/png", "image/webp", "image/gif"
HEIC = "image/heic"
IMAGE_TYPES = {JPEG, PNG, WEBP, GIF, HEIC}
ALLOWED_TYPES = IMAGE_TYPES | {PDF}
# Tipos que la API de extracción acepta directamente.
NATIVE_TYPES = {PDF, JPEG, PNG, WEBP, GIF}
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


class PreprocessError(Exception):
    code = "preprocess_error"


class UnsupportedFileType(PreprocessError):
    code = "unsupported_type"


class FileTooLarge(PreprocessError):
    code = "file_too_large"


class TooManyPages(PreprocessError):
    code = "too_many_pages"


class CorruptFile(PreprocessError):
    code = "corrupt_file"


class EncryptedPdf(PreprocessError):
    code = "encrypted_pdf"


@dataclass
class PreprocessedFile:
    content: bytes
    mime_type: str
    original_mime_type: str
    page_count: int | None = None
    width: int | None = None
    height: int | None = None
    converted: bool = False
    notes: list[str] = field(default_factory=list)


def detect_mime(content: bytes) -> str | None:
    """Tipo real a partir de la firma del archivo; None si no es un formato admitido."""
    head = content[:16]
    if head.startswith(b"%PDF"):
        return PDF
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return GIF
    if head[4:8] == b"ftyp" and head[8:12] in HEIF_BRANDS:
        return HEIC
    return None


def _limits(max_bytes, max_pages, max_side, max_image_bytes):
    return (
        max_bytes if max_bytes is not None else settings.UPLOAD_MAX_FILE_MB * 1024 * 1024,
        max_pages if max_pages is not None else settings.EXTRACTION_MAX_PAGES,
        max_side if max_side is not None else settings.EXTRACTION_MAX_IMAGE_SIDE,
        max_image_bytes if max_image_bytes is not None else settings.EXTRACTION_MAX_IMAGE_MB * 1024 * 1024,
    )


def preprocess(
    content: bytes,
    *,
    max_bytes: int | None = None,
    max_pages: int | None = None,
    max_side: int | None = None,
    max_image_bytes: int | None = None,
) -> PreprocessedFile:
    max_bytes, max_pages, max_side, max_image_bytes = _limits(max_bytes, max_pages, max_side, max_image_bytes)
    if len(content) > max_bytes:
        raise FileTooLarge(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
    mime = detect_mime(content)
    if mime is None:
        raise UnsupportedFileType("Tipo de archivo no admitido (PDF, JPG, PNG, WEBP, GIF o HEIC).")
    if mime == PDF:
        return _pdf(content, max_pages)
    return _image(content, mime, max_side, max_image_bytes)


# --- PDF -------------------------------------------------------------------

def _pdf(content: bytes, max_pages: int) -> PreprocessedFile:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # Muchos PDF «cifrados» solo tienen restricciones y abren con contraseña vacía.
            if not reader.decrypt(""):
                raise EncryptedPdf("El PDF está protegido con contraseña.")
        pages = len(reader.pages)
    except PreprocessError:
        raise
    except (PdfReadError, ValueError, KeyError, AttributeError, OSError, RecursionError) as exc:
        raise CorruptFile("El PDF está dañado o no se puede leer.") from exc
    if pages == 0:
        raise CorruptFile("El PDF no tiene páginas.")
    if pages > max_pages:
        raise TooManyPages(f"El PDF tiene {pages} páginas; el máximo es {max_pages}.")
    return PreprocessedFile(content=content, mime_type=PDF, original_mime_type=PDF, page_count=pages)


# --- Imágenes ---------------------------------------------------------------

def _image(content: bytes, mime: str, max_side: int, max_image_bytes: int) -> PreprocessedFile:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.load()
            return _process_image(img, content, mime, max_side, max_image_bytes)
    except PreprocessError:
        raise
    except Image.DecompressionBombError as exc:
        raise FileTooLarge("La imagen tiene demasiados píxeles.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as exc:
        raise CorruptFile("La imagen está dañada o no se puede leer.") from exc


def _process_image(img, content: bytes, mime: str, max_side: int, max_image_bytes: int) -> PreprocessedFile:
    notes: list[str] = []
    orientation = img.getexif().get(0x0112, 1)
    has_exif = bool(img.getexif())
    animated = getattr(img, "n_frames", 1) > 1
    needs_convert = mime not in NATIVE_TYPES          # HEIC
    needs_rotate = orientation not in (None, 1)
    too_big_px = max(img.size) > max_side
    too_big_bytes = len(content) > max_image_bytes

    if not (needs_convert or needs_rotate or too_big_px or too_big_bytes or has_exif or animated):
        return PreprocessedFile(
            content=content, mime_type=mime, original_mime_type=mime,
            width=img.width, height=img.height,
        )

    if needs_convert:
        notes.append("convertida de HEIC a JPEG")
    if needs_rotate:
        notes.append("rotación EXIF corregida")
    if has_exif:
        notes.append("metadatos EXIF eliminados")
    if animated:
        img.seek(0)
        notes.append("solo el primer fotograma")

    img = ImageOps.exif_transpose(img)
    img = _flatten_to_rgb(img)
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        notes.append(f"redimensionada a {max_side}px")

    data = _encode_jpeg(img, max_image_bytes)
    return PreprocessedFile(
        content=data, mime_type=JPEG, original_mime_type=mime,
        width=img.width, height=img.height, converted=True, notes=notes,
    )


def _flatten_to_rgb(img):
    """Quita la transparencia sobre fondo blanco y deja la imagen en RGB."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _encode_jpeg(img, max_bytes: int) -> bytes:
    """JPEG sin metadatos; baja calidad (y luego tamaño) hasta caber en `max_bytes`."""
    quality = 90
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data
        if quality > 60:
            quality -= 10
        elif min(img.size) > 400:
            img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.LANCZOS)
        else:
            raise FileTooLarge("No se puede reducir la imagen al tamaño máximo permitido.")


# --- Integración con Document ------------------------------------------------

def load_and_preprocess(document, **limits) -> PreprocessedFile:
    """Lee el archivo del almacenamiento (R2/disco) y lo preprocesa.

    Comprueba el tamaño ANTES de leer, para no cargar en memoria archivos enormes.
    """
    max_bytes = limits.get("max_bytes") if limits.get("max_bytes") is not None else settings.UPLOAD_MAX_FILE_MB * 1024 * 1024
    try:
        size = document.file.size
    except Exception as exc:
        raise CorruptFile("No se puede acceder al archivo almacenado.") from exc
    if size > max_bytes:
        raise FileTooLarge(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
    with document.file.open("rb") as fh:
        content = fh.read()
    return preprocess(content, **limits)


def record_file_metadata(document, pre: PreprocessedFile) -> None:
    """Guarda MIME real y nº de páginas en el DocumentFile, si existe."""
    from documents.models import DocumentFile

    updates = {"mime_type": pre.original_mime_type}
    if pre.page_count is not None:
        updates["page_count"] = pre.page_count
    DocumentFile.objects.filter(document=document).update(**updates)
