"""
Unit tests for the classify_batch() control flow — specifically the dry-run
guarantee (Phase 3 requirement: dry run must call the AI and validate the
output, but must NEVER write to the database) and correct handling of a
mixed batch of successes and failures.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import classify_batch

from .conftest import VALID_TOOL_INPUT, FakeLLMClient, make_response
from src.ai.classifier import TicketClassifier
from src.ai.llm_client import LLMTimeoutError


@pytest.fixture
def logger():
    log = logging.getLogger("test_pipeline")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    return log


SAMPLE_TICKETS = [
    {"ticket_id": 101, "message_text": "I need a refund.", "ground_truth_category": "Refund Request"},
    {"ticket_id": 102, "message_text": "Where is my order?", "ground_truth_category": "Order Status Inquiry"},
]


@patch("src.pipeline.update_ticket_classification")
def test_dry_run_never_writes_to_database(mock_update, logger):
    client = FakeLLMClient(response=make_response(VALID_TOOL_INPUT))
    classifier = TicketClassifier(client)
    fake_conn = MagicMock()

    summary = classify_batch(fake_conn, classifier, SAMPLE_TICKETS, dry_run=True, logger=logger)

    assert summary["n_success"] == 2
    assert summary["n_failed"] == 0
    mock_update.assert_not_called()  # <-- the critical dry-run guarantee


@patch("src.pipeline.update_ticket_classification")
def test_live_run_writes_successful_classifications(mock_update, logger):
    client = FakeLLMClient(response=make_response(VALID_TOOL_INPUT))
    classifier = TicketClassifier(client)
    fake_conn = MagicMock()

    summary = classify_batch(fake_conn, classifier, SAMPLE_TICKETS, dry_run=False, logger=logger)

    assert summary["n_success"] == 2
    assert mock_update.call_count == 2
    # Confirm it's called with the validated (not raw) fields
    _, kwargs = mock_update.call_args
    assert kwargs["category"] == "Refund Request"
    assert kwargs["confidence"] == 0.87


@patch("src.pipeline.update_ticket_classification")
def test_failed_classification_never_triggers_a_database_write(mock_update, logger):
    """A failed AI prediction must not corrupt the original ticket — i.e.
    no UPDATE should be issued for tickets that failed classification,
    even in live mode."""
    client = FakeLLMClient(error=LLMTimeoutError("timed out"))
    classifier = TicketClassifier(client)
    fake_conn = MagicMock()

    summary = classify_batch(fake_conn, classifier, SAMPLE_TICKETS, dry_run=False, logger=logger)

    assert summary["n_success"] == 0
    assert summary["n_failed"] == 2
    assert summary["failures_by_type"] == {"timeout": 2}
    mock_update.assert_not_called()


@patch("src.pipeline.update_ticket_classification")
def test_mixed_batch_only_writes_the_successful_ones(mock_update, logger):
    """One ticket classifies successfully, one fails — only the successful
    one should reach the database."""
    call_sequence = [make_response(VALID_TOOL_INPUT), None]

    class SequencedFakeClient:
        def __init__(self):
            self.calls = 0

        def classify(self, system_prompt, user_prompt, tool_schema):
            self.calls += 1
            if self.calls == 1:
                return call_sequence[0]
            raise LLMTimeoutError("timed out on 2nd ticket")

    classifier = TicketClassifier(SequencedFakeClient())
    fake_conn = MagicMock()

    summary = classify_batch(fake_conn, classifier, SAMPLE_TICKETS, dry_run=False, logger=logger)

    assert summary["n_success"] == 1
    assert summary["n_failed"] == 1
    assert mock_update.call_count == 1
