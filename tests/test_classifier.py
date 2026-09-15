"""
Unit tests for TicketClassifier / ValidatedClassification.

These test the validation gate directly — the part of the system
responsible for never trusting raw LLM output. No real API calls are made;
FakeLLMClient (see conftest.py) stands in for the network boundary.
"""

import copy

from src.ai.classifier import TicketClassifier
from src.ai.llm_client import LLMMalformedResponseError, LLMTimeoutError

from .conftest import VALID_TOOL_INPUT, FakeLLMClient, make_response


def test_valid_structured_response_succeeds():
    client = FakeLLMClient(response=make_response(VALID_TOOL_INPUT))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=1, message_text="I want a refund please.")

    assert result.success is True
    assert result.validated.category == "Refund Request"
    assert result.validated.priority == "Medium"
    assert result.error_type is None
    assert client.call_count == 1


def test_invalid_category_is_rejected():
    bad_input = copy.deepcopy(VALID_TOOL_INPUT)
    bad_input["category"] = "Not A Real Category"
    client = FakeLLMClient(response=make_response(bad_input))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=2, message_text="test")

    assert result.success is False
    assert result.error_type == "invalid_category"
    assert result.validated is None


def test_invalid_priority_is_rejected():
    bad_input = copy.deepcopy(VALID_TOOL_INPUT)
    bad_input["priority"] = "SuperUrgent"  # not in APPROVED_PRIORITIES
    client = FakeLLMClient(response=make_response(bad_input))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=3, message_text="test")

    assert result.success is False
    assert result.error_type == "invalid_priority"


def test_malformed_response_is_marked_failed_not_raised():
    """If the LLM client can't find a valid tool_use block, that surfaces as
    an LLMClientError from the client layer — the classifier must catch it
    and return a failed result, not propagate an exception."""
    client = FakeLLMClient(error=LLMMalformedResponseError("no tool_use block found"))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=4, message_text="test")

    assert result.success is False
    assert result.error_type == "malformed_response"
    assert result.validated is None


def test_missing_required_field_is_rejected():
    bad_input = copy.deepcopy(VALID_TOOL_INPUT)
    del bad_input["confidence"]  # required field
    client = FakeLLMClient(response=make_response(bad_input))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=5, message_text="test")

    assert result.success is False
    assert result.error_type == "invalid_response_schema"


def test_out_of_range_sentiment_is_rejected():
    bad_input = copy.deepcopy(VALID_TOOL_INPUT)
    bad_input["sentiment_score"] = 5.0  # outside [-1, 1]
    client = FakeLLMClient(response=make_response(bad_input))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=6, message_text="test")

    assert result.success is False
    assert result.error_type == "invalid_response_schema"


def test_timeout_error_is_marked_failed_not_raised():
    client = FakeLLMClient(error=LLMTimeoutError("request timed out"))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=7, message_text="test")

    assert result.success is False
    assert result.error_type == "timeout"


def test_order_id_extraction_when_present():
    with_order = copy.deepcopy(VALID_TOOL_INPUT)
    with_order["order_id"] = 54821
    client = FakeLLMClient(response=make_response(with_order))
    classifier = TicketClassifier(client)

    result = classifier.classify(ticket_id=8, message_text="Regarding order #54821")

    assert result.success is True
    assert result.validated.order_id == 54821
