"""Small injectable OpenRouter client. Only explicit, currently zero-priced models."""

import http.client
import json
import math
import os
import re
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["answered", "partial", "insufficient_evidence"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "answer", "citations", "missing_evidence"],
}


class GenerationError(ValueError):
    """Provider/format failures are errors, never evidence-insufficiency decisions."""

    def __init__(self, kind: str, message: str, *, metadata: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.metadata = metadata


@dataclass(frozen=True)
class GenerationConfig:
    model_id: str = "nvidia/nemotron-3.5-super-vl:free"
    temperature: float = 0
    max_output_tokens: int = 1600
    max_prompt_bytes: int = 24000
    timeout_seconds: float = 45

    def __post_init__(self):
        if not isinstance(self.model_id, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+:free", self.model_id):
            raise ValueError("Generation requires one explicit provider/model:free ID; routers and paid IDs are rejected.")
        for field, low, high in (("max_output_tokens", 128, 4096), ("max_prompt_bytes", 4000, 48000)):
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field} must be an integer between {low} and {high}.")
        for field, low, high in (("temperature", 0, 1), ("timeout_seconds", 1, 60)):
            value = getattr(self, field)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} must be between {low} and {high}.")


def load_generation_config(path: Path) -> GenerationConfig:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != set(GenerationConfig.__dataclass_fields__):
        raise ValueError("Generation configuration must contain exactly the documented settings.")
    return GenerationConfig(**data)


@dataclass(frozen=True)
class Completion:
    content: str
    metadata: dict


class Generator(Protocol):
    def complete(self, messages: tuple[dict, ...], config: GenerationConfig) -> Completion: ...


class _NoRedirect(HTTPRedirectHandler):
    # Never forward credentials or silently change the API endpoint.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_error(code: int) -> GenerationError:
    messages = {
        401: ("authentication", "OpenRouter authentication failed; check OPENROUTER_API_KEY."),
        402: ("account", "OpenRouter rejected the account/credit state; no paid request or fallback was attempted."),
        403: ("access", "OpenRouter denied access; check account and provider data-policy settings."),
        404: ("unavailable", "The selected free model or endpoint is unavailable."),
        408: ("timeout", "OpenRouter timed out; no automatic retry was made."),
        429: ("rate_limit", "OpenRouter free capacity is rate-limited; wait before manually retrying."),
        502: ("unavailable", "The free model provider failed or returned an invalid response."),
        503: ("unavailable", "No eligible free provider is available with the required settings."),
    }
    kind, message = messages.get(code, ("provider", "OpenRouter request failed; no automatic retry or fallback was made."))
    return GenerationError(kind, message)


