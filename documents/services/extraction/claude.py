"""Extractor basado en la API de Claude (salida estructurada con Pydantic)."""
import base64
import logging

import anthropic
import pydantic

from .base import (
    SUPPORTED_MIME_TYPES, ConfigurationError, ExtractionInput, ExtractionOutput,
    InvalidRequestError, InvalidResponseError, ProviderTimeoutError,
    ProviderUnavailableError, RateLimitedError, RefusedError,
    UnsupportedInputError, Usage,
)
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_text
from .schemas import ExtractionResult

logger = logging.getLogger(__name__)


class ClaudeExtractor:
    def __init__(
        self,
        model: str,
        *,
        effort: str = "low",
        max_tokens: int = 8192,
        timeout: float = 120.0,
        api_key: str | None = None,
        client=None,
    ):
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._api_key = api_key
        self._client = client

    @property
    def client(self):
        if self._client is None:
            if not self._api_key:
                raise ConfigurationError("Falta ANTHROPIC_API_KEY")
            # max_retries del SDK: reintenta 408/409/429/5xx con backoff.
            self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self.timeout, max_retries=2)
        return self._client

    @staticmethod
    def _content_block(inp: ExtractionInput) -> dict:
        if inp.mime_type not in SUPPORTED_MIME_TYPES:
            raise UnsupportedInputError(f"Tipo no soportado: {inp.mime_type}")
        data = base64.standard_b64encode(inp.content).decode("ascii")
        kind = "document" if inp.mime_type == "application/pdf" else "image"
        return {"type": kind, "source": {"type": "base64", "media_type": inp.mime_type, "data": data}}

    def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        block = self._content_block(inp)
        client = self.client  # puede lanzar ConfigurationError
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                # El sistema es estable → se cachea; lo variable va en el mensaje de usuario.
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{
                    "role": "user",
                    "content": [block, {"type": "text", "text": build_user_text(inp)}],
                }],
                output_format=ExtractionResult,
                output_config={"effort": self.effort},
            )
        except anthropic.RateLimitError as e:
            retry_after = _retry_after(e)
            raise RateLimitedError("Límite de peticiones", retry_after=retry_after) from None
        except anthropic.APITimeoutError:
            raise ProviderTimeoutError("Tiempo de espera agotado") from None
        except anthropic.APIConnectionError:
            raise ProviderUnavailableError("Error de conexión con el proveedor") from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise ConfigurationError("Credenciales de la API rechazadas") from None
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 or e.status_code == 529:
                raise ProviderUnavailableError(f"Error del proveedor ({e.status_code})") from None
            # Mensaje del proveedor: describe la petición, no contiene el documento.
            raise InvalidRequestError(f"Petición rechazada ({e.status_code}): {e.message}") from None
        except pydantic.ValidationError:
            raise InvalidResponseError("La respuesta no cumple el esquema") from None

        usage = _usage(response)
        request_id = getattr(response, "_request_id", None)
        stop = getattr(response, "stop_reason", None)
        logger.info(
            "extraction model=%s request_id=%s stop=%s in=%s out=%s cache_read=%s",
            self.model, request_id, stop, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
        )
        if stop == "refusal":
            raise RefusedError("El modelo rechazó la petición", usage=usage, request_id=request_id)
        if stop == "max_tokens":
            raise InvalidResponseError("Respuesta truncada (max_tokens)", usage=usage, request_id=request_id)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise InvalidResponseError("Sin salida estructurada", usage=usage, request_id=request_id)
        return ExtractionOutput(
            result=parsed, model=getattr(response, "model", None) or self.model,
            prompt_version=PROMPT_VERSION, usage=usage, request_id=request_id, stop_reason=stop,
        )


def _usage(response) -> Usage:
    u = getattr(response, "usage", None)
    g = lambda name: int(getattr(u, name, 0) or 0)  # noqa: E731
    return Usage(
        input_tokens=g("input_tokens"), output_tokens=g("output_tokens"),
        cache_read_tokens=g("cache_read_input_tokens"),
        cache_creation_tokens=g("cache_creation_input_tokens"),
    )


def _retry_after(exc) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None
