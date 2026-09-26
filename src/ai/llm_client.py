"""
Meridian Commerce — Phase 3: LLM Client

Isolates all direct contact with the LLM provider's API behind a small
interface (`LLMClient`), so `classifier.py` never imports the provider
package directly.

OpenRouter uses an OpenAI-compatible API, so the rest of the application
does not need to know which provider is being used.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
    OpenAI,
)


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


class LLMClientError(Exception):
    """Base class for all LLM client errors."""

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
    """Raised when the API response does not contain valid structured output."""

    error_type = "malformed_response"


# ----------------------------------------------------------------------------
# Abstract interface
# ----------------------------------------------------------------------------

class LLMClient(ABC):

    @abstractmethod
    def classify(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_schema: dict,
    ) -> LLMResponse:
        """
        Call the model with a structured-output request and return the raw
        structured output plus usage/timing metadata.
        """
        raise NotImplementedError


# ----------------------------------------------------------------------------
# OpenRouter implementation
# ----------------------------------------------------------------------------

class OpenRouterLLMClient(LLMClient):

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ):
        if not api_key:
            raise LLMAuthError(
                "No API key provided to OpenRouterLLMClient."
            )

        self._client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout_seconds,
            max_retries=0,
        )

        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries

    def classify(
        self,
        system_prompt: str,
        user_prompt: str,
        tool_schema: dict,
    ) -> LLMResponse:

        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()

            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": tool_schema["name"],
                                "description": tool_schema.get(
                                    "description",
                                    "",
                                ),
                                "parameters": tool_schema["input_schema"],
                            },
                        }
                    ],
                    tool_choice={
                        "type": "function",
                        "function": {
                            "name": tool_schema["name"],
                        },
                    },
                )

                latency_ms = (time.monotonic() - start) * 1000

                if not response.choices:
                    raise LLMMalformedResponseError(
                        "OpenRouter returned no choices."
                    )

                message = response.choices[0].message

                tool_calls = message.tool_calls or []

                tool_call = next(
                    (
                        call
                        for call in tool_calls
                        if getattr(call.function, "name", None)
                        == tool_schema["name"]
                    ),
                    None,
                )

                if tool_call is None:
                    raise LLMMalformedResponseError(
                        f"No '{tool_schema['name']}' tool call in response."
                    )

                arguments = tool_call.function.arguments

                if not arguments:
                    raise LLMMalformedResponseError(
                        f"Tool call '{tool_schema['name']}' "
                        "contained no arguments."
                    )

                import json

                try:
                    tool_input = json.loads(arguments)
                except (TypeError, json.JSONDecodeError) as e:
                    raise LLMMalformedResponseError(
                        f"Tool call arguments were not valid JSON: {e}"
                    ) from e

                if not isinstance(tool_input, dict):
                    raise LLMMalformedResponseError(
                        "Tool call arguments must decode to a JSON object."
                    )

                usage = response.usage

                input_tokens = (
                    getattr(usage, "prompt_tokens", 0)
                    if usage
                    else 0
                )

                output_tokens = (
                    getattr(usage, "completion_tokens", 0)
                    if usage
                    else 0
                )

                finish_reason = (
                    response.choices[0].finish_reason
                    or "unknown"
                )

                return LLMResponse(
                    tool_input=tool_input,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    raw_stop_reason=finish_reason,
                )

            except AuthenticationError as e:
                # Credentials are invalid. Retrying will not help.
                raise LLMAuthError(str(e)) from e

            except APITimeoutError as e:
                last_error = LLMTimeoutError(str(e))

            except RateLimitError as e:
                last_error = LLMRateLimitError(str(e))

            except APIConnectionError as e:
                last_error = LLMAPIError(
                    f"OpenRouter connection error: {str(e)}"
                )

            except APIStatusError as e:
                last_error = LLMAPIError(
                    f"status={e.status_code}, message={str(e)}"
                )

            except LLMMalformedResponseError as e:
                last_error = e

            if attempt < self._max_retries:
                time.sleep(min(2 ** attempt, 10))

        raise last_error or LLMAPIError(
            "LLM call failed for an unknown reason."
        )