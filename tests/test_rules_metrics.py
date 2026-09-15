"""
Unit tests for Phase 4's evaluation metrics — specifically the Phase 4.1
correction of the escalation_rate ambiguity into two clearly separated,
correctly-scoped metrics: human_review_rate and urgent_human_review_rate.

Every rate's numerator/denominator is checked explicitly, not just its
final value, so a future edit that silently changes the denominator (the
exact bug being fixed here) would be caught immediately.
"""

from src.evaluation.rules_metrics import compute_rules_evaluation, compute_rules_evaluation_from_db
from src.rules.engine import evaluate
from src.rules.models import TicketContext

CONF_THRESHOLD = 0.75
SENTIMENT_THRESHOLD = -0.7
ORDER_VALUE_THRESHOLD = 450.0


def _make_decisions():
    """6 tickets covering all combinations needed to distinguish
    human_review_rate from urgent_human_review_rate:
      - 2 Automated (not in either "human review" numerator)
      - 2 Human Review, Medium priority (in human_review_rate, NOT urgent)
      - 2 Human Review, High/Urgent priority (in BOTH numerators)
    """
    fixtures = [
        dict(ticket_id=1, ai_predicted_category="Order Status Inquiry",
             classification_confidence=0.95, sentiment_score=0.1),                    # Automated / Low
        dict(ticket_id=2, ai_predicted_category="Product Question",
             classification_confidence=0.9, sentiment_score=0.0),                     # Automated / Low
        dict(ticket_id=3, ai_predicted_category="Refund Request",
             classification_confidence=0.5, sentiment_score=0.0),                     # Human Review / Medium (low_confidence)
        dict(ticket_id=4, ai_predicted_category="Account Problem",
             classification_confidence=0.9, sentiment_score=0.0),                     # Human Review / Medium (sensitive_category)
        dict(ticket_id=5, ai_predicted_category="Payment Problem",
             classification_confidence=0.9, sentiment_score=0.0),                     # Human Review / High (sensitive_category)
        dict(ticket_id=6, ai_predicted_category="Complaint",
             classification_confidence=0.9, sentiment_score=-0.9),                    # Human Review / Urgent
    ]
    decisions = []
    contexts = {}
    for f in fixtures:
        ctx = TicketContext(**f)
        d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)
        decisions.append(d)
        contexts[d.ticket_id] = ctx
    return decisions, contexts


def test_human_review_rate_denominator_is_all_processed_tickets():
    decisions, contexts = _make_decisions()
    report = compute_rules_evaluation(decisions, CONF_THRESHOLD, contexts)

    assert report.n_processed == 6
    # 4 of 6 are Human Review (tickets 3, 4, 5, 6)
    assert report.human_review_rate == 4 / 6
    assert report.automated_rate == 2 / 6
    assert report.automated_rate + report.human_review_rate == 1.0


def test_urgent_human_review_rate_denominator_is_all_processed_not_just_human_reviewed():
    """The exact bug this test guards against: urgent_human_review_rate must
    be computed over ALL 6 tickets, not over the 4 that went to human
    review. Only tickets 5 (High) and 6 (Urgent) are HUMAN_REVIEW_URGENT."""
    decisions, contexts = _make_decisions()
    report = compute_rules_evaluation(decisions, CONF_THRESHOLD, contexts)

    assert report.urgent_human_review_rate == 2 / 6   # NOT 2/4
    assert report.urgent_human_review_rate != 2 / 4    # guards the old ambiguity explicitly


def test_urgent_human_review_rate_is_always_a_subset_of_human_review_rate():
    decisions, contexts = _make_decisions()
    report = compute_rules_evaluation(decisions, CONF_THRESHOLD, contexts)

    assert report.urgent_human_review_rate <= report.human_review_rate


def test_db_derived_urgent_human_review_rate_exactly_matches_in_memory_not_approximated():
    """Proves the Phase 4.1 fix: reconstructing recommended_action from just
    (decision_path, final_priority) via derive_recommended_action gives an
    EXACT match to the in-memory computation — not merely a close
    approximation — for the same underlying decisions."""
    decisions, contexts = _make_decisions()
    in_memory_report = compute_rules_evaluation(decisions, CONF_THRESHOLD, contexts)

    db_rows = [
        {"ticket_id": d.ticket_id, "decision_path": d.decision_path,
         "final_priority": d.final_priority,
         "ai_predicted_category": contexts[d.ticket_id].ai_predicted_category,
         "sentiment_score": contexts[d.ticket_id].sentiment_score,
         "classification_confidence": contexts[d.ticket_id].classification_confidence}
        for d in decisions
    ]
    db_report = compute_rules_evaluation_from_db(db_rows, CONF_THRESHOLD)

    assert db_report.urgent_human_review_rate == in_memory_report.urgent_human_review_rate
    assert db_report.human_review_rate == in_memory_report.human_review_rate
    assert db_report.automated_rate == in_memory_report.automated_rate


def test_db_derived_report_marks_rule_level_detail_as_not_available():
    decisions, contexts = _make_decisions()
    db_rows = [{"ticket_id": d.ticket_id, "decision_path": d.decision_path,
                "final_priority": d.final_priority, "ai_predicted_category": None,
                "sentiment_score": None, "classification_confidence": None}
               for d in decisions]

    report = compute_rules_evaluation_from_db(db_rows, CONF_THRESHOLD)

    assert report.rule_frequency is None
    assert report.multi_rule_frequency is None
    assert report.conflict_frequency is None
    assert report.fallback_frequency is None
    assert any("NOT AVAILABLE" in note for note in report.notes)


def test_empty_input_returns_none_rates_not_division_by_zero():
    report = compute_rules_evaluation([], CONF_THRESHOLD)
    assert report.n_processed == 0
    assert report.automated_rate is None
    assert report.human_review_rate is None
    assert report.urgent_human_review_rate is None

    db_report = compute_rules_evaluation_from_db([], CONF_THRESHOLD)
    assert db_report.n_processed == 0
    assert db_report.urgent_human_review_rate is None


def test_provenance_label_defaults_to_real_and_can_be_overridden():
    decisions, contexts = _make_decisions()

    default_report = compute_rules_evaluation(decisions, CONF_THRESHOLD, contexts)
    assert default_report.metric_provenance == "REAL (in-memory batch run)"

    simulated_report = compute_rules_evaluation(
        decisions, CONF_THRESHOLD, contexts,
        provenance_label="SIMULATED (fixture data, not real tickets)",
    )
    assert simulated_report.metric_provenance == "SIMULATED (fixture data, not real tickets)"

    db_report = compute_rules_evaluation_from_db(
        [{"ticket_id": 1, "decision_path": "Automated", "final_priority": "Low",
          "ai_predicted_category": None, "sentiment_score": None, "classification_confidence": None}],
        CONF_THRESHOLD,
    )
    assert db_report.metric_provenance == "REAL (derived from database)"


def test_all_automated_gives_zero_human_review_and_zero_urgent_rate():
    ctx = TicketContext(ticket_id=1, ai_predicted_category="Order Status Inquiry",
                         classification_confidence=0.95, sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)
    report = compute_rules_evaluation([d], CONF_THRESHOLD, {1: ctx})

    assert report.human_review_rate == 0.0
    assert report.urgent_human_review_rate == 0.0
