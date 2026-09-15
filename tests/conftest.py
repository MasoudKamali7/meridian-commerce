"""Shared pytest fixtures for Phase 3 tests.

`FakeLLMClient` is a test double implementing the same `LLMClient` interface
`AnthropicLLMClient` does — this is the whole point of the abstraction in
llm_client.py: tests never touch the real anthropic SDK or network.
"""

import logging

import pytest

from src.ai.llm_client import LLMClient, LLMClientError, LLMResponse


class FakeLLMClient(LLMClient):
    """Returns a pre-programmed response or raises a pre-programmed error,
    without making any real API call."""

    def __init__(self, response: LLMResponse = None, error: LLMClientError = None):
        self._response = response
        self._error = error
        self.call_count = 0

    def classify(self, system_prompt, user_prompt, tool_schema):
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return self._response


def make_response(tool_input: dict, input_tokens=50, output_tokens=20, latency_ms=250.0):
    return LLMResponse(
        tool_input=tool_input,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        raw_stop_reason="tool_use",
    )


@pytest.fixture
def silent_logger():
    logger = logging.getLogger("test_logger")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


VALID_TOOL_INPUT = {
    "category": "Refund Request",
    "priority": "Medium",
    "sentiment_score": -0.4,
    "order_id": None,
    "mentions_customer_info": False,
    "confidence": 0.87,
}
