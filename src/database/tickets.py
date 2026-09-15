"""
Meridian Commerce — Phase 3/4: Ticket Database Operations

Design decisions made explicit here (see PHASE3_SUMMARY.md and
PHASE4_SUMMARY.md for full reasoning):

1. `update_ticket_classification()` (Phase 3) writes ONLY: ai_predicted_category,
   classification_confidence, sentiment_score, decision_at. It never touches
   category, created_at, customer_id, order_id, or any other original field.

2. It also does NOT touch `status`. These 1,500 tickets are historical/closed
   records being retroactively evaluated, not live tickets moving through an
   operational pipeline for the first time — flipping an already-`Closed`
   ticket's status to `Classified` would misrepresent its real lifecycle.

3. The AI's raw `priority` prediction (Phase 3) is intentionally NOT written
   anywhere in the database — see the priority design decision in
   PHASE3_SUMMARY.md. It's captured only in the classification log, never
   persisted to the ticket record itself.

4. `update_phase4_decision()` (Phase 4) writes ONLY: final_priority,
   decision_path, rule_decision_at. It never touches category, priority,
   ai_predicted_category, created_at, customer_id, order_id, status,
   resolution_type, or any Phase 3 field — see PHASE4_SUMMARY.md.
"""

from typing import Optional

from .connection import get_cursor


def fetch_ticket_batch(conn, limit: int, only_unclassified: bool = True) -> list:
    """Fetch a batch of historical tickets to run through the classifier.
    Returns dicts with ticket_id, message_text, and the ground-truth category
    (needed later for evaluation — never sent to the LLM)."""
    where_clause = "WHERE ai_predicted_category IS NULL" if only_unclassified else ""
    query = f"""
        SELECT ticket_id, message_text, category AS ground_truth_category
        FROM tickets
        {where_clause}
        ORDER BY ticket_id
        LIMIT %s;
    """
    with get_cursor(conn) as cur:
        cur.execute(query, (limit,))
        return cur.fetchall()


def update_ticket_classification(conn, ticket_id: int, category: str,
                                  confidence: float, sentiment_score: float) -> None:
    """Writes only the AI-derived fields. Never touches category, created_at,
    customer_id, order_id, status, or decision_path (see module docstring)."""
    query = """
        UPDATE tickets
        SET ai_predicted_category = %s,
            classification_confidence = %s,
            sentiment_score = %s,
            decision_at = now()
        WHERE ticket_id = %s;
    """
    with get_cursor(conn) as cur:
        cur.execute(query, (category, confidence, sentiment_score, ticket_id))
    conn.commit()


def fetch_evaluation_data(conn) -> list:
    """Fetch every ticket that has BOTH a ground-truth category and an
    AI-predicted category, for computing evaluation metrics."""
    query = """
        SELECT ticket_id, category AS ground_truth_category, ai_predicted_category,
               classification_confidence
        FROM tickets
        WHERE ai_predicted_category IS NOT NULL
        ORDER BY ticket_id;
    """
    with get_cursor(conn) as cur:
        cur.execute(query)
        return cur.fetchall()


def count_classified(conn) -> int:
    with get_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tickets WHERE ai_predicted_category IS NOT NULL;")
        return cur.fetchone()["n"]


# ----------------------------------------------------------------------------
# Phase 4: Business-rule engine support
# ----------------------------------------------------------------------------

def fetch_tickets_for_rules(conn, limit: int, only_undecided: bool = True) -> list:
    """Fetch tickets joined with the order/customer context the rule engine
    needs (order_value, customer_segment). LEFT JOINs so tickets with no
    linked order still come back (order_value/customer_segment as NULL,
    correctly signaling 'no order context available' to the engine).

    Deliberately does NOT select tickets.priority (historical ground truth)
    or any LLM-guessed priority — the engine never sees either, by design.
    """
    where_clause = "WHERE t.decision_path IS NULL" if only_undecided else ""
    query = f"""
        SELECT t.ticket_id, t.ai_predicted_category, t.classification_confidence,
               t.sentiment_score, t.order_id, o.total_amount AS order_value,
               c.customer_segment
        FROM tickets t
        JOIN customers c ON t.customer_id = c.customer_id
        LEFT JOIN orders o ON t.order_id = o.order_id
        {where_clause}
        ORDER BY t.ticket_id
        LIMIT %s;
    """
    with get_cursor(conn) as cur:
        cur.execute(query, (limit,))
        rows = cur.fetchall()
    # order_value comes back as Decimal from psycopg2 — the rule engine's
    # Pydantic model expects a plain float.
    for row in rows:
        if row["order_value"] is not None:
            row["order_value"] = float(row["order_value"])
    return rows


def update_phase4_decision(conn, ticket_id: int, final_priority: str, decision_path: str) -> None:
    """Writes ONLY the three Phase 4 fields: final_priority, decision_path,
    rule_decision_at. Never touches category, ai_predicted_category,
    priority, created_at, customer_id, order_id, status, resolution_type, or
    any other field — see PHASE4_SUMMARY.md for why each of those stays
    untouched."""
    query = """
        UPDATE tickets
        SET final_priority = %s,
            decision_path = %s,
            rule_decision_at = now()
        WHERE ticket_id = %s;
    """
    with get_cursor(conn) as cur:
        cur.execute(query, (final_priority, decision_path, ticket_id))
    conn.commit()


def count_phase4_decided(conn) -> int:
    with get_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tickets WHERE decision_path IS NOT NULL;")
        return cur.fetchone()["n"]


def fetch_phase4_results(conn) -> list:
    """All tickets with a Phase 4 decision, plus enough context (category,
    sentiment, confidence) to build the evaluation breakdowns Phase 4's
    report requires."""
    query = """
        SELECT ticket_id, ai_predicted_category, classification_confidence,
               sentiment_score, final_priority, decision_path
        FROM tickets
        WHERE decision_path IS NOT NULL
        ORDER BY ticket_id;
    """
    with get_cursor(conn) as cur:
        cur.execute(query)
        return cur.fetchall()