class OpenRouterClient:
    """Two bounded HTTP calls: public price preflight, then one completion. No SDK."""

    def __init__(self, *, transport=None):
        # The injectable transport has the same request/timeout contract as opener.open.
        self._transport = transport or build_opener(_NoRedirect()).open

    def _json(self, request: Request, timeout: float, key: str, *, limit: int) -> dict:
        try:
            with self._transport(request, timeout=timeout) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise GenerationError("invalid_response", "OpenRouter response exceeded the allowed size.")
            # Do not persist provider error bodies or echoed credentials, even in tests.
            text = raw.decode("utf-8")
            if key in text or re.search(r"sk-or-v1-[A-Za-z0-9_-]+", text):
                raise GenerationError("secret_redaction", "Provider response contained credential-like data and was discarded.")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError
            if "error" in data:
                error = data["error"]
                code = error.get("code") if isinstance(error, dict) else None
                raise _http_error(code if type(code) is int else 500)
            return data
        except GenerationError:
            raise
        except HTTPError as error:
            error.close()
            raise _http_error(error.code) from None
        except (TimeoutError, socket.timeout):
            raise GenerationError("timeout", "OpenRouter request timed out; no automatic retry was made.") from None
        except (OSError, URLError, http.client.HTTPException):
            raise GenerationError("transport", "OpenRouter connection failed or was interrupted; no automatic retry was made.") from None
        except (ValueError, UnicodeError):
            raise GenerationError("invalid_response", "OpenRouter returned malformed JSON; response body discarded.") from None

    def complete(self, messages: tuple[dict, ...], config: GenerationConfig) -> Completion:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise GenerationError("configuration", "Set OPENROUTER_API_KEY in your environment; prompt inspection needs no key.")
        if any(c.isspace() for c in key):
            raise GenerationError("configuration", "OPENROUTER_API_KEY contains whitespace; check the environment value.")
        encoded_messages = json.dumps(messages, ensure_ascii=False)
        if key in encoded_messages or re.search(r"sk-or-v1-[A-Za-z0-9_-]+", encoded_messages):
            raise GenerationError("secret_redaction", "Credential-like data in the prompt was blocked before sending.")
        prompt_bytes = len(encoded_messages.encode())
        if prompt_bytes > config.max_prompt_bytes:
            raise GenerationError("context", "Prompt exceeds the configured byte budget; no request was sent.")
        started = time.perf_counter()
        catalog = self._json(Request("https://openrouter.ai/api/v1/models"), config.timeout_seconds, key, limit=4_000_000)
        models = catalog.get("data")
        model = next((m for m in models if isinstance(m, dict) and m.get("id") == config.model_id), None) if isinstance(models, list) else None
        if model is None:
            raise GenerationError("unavailable", "Selected :free model is absent from the current OpenRouter catalog.")
        pricing = model.get("pricing")
        try:
            if not isinstance(pricing, dict) or not {"prompt", "completion"} <= pricing.keys():
                raise ValueError
            for field in ("prompt", "completion", "request"):
                price = Decimal(str(pricing.get(field, "0")))
                if not price.is_finite() or price != 0:
                    raise ValueError
        except (ValueError, InvalidOperation):
            raise GenerationError("pricing", "Zero input/output/request pricing could not be verified; generation blocked.") from None
        required = {"response_format", "structured_outputs", "temperature", "max_tokens", "reasoning"}
        parameters = model.get("supported_parameters")
        if not isinstance(parameters, list) or any(not isinstance(p, str) for p in parameters) or not required <= set(parameters):
            raise GenerationError("unavailable", "Selected free model lacks required structured-output/generation parameters.")
        context = model.get("context_length")
        top_provider = model.get("top_provider")
        output_cap = top_provider.get("max_completion_tokens") if isinstance(top_provider, dict) else None
        # Conservative admission estimate, not the provider's exact tokenizer.
        # Include schema bytes and 1,024 framing tokens; never auto-compress text.
        input_bound = prompt_bytes + len(json.dumps(ANSWER_SCHEMA).encode()) + 1024
        if type(context) is not int or input_bound + config.max_output_tokens > context:
            raise GenerationError("context", "Prompt/output reservation exceeds the catalog context budget; no text was truncated.")
        if type(output_cap) is not int or config.max_output_tokens > output_cap:
            raise GenerationError("context", "Configured output reservation exceeds the model's catalog output limit.")
        payload = {
            "model": config.model_id, "messages": messages, "stream": False,
            "temperature": config.temperature, "max_tokens": config.max_output_tokens,
            "reasoning": {"enabled": False}, "transforms": [],
            "provider": {"allow_fallbacks": False, "require_parameters": True,
                         "max_price": {"prompt": 0, "completion": 0, "request": 0}},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "doclens_answer", "strict": True, "schema": ANSWER_SCHEMA,
            }},
        }
        request = Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        })
        before = time.perf_counter()
        data = self._json(request, config.timeout_seconds, key, limit=256_000)
        metadata = {
            "provider": "openrouter", "requested_model": config.model_id,
            "returned_model": data.get("model"), "settings": asdict(config),
            "latency_seconds": time.perf_counter() - before,
            "preflight_and_generation_seconds": time.perf_counter() - started,
            "pricing_checked_at": datetime.now(timezone.utc).isoformat(),
            "verified_pricing": {field: pricing.get(field, "0") for field in ("prompt", "completion", "request")},
            "catalog_context_tokens": context, "input_token_admission_estimate": input_bound,
            "automatic_retries": 0, "provider_fallbacks": False,
        }
        accepted_models = {config.model_id, config.model_id.removesuffix(":free")}
        if isinstance(model.get("canonical_slug"), str):
            accepted_models.add(model["canonical_slug"])
        returned_model = data.get("model")
        if not isinstance(returned_model, str) or returned_model not in accepted_models:
            raise GenerationError("invalid_response", "Returned model does not match the selected model or catalog canonical ID.", metadata=metadata)
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise GenerationError("invalid_response", "Expected exactly one OpenRouter completion.", metadata=metadata)
        choice = choices[0]
        metadata["finish_reason"] = choice.get("finish_reason")
        if "error" in choice:
            raise GenerationError("provider", "Provider failed while generating the answer.", metadata=metadata)
        if choice.get("finish_reason") != "stop":
            raise GenerationError("invalid_response", "Completion did not finish normally (truncated, filtered, or failed); answer rejected.", metadata=metadata)
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant" or message.get("tool_calls") or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise GenerationError("invalid_response", "Completion has no usable answer text.", metadata=metadata)
        usage = data.get("usage")
        if usage is not None:
            if not isinstance(usage, dict):
                raise GenerationError("invalid_response", "Malformed provider usage metadata.", metadata=metadata)
            fields = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
            for field in fields:
                if field in usage:
                    value = usage[field]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise GenerationError("invalid_response", "Malformed numeric provider usage metadata.", metadata=metadata)
            # Whitelist numeric fields: arbitrary provider strings never reach reports.
            metadata["usage"] = {k: v for k, v in usage.items() if k in fields}
            if metadata["usage"].get("cost", 0) != 0:
                raise GenerationError("pricing", "Provider reported nonzero cost despite zero-price constraints; stop and inspect account activity.", metadata=metadata)
        else:
            metadata["usage"] = None
        return Completion(message["content"], metadata)
