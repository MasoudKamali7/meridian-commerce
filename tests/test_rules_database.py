"""
Unit tests for Phase 4's database operations — verified against a mocked
psycopg2 connection/cursor (the same real functions were also exercised
against the live Phase 2/3 database — see PHASE4_SUMMARY.md).
"""

from unittest.mock import MagicMock

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


def test_update_phase4_decision_writes_only_phase4_fields_and_commits():
    mock_conn, mock_cursor = make_mock_conn()

    tickets.update_phase4_decision(mock_conn, ticket_id=7, final_priority="High",
                                    decision_path="Automated")

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "UPDATE tickets" in executed_sql
    assert "SET final_priority" in executed_sql
    assert "decision_path" in executed_sql
    assert "rule_decision_at = now()" in executed_sql
    # Guarantee every protected field is absent from this query. Strip out
    # the legitimate "final_priority" occurrence first so this check can't
    # false-positive on "priority" being a substring of "final_priority".
    sql_without_final_priority = executed_sql.replace("final_priority", "")
    for protected in ("category", "ai_predicted_category", "priority",
                       "created_at", "customer_id", "order_id", "status",
                       "resolution_type", "classification_confidence", "sentiment_score"):
        assert protected not in sql_without_final_priority, f"'{protected}' must not appear in the Phase 4 UPDATE"

    assert params == ("High", "Automated", 7)
    mock_conn.commit.assert_called_once()


def test_fetch_tickets_for_rules_filters_undecided_by_default():
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[
        {"ticket_id": 1, "ai_predicted_category": None, "classification_confidence": None,
         "sentiment_score": None, "order_id": None, "order_value": None, "customer_segment": "New"}
    ])

    result = tickets.fetch_tickets_for_rules(mock_conn, limit=5)

    executed_sql, params = mock_cursor.execute.call_args[0]
    assert "WHERE t.decision_path IS NULL" in executed_sql
    assert "LEFT JOIN orders" in executed_sql  # tickets with no order must still come back
    assert params == (5,)
    assert len(result) == 1


def test_fetch_tickets_for_rules_converts_decimal_order_value_to_float():
    from decimal import Decimal
    mock_conn, mock_cursor = make_mock_conn(fetchall_return=[
        {"ticket_id": 1, "ai_predicted_category": "Refund Request", "classification_confidence": 0.9,
         "sentiment_score": 0.0, "order_id": 5, "order_value": Decimal("123.45"),
         "customer_segment": "VIP"}
    ])

    result = tickets.fetch_tickets_for_rules(mock_conn, limit=5)

    assert isinstance(result[0]["order_value"], float)
    assert result[0]["order_value"] == 123.45


def test_count_phase4_decided_queries_decision_path():
    mock_conn, mock_cursor = make_mock_conn(fetchone_return={"n": 3})

    count = tickets.count_phase4_decided(mock_conn)

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert "decision_path IS NOT NULL" in executed_sql
    assert count == 3
