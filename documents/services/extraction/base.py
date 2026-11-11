"""Interfaz del proveedor de extracción y errores comunes.

Cualquier proveedor (Claude u otro OCR) implementa `Extractor`; el resto de la
app solo depende de esta interfaz, de modo que se puede mockear o cambiar.
"""
from dataclasses import dataclass, field
from typing import Protocol

from .schemas import ExtractionResult

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


@dataclass(frozen=True)
class ExtractionInput:
    content: bytes
    mime_type: str
    client_name: str = ""
    client_tax_id: str = ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class ExtractionOutput:
    result: ExtractionResult
    model: str
    prompt_version: str
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None
    stop_reason: str | None = None


class ExtractionError(Exception):
    """Base. `retryable`: tiene sentido reintentar la misma petición más tarde.
    `fallback_eligible`: tiene sentido probar con el modelo de respaldo."""
    code = "extraction_error"
    retryable = False
    fallback_eligible = False

    def __init__(self, message: str = "", *, usage: Usage | None = None, request_id: str | None = None):
        super().__init__(message)
        self.usage = usage or Usage()
        self.request_id = request_id


class ConfigurationError(ExtractionError):
    code = "configuration"


class UnsupportedInputError(ExtractionError):
    code = "unsupported_input"


class RateLimitedError(ExtractionError):
    code = "rate_limited"
    retryable = True

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ProviderTimeoutError(ExtractionError):
    code = "timeout"
    retryable = True


class ProviderUnavailableError(ExtractionError):
    code = "provider_unavailable"
    retryable = True


class InvalidRequestError(ExtractionError):
    code = "invalid_request"


class InvalidResponseError(ExtractionError):
    code = "invalid_response"
    fallback_eligible = True


class RefusedError(ExtractionError):
    code = "refused"
    fallback_eligible = True


class Extractor(Protocol):
    model: str

    def extract(self, inp: ExtractionInput) -> ExtractionOutput: ...
