"""
Unit tests for src/database/tickets.py — verified against a mocked psycopg2
connection/cursor (no real database needed for these, though the same code
was also exercised against the real Phase 2 database — see PHASE3_SUMMARY.md).
"""

from unittest.mock import MagicMock, patch

from src.database import tickets


def make_mock_conn(fetchall_return=None, fetchone_return=None):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = fetchall_return or []
    mock_cursor.fetchone.return_value = fetchone_return
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_update_ticket_classification_writes_only_ai_fields_and_commits():
    mock_conn, mock_cursor = make_mock_conn()

    with patch("src.database.connection.psycopg2.extras.RealDictCursor", None):
        tickets.update_ticket_classification(
            mock_conn, ticket_id=42, category="Refund Request",
            confidence=0.9, sentiment_score=-0.3,
        )

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "UPDATE tickets" in executed_sql
    assert "SET ai_predicted_category" in executed_sql
    assert "classification_confidence" in executed_sql
    assert "sentiment_score" in executed_sql
    assert "decision_at = now()" in executed_sql
    # Guarantee the protected fields are never touched by this query
    assert "category =" not in executed_sql.replace("ai_predicted_category", "")
    assert "created_at" not in executed_sql
    assert "customer_id" not in executed_sql
    assert "order_id" not in executed_sql
    assert "status" not in executed_sql
    assert "decision_path" not in executed_sql

    assert params == ("Refund Request", 0.9, -0.3, 42)
    mock_conn.commit.assert_called_once()


def test_fetch_ticket_batch_filters_unclassified_by_default():
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[
        {"ticket_id": 1, "message_text": "hi", "ground_truth_category": "Other"}
    ])

    result = tickets.fetch_ticket_batch(mock_conn, limit=10)

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "WHERE ai_predicted_category IS NULL" in executed_sql
    assert params == (10,)
    assert len(result) == 1


def test_fetch_evaluation_data_only_returns_classified_tickets():
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[])

    tickets.fetch_evaluation_data(mock_conn)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "WHERE ai_predicted_category IS NOT NULL" in executed_sql
