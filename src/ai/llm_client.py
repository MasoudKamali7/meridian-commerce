"""
Meridian Commerce — Phase 3: LLM Client

Isolates all direct contact with the LLM provider's API behind a small
interface (`LLMClient`), so `classifier.py` never imports the `anthropic`
package directly. Swapping providers (or adding a second one) means writing
one new class here, not touching the classifier or the prompts.

Error handling: this module distinguishes between error types the caller
needs to react to differently (timeout vs. rate limit vs. auth vs. malformed
response) rather than collapsing everything into a single generic exception.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import anthropic


# ----------------------------------------------------------------------------
# Result / error types
# ----------------------------------------------------------------------------
@dataclass
class LLMResponse:
    tool_input: dict           # the parsed tool-call arguments (raw, not yet validated)
    input_tokens: int
    output_tokens: int
    latency_ms: float
    raw_stop_reason: str


class LLMClientError(Exception):
    """Base class for all LLM client errors. `error_type` is a short,
    log-friendly string (used in structured logs / evaluation reports)."""
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
    """Raised when the API call succeeds but no valid tool_use block with the
    expected tool name is present in the response."""
    error_type = "malformed_response"


# ----------------------------------------------------------------------------
# Abstract interface
# ----------------------------------------------------------------------------
class LLMClient(ABC):
    @abstractmethod
    def classify(self, system_prompt: str, user_prompt: str, tool_schema: dict) -> LLMResponse:
        """Call the model with a forced tool-use request and return the raw
        (unvalidated) structured output plus usage/timing metadata.
        Raises an LLMClientError subclass on any failure."""
        raise NotImplementedError


# ----------------------------------------------------------------------------
# Anthropic implementation
# ----------------------------------------------------------------------------
class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024,
                 timeout_seconds: float = 30.0, max_retries: int = 3):
        if not api_key:
            raise LLMAuthError("No API key provided to AnthropicLLMClient.")
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries

    def classify(self, system_prompt: str, user_prompt: str, tool_schema: dict) -> LLMResponse:
        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=[tool_schema],
                    tool_choice={"type": "tool", "name": tool_schema["name"]},
                )
                latency_ms = (time.monotonic() - start) * 1000

                tool_use_block = next(
                    (b for b in response.content if getattr(b, "type", None) == "tool_use"
                     and b.name == tool_schema["name"]),
                    None,
                )
                if tool_use_block is None:
                    raise LLMMalformedResponseError(
                        f"No '{tool_schema['name']}' tool_use block in response."
                    )

                return LLMResponse(
                    tool_input=tool_use_block.input,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    latency_ms=latency_ms,
                    raw_stop_reason=response.stop_reason,
                )

            except anthropic.AuthenticationError as e:
                # Not retryable — credentials are wrong/missing.
                raise LLMAuthError(str(e)) from e

            except anthropic.APITimeoutError as e:
                last_error = LLMTimeoutError(str(e))

            except anthropic.RateLimitError as e:
                last_error = LLMRateLimitError(str(e))

            except anthropic.APIStatusError as e:
                # 5xx / other API-side errors — retryable
                last_error = LLMAPIError(f"status={e.status_code}, message={str(e)}")

            except LLMMalformedResponseError as e:
                # Retrying a malformed response occasionally helps (model
                # sometimes ignores tool_choice on a bad sample); still bounded.
                last_error = e

            if attempt < self._max_retries:
                time.sleep(min(2 ** attempt, 10))  # exponential backoff, capped

        raise last_error or LLMAPIError("LLM call failed for an unknown reason.")
