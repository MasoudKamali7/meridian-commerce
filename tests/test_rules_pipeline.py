"""
Unit tests for the Phase 4 `rules_batch` control flow — the dry-run
guarantee and live-mode write behavior, mirroring the equivalent Phase 3
tests in test_pipeline.py exactly (same safety property, same test shape).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.pipeline import rules_batch


@pytest.fixture
def logger():
    log = logging.getLogger("test_rules_pipeline")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    return log


@pytest.fixture
def config():
    return Config(low_confidence_threshold=0.75, strong_negative_sentiment_threshold=-0.7,
                  high_value_order_threshold=450.0)


SAMPLE_ROWS = [
    {"ticket_id": 1, "ai_predicted_category": "Order Status Inquiry", "classification_confidence": 0.95,
     "sentiment_score": 0.1, "order_id": 10, "order_value": 50.0, "customer_segment": "Returning"},
    {"ticket_id": 2, "ai_predicted_category": "Payment Problem", "classification_confidence": 0.9,
     "sentiment_score": -0.2, "order_id": 11, "order_value": 80.0, "customer_segment": "New"},
]


@patch("src.pipeline.update_phase4_decision")
def test_dry_run_never_writes_to_database(mock_update, config, logger):
    fake_conn = MagicMock()

    summary, decisions, contexts = rules_batch(fake_conn, SAMPLE_ROWS, dry_run=True,
                                                logger=logger, config=config)

    assert summary["tickets_processed"] == 2
    mock_update.assert_not_called()  # <-- the critical dry-run guarantee
    assert len(decisions) == 2


@patch("src.pipeline.update_phase4_decision")
def test_live_run_writes_every_decision(mock_update, config, logger):
    fake_conn = MagicMock()

    summary, decisions, contexts = rules_batch(fake_conn, SAMPLE_ROWS, dry_run=False,
                                                logger=logger, config=config)

    assert mock_update.call_count == 2
    # ticket 1: clean/safe -> Automated; ticket 2: Payment Problem -> Human Review
    assert summary["n_automated"] == 1
    assert summary["n_human_review"] == 1


@patch("src.pipeline.update_phase4_decision")
def test_live_run_passes_the_engines_own_decision_to_the_database_write(mock_update, config, logger):
    fake_conn = MagicMock()

    rules_batch(fake_conn, [SAMPLE_ROWS[1]], dry_run=False, logger=logger, config=config)

    _, kwargs = mock_update.call_args
    assert kwargs["ticket_id"] == 2
    assert kwargs["decision_path"] == "Human Review"  # Payment Problem is sensitive
    assert kwargs["final_priority"] == "High"          # base priority for Payment Problem


@patch("src.pipeline.update_phase4_decision")
def test_fallback_decisions_still_get_written_live_but_never_in_dry_run(mock_update, config, logger):
    """A fallback decision is still a valid Decision (Human Review, Medium) —
    it should be written like any other live decision. It must simply never
    be written during a dry run."""
    bad_row = [{"ticket_id": 3, "classification_confidence": 5.0}]  # invalid -> fallback

    summary_dry, decisions_dry, _ = rules_batch(fake_conn := MagicMock(), bad_row, dry_run=True,
                                                 logger=logger, config=config)
    assert decisions_dry[0].is_fallback is True
    mock_update.assert_not_called()

    mock_update.reset_mock()
    summary_live, decisions_live, _ = rules_batch(fake_conn, bad_row, dry_run=False,
                                                   logger=logger, config=config)
    assert decisions_live[0].is_fallback is True
    mock_update.assert_called_once()
    _, kwargs = mock_update.call_args
    assert kwargs["decision_path"] == "Human Review"
