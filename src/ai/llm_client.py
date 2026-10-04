"""
Meridian Commerce — LLM Client (provider: OpenRouter)

Isolates all direct contact with the LLM provider's API behind a small
interface (`LLMClient`), so `classifier.py` (Phase 3) and
`response/generator.py` (Phase 5) never import the provider package directly.

Current provider: OpenRouter, reached through its OpenAI-compatible API with
the official OpenAI Python SDK:

    base_url = https://openrouter.ai/api/v1
    api key  = OPENROUTER_API_KEY   (local .env only, never committed)
    model    = MODEL_NAME            (default "openrouter/free")

Free routing only: the client refuses to start with a model that is not
OpenRouter's free router ("openrouter/free") or an explicit ":free" variant,
so a stray MODEL_NAME can never silently spend credits.

Structured output is obtained exactly the way the pipeline has always relied
on it: ONE forced tool/function call whose JSON arguments become
`LLMResponse.tool_input`. The client only guarantees "a JSON object came
back"; the authoritative validation stays where it always was (Pydantic in
classifier.py, required-field + safety-scan checks in response/generator.py).

Error model (unchanged concepts, provider-neutral types):
    LLMAuthError              missing/invalid OPENROUTER_API_KEY — never retried
    LLMTimeoutError           request timed out                  — retried
    LLMRateLimitError         HTTP 429 (free tier: per-minute/day caps) — retried
    LLMAPIError               connection errors / HTTP 5xx — retried;
                              other HTTP 4xx (bad request, 402, 404) — not retried
    LLMMalformedResponseError no/invalid tool call in the response — retried
    LLMConfigError            non-free MODEL_NAME                — never retried

The API key is never logged or echoed: it is redacted from every error
message this module produces.
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_FREE_MODEL = "openrouter/free"


def is_free_openrouter_model(model: Optional[str]) -> bool:
    """True only for OpenRouter's free router or an explicit ':free' model
    variant. Anything else could bill the account, which this project must
    never do."""
    if not model or not model.strip():
        return False
    model = model.strip()
    return model == DEFAULT_FREE_MODEL or model.endswith(":free")


# ----------------------------------------------------------------------------
# Result / error types
# ----------------------------------------------------------------------------
@dataclass
class LLMResponse:
    tool_input: dict
    input_tokens: int
    output_tokens: int
    latency_ms: float
    raw_stop_reason: str
    # Which concrete model served the call. With "openrouter/free" the router
    # picks a model per request, so this is recorded for traceability.
    model: Optional[str] = None


class LLMClientError(Exception):
    """Base class for all LLM client errors. `error_type` is the stable,
    provider-neutral code that classifier.py / generator.py record."""
    error_type = "unknown_error"


class LLMAuthError(LLMClientError):
    error_type = "auth_error"


class LLMTimeoutError(LLMClientError):
    error_type = "timeout"


class LLMRateLimitError(LLMClientError):
    error_type = "rate_limit"


class LLMAPIError(LLMClientError):
    error_type = "api_error"


class LLMMalformedResponseError(LLMClientError):
    """Raised when the API response does not contain a valid forced tool call."""
    error_type = "malformed_response"


class LLMConfigError(LLMClientError):
    """Raised for configuration that must not be used (e.g. a paid model)."""
    error_type = "config_error"


# ----------------------------------------------------------------------------
# Abstract interface
# ----------------------------------------------------------------------------
class LLMClient(ABC):
    @abstractmethod
    def classify(self, system_prompt: str, user_prompt: str, tool_schema: dict) -> LLMResponse:
        """Call the model with a forced structured-output (tool) request and
        return the raw structured output plus usage/timing metadata. The
        caller is responsible for validating the content."""
        raise NotImplementedError

    def generate_structured(self, system_prompt: str, user_prompt: str,
                            tool_schema: dict) -> LLMResponse:
        """Phase 5 entry point. Same forced-tool contract as `classify`; the
        separate name only documents intent at the call site. Defaults to
        `classify`, so any LLMClient (including test fakes) supports it."""
        return self.classify(system_prompt, user_prompt, tool_schema)


# ----------------------------------------------------------------------------
# OpenRouter implementation
# ----------------------------------------------------------------------------
def _to_openai_tool(tool_schema: dict) -> dict:
    """Project tool schemas keep their original shape ({name, description,
    input_schema}); this converts one to the OpenAI function-tool format."""
    parameters = tool_schema.get("input_schema") or tool_schema.get("parameters")
    if not tool_schema.get("name") or not isinstance(parameters, dict):
        raise LLMMalformedResponseError(
            "Tool schema must define a 'name' and an 'input_schema' object.")
    return {
        "type": "function",
        "function": {
            "name": tool_schema["name"],
            "description": tool_schema.get("description", ""),
            "parameters": parameters,
        },
    }


class OpenRouterLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_FREE_MODEL, max_tokens: int = 1024,
                 timeout_seconds: float = 30.0, max_retries: int = 3):
        if not api_key or not str(api_key).strip():
            raise LLMAuthError(
                "OPENROUTER_API_KEY is not set. Put it in your local .env file "
                "(see .env.example); it must never be committed.")
        if not is_free_openrouter_model(model):
            raise LLMConfigError(
                f"MODEL_NAME '{model}' is not a free OpenRouter model. This project "
                f"only uses free routing: set MODEL_NAME={DEFAULT_FREE_MODEL} "
                "(or another model id ending in ':free').")

        self._api_key = str(api_key).strip()
        self._model = model.strip()
        self._max_tokens = max_tokens
        # max_retries keeps its original meaning: total attempts per call.
        self._max_retries = max(1, int(max_retries))
        # SDK-level retries are disabled so this class owns retry behavior.
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=timeout_seconds,
            max_retries=0,
        )

    # -- helpers -------------------------------------------------------------
    def _redact(self, text: str) -> str:
        text = str(text)
        if self._api_key:
            text = text.replace(self._api_key, "[REDACTED]")
        return text

    def _call_with_tool(self, system_prompt: str, user_prompt: str,
                        tool_schema: dict) -> LLMResponse:
        tool = _to_openai_tool(tool_schema)
        tool_name = tool["function"]["name"]
        last_error: Optional[LLMClientError] = None

        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    tools=[tool],
                    tool_choice={"type": "function", "function": {"name": tool_name}},
                )
                latency_ms = (time.monotonic() - start) * 1000
                return self._parse_response(response, tool_name, latency_ms)

            except AuthenticationError as e:
                # Invalid credentials: retrying cannot help.
                raise LLMAuthError(self._redact(
                    f"OpenRouter rejected OPENROUTER_API_KEY (HTTP 401): {e}")) from e
            except APITimeoutError as e:          # subclass of APIConnectionError
                last_error = LLMTimeoutError(self._redact(f"OpenRouter request timed out: {e}"))
            except RateLimitError as e:
                last_error = LLMRateLimitError(self._redact(
                    f"OpenRouter rate limit hit (HTTP 429; free models have per-minute "
                    f"and per-day caps): {e}"))
            except APIConnectionError as e:
                last_error = LLMAPIError(self._redact(f"OpenRouter connection error: {e}"))
            except APIStatusError as e:
                status = getattr(e, "status_code", None)
                if status == 402:
                    hint = (" (402 Payment Required: the request needs credits; this "
                            "project only supports free routing, check MODEL_NAME)")
                else:
                    hint = ""
                err = LLMAPIError(self._redact(f"status={status}, message={e}{hint}"))
                if status is not None and status < 500 and status not in (408, 409):
                    # Deterministic client-side failure: fail fast instead of
                    # burning free-tier quota on identical retries.
                    raise err from e
                last_error = err
            except LLMMalformedResponseError as e:
                last_error = e

            if attempt < self._max_retries:
                time.sleep(min(2 ** attempt, 10))

        raise last_error or LLMAPIError("LLM call failed for an unknown reason.")

    @staticmethod
    def _parse_response(response, tool_name: str, latency_ms: float) -> LLMResponse:
        choices = getattr(response, "choices", None)
        if not choices:
            raise LLMMalformedResponseError("OpenRouter returned no choices.")

        choice = choices[0]
        message = getattr(choice, "message", None)
        tool_calls = (getattr(message, "tool_calls", None) or []) if message else []
        tool_call = next(
            (c for c in tool_calls
             if getattr(getattr(c, "function", None), "name", None) == tool_name),
            None,
        )
        if tool_call is None:
            raise LLMMalformedResponseError(f"No '{tool_name}' tool call in response.")

        arguments = tool_call.function.arguments
        if isinstance(arguments, dict):
            tool_input = arguments
        else:
            if not arguments or not str(arguments).strip():
                raise LLMMalformedResponseError(
                    f"Tool call '{tool_name}' contained no arguments.")
            try:
                tool_input = json.loads(arguments)
            except (TypeError, ValueError) as e:
                raise LLMMalformedResponseError(
                    f"Tool call arguments were not valid JSON: {e}") from e
        if not isinstance(tool_input, dict):
            raise LLMMalformedResponseError("Tool call arguments must decode to a JSON object.")

        usage = getattr(response, "usage", None)
        input_tokens = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        output_tokens = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0

        return LLMResponse(
            tool_input=tool_input,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            raw_stop_reason=getattr(choice, "finish_reason", None) or "unknown",
            model=getattr(response, "model", None),
        )

    # -- public API ----------------------------------------------------------
    def classify(self, system_prompt: str, user_prompt: str, tool_schema: dict) -> LLMResponse:
        """Phase 3: forced `classify_ticket` tool call."""
        return self._call_with_tool(system_prompt, user_prompt, tool_schema)

    def generate_structured(self, system_prompt: str, user_prompt: str,
                            tool_schema: dict) -> LLMResponse:
        """Phase 5: forced `draft_support_response` tool call."""
        return self._call_with_tool(system_prompt, user_prompt, tool_schema)
