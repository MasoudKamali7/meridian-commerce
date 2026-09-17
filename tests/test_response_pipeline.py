"""
Unit tests for Phase 5's pipeline batch loop and database operations —
the dry-run guarantee, live-write field safety, and query correctness.
Mirrors the shape of the equivalent Phase 3 and Phase 4 test files.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.database import tickets
from src.pipeline import response_batch


@pytest.fixture
def logger():
    log = logging.getLogger("test_response_pipeline")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    return log


@pytest.fixture
def config():
    return Config(low_confidence_threshold=0.75, strong_negative_sentiment_threshold=-0.7,
                  generate_internal_drafts=True)


SAMPLE_ROWS = [
    # Phase 4 said Automated, clean -> would be eligible (BLOCKED here: no generator)
    {"ticket_id": 1, "message_text": "Where is my order?", "ai_predicted_category": "Order Status Inquiry",
     "classification_confidence": 0.95, "sentiment_score": 0.1, "decision_path": "Automated",
     "final_priority": "Low", "order_id": 10, "order_status": "Shipped",
     "expected_delivery_date": "2026-01-10", "actual_delivery_date": None,
     "customer_segment": "Returning", "product_names": "Yoga Mat"},
    # Phase 4 said Human Review
    {"ticket_id": 2, "message_text": "I want to complain.", "ai_predicted_category": "Complaint",
     "classification_confidence": 0.9, "sentiment_score": -0.5, "decision_path": "Human Review",
     "final_priority": "Urgent", "order_id": None, "order_status": None,
     "expected_delivery_date": None, "actual_delivery_date": None,
     "customer_segment": "New", "product_names": None},
    # Phase 4 hasn't decided yet
    {"ticket_id": 3, "message_text": "Hello?", "ai_predicted_category": None,
     "classification_confidence": None, "sentiment_score": None, "decision_path": None,
     "final_priority": None, "order_id": None, "order_status": None,
     "expected_delivery_date": None, "actual_delivery_date": None,
     "customer_segment": "VIP", "product_names": None},
]


# ----------------------------------------------------------------------------
# Dry-run / live safety
# ----------------------------------------------------------------------------
@patch("src.pipeline.update_phase5_response")
def test_dry_run_never_writes_to_database(mock_update, config, logger):
    fake_conn = MagicMock()

    summary, decisions = response_batch(fake_conn, SAMPLE_ROWS, dry_run=True,
                                         logger=logger, config=config, generator=None)

    assert summary["tickets_processed"] == 3
    mock_update.assert_not_called()   # the critical dry-run guarantee


@patch("src.pipeline.update_phase5_response")
def test_live_run_writes_every_decision(mock_update, config, logger):
    fake_conn = MagicMock()

    summary, decisions = response_batch(fake_conn, SAMPLE_ROWS, dry_run=False,
                                         logger=logger, config=config, generator=None)

    assert mock_update.call_count == 3
    assert summary["n_not_eligible"] == 1        # ticket 3, no Phase 4 decision
    assert summary["n_human_review_draft"] == 1   # ticket 2
    assert summary["n_blocked"] == 1              # ticket 1 (eligible but no generator)


@patch("src.pipeline.update_phase5_response")
def test_live_write_passes_only_phase5_owned_values(mock_update, config, logger):
    fake_conn = MagicMock()

    response_batch(fake_conn, [SAMPLE_ROWS[1]], dry_run=False,
                    logger=logger, config=config, generator=None)

    _, kwargs = mock_update.call_args
    assert set(kwargs.keys()) == {"ticket_id", "response_status", "response_type", "response_draft"}
    assert kwargs["response_status"] == "HUMAN_REVIEW_DRAFT"
    assert kwargs["response_type"] == "COMPLAINT"


# ----------------------------------------------------------------------------
# Database operations (mocked cursor)
# ----------------------------------------------------------------------------
def make_mock_conn(fetchall_return=None, fetchone_return=None):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = fetchall_return or []
    mock_cursor.fetchone.return_value = fetchone_return
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_update_phase5_response_writes_only_phase5_columns_and_commits():
    mock_conn, mock_cursor = make_mock_conn()

    tickets.update_phase5_response(mock_conn, ticket_id=7, response_status="DRAFT_GENERATED",
                                    response_type="ORDER_STATUS", response_draft="Hello.")

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "UPDATE tickets" in executed_sql
    assert "SET response_status" in executed_sql
    assert "response_generated_at = now()" in executed_sql

    # Every Phase 1-4 field must be absent. Strip the legitimate response_*
    # column names first so this can't false-positive on substrings
    # (the same class of test bug found and fixed in Phase 4.1).
    stripped = executed_sql
    for legit in ("response_status", "response_type", "response_draft", "response_generated_at"):
        stripped = stripped.replace(legit, "")
    for protected in ("category", "ai_predicted_category", "classification_confidence",
                       "sentiment_score", "decision_path", "final_priority", "rule_decision_at",
                       "priority", "created_at", "customer_id", "order_id", "status",
                       "message_text"):
        assert protected not in stripped, f"'{protected}' must not appear in the Phase 5 UPDATE"

    assert params == ("DRAFT_GENERATED", "ORDER_STATUS", "Hello.", 7)
    mock_conn.commit.assert_called_once()


def test_fetch_tickets_for_response_filters_unprocessed_and_excludes_pii():
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[])

    tickets.fetch_tickets_for_response(mock_conn, limit=5)

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "WHERE t.response_status IS NULL" in executed_sql
    assert "LEFT JOIN orders" in executed_sql   # tickets with no order still come back
    assert params == (5,)
    # PII / unnecessary fields must not be selected at all
    for forbidden in ("first_name", "last_name", "email", "phone", "payment_method", "total_amount"):
        assert forbidden not in executed_sql, f"'{forbidden}' must not be queried by Phase 5"


def test_fetch_phase5_results_does_not_select_draft_text():
    """Evaluation reports counts and distributions — never draft contents."""
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[])

    tickets.fetch_phase5_results(mock_conn)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "response_draft IS NOT NULL" in executed_sql   # only presence, as a boolean
    assert "SELECT ticket_id" in executed_sql


def test_count_phase5_processed_queries_response_status():
    mock_conn, mock_cursor = make_mock_conn(fetchone_return={"n": 4})

    count = tickets.count_phase5_processed(mock_conn)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "response_status IS NOT NULL" in executed_sql
    assert count == 4
