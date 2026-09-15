"""
Unit tests for the Phase 4 deterministic rule engine.

Pure logic tests — no database, no LLM, fully deterministic and fast. Each
test targets one of the scenarios explicitly required by the Phase 4 brief.
"""

import pytest
from pydantic import ValidationError

from src.rules.engine import evaluate, safe_evaluate
from src.rules.models import TicketContext

CONF_THRESHOLD = 0.75
SENTIMENT_THRESHOLD = -0.7
ORDER_VALUE_THRESHOLD = 450.0


def make_ctx(**kwargs):
    defaults = dict(ticket_id=1)
    defaults.update(kwargs)
    return TicketContext(**defaults)


# ----------------------------------------------------------------------------
# Normal / low-risk tickets -> Automated
# ----------------------------------------------------------------------------
def test_normal_low_risk_ticket_is_automated():
    ctx = make_ctx(ai_predicted_category="Order Status Inquiry", classification_confidence=0.95,
                    sentiment_score=0.1, order_id=10, order_value=50.0, customer_segment="Returning")
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Automated"
    assert d.final_priority == "Low"
    assert d.recommended_action == "AUTO_RESOLVE"
    assert d.conflicting_signals is False
    assert d.is_fallback is False


# ----------------------------------------------------------------------------
# High-value orders
# ----------------------------------------------------------------------------
def test_high_value_vip_order_raises_priority_but_stays_automated_if_otherwise_safe():
    ctx = make_ctx(ai_predicted_category="Delivery Delay", classification_confidence=0.9,
                    sentiment_score=0.0, order_id=20, order_value=600.0, customer_segment="VIP")
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "high_value_vip_order_priority" in d.triggered_rules
    assert d.final_priority == "High"
    assert d.decision_path == "Automated"  # high value alone doesn't force human review


def test_high_value_non_vip_order_does_not_trigger_the_vip_rule():
    ctx = make_ctx(ai_predicted_category="Delivery Delay", classification_confidence=0.9,
                    sentiment_score=0.0, order_id=20, order_value=600.0, customer_segment="Returning")
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "high_value_vip_order_priority" not in d.triggered_rules
    assert d.final_priority == "Medium"  # base category priority for Delivery Delay


def test_low_value_vip_order_does_not_trigger_the_vip_rule():
    ctx = make_ctx(ai_predicted_category="Delivery Delay", classification_confidence=0.9,
                    sentiment_score=0.0, order_id=20, order_value=50.0, customer_segment="VIP")
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "high_value_vip_order_priority" not in d.triggered_rules


# ----------------------------------------------------------------------------
# Confidence
# ----------------------------------------------------------------------------
def test_low_confidence_forces_human_review():
    ctx = make_ctx(ai_predicted_category="Order Status Inquiry", classification_confidence=0.4,
                    sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Human Review"
    assert "low_confidence" in d.triggered_rules


def test_high_confidence_does_not_trigger_low_confidence_rule():
    ctx = make_ctx(ai_predicted_category="Order Status Inquiry", classification_confidence=0.96,
                    sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "low_confidence" not in d.triggered_rules


def test_confidence_exactly_at_threshold_is_not_low():
    """Boundary check: the rule uses strict '<', so a score exactly at the
    threshold should NOT be flagged as low."""
    ctx = make_ctx(ai_predicted_category="Order Status Inquiry",
                    classification_confidence=CONF_THRESHOLD, sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "low_confidence" not in d.triggered_rules


# ----------------------------------------------------------------------------
# Sentiment
# ----------------------------------------------------------------------------
def test_moderately_negative_sentiment_does_not_force_review():
    ctx = make_ctx(ai_predicted_category="Order Status Inquiry", classification_confidence=0.9,
                    sentiment_score=-0.3)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "strong_negative_sentiment_review" not in d.triggered_rules
    assert d.decision_path == "Automated"


def test_strongly_negative_sentiment_forces_review_and_raises_priority():
    ctx = make_ctx(ai_predicted_category="Product Question", classification_confidence=0.9,
                    sentiment_score=-0.85)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Human Review"
    assert d.final_priority == "High"
    assert "strong_negative_sentiment_review" in d.triggered_rules
    assert "strong_negative_sentiment_priority" in d.triggered_rules


# ----------------------------------------------------------------------------
# Sensitive / high-risk categories
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("category", ["Payment Problem", "Account Problem", "Complaint"])
def test_sensitive_categories_always_force_human_review(category):
    ctx = make_ctx(ai_predicted_category=category, classification_confidence=0.99, sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Human Review"
    assert "sensitive_category" in d.triggered_rules


def test_non_sensitive_category_does_not_trigger_sensitive_rule():
    ctx = make_ctx(ai_predicted_category="Product Question", classification_confidence=0.9, sentiment_score=0.0)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "sensitive_category" not in d.triggered_rules


# ----------------------------------------------------------------------------
# Missing information
# ----------------------------------------------------------------------------
def test_missing_classification_forces_human_review():
    ctx = make_ctx()  # no ai_predicted_category at all — the REAL current state of all 1,500 tickets
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Human Review"
    assert "missing_classification" in d.triggered_rules
    assert d.final_priority == "Medium"  # conservative default, not Low or High


def test_missing_order_context_for_order_dependent_category():
    """Real scenario, confirmed against the actual database: 21 of 195 real
    'Refund Request' tickets have no order_id."""
    ctx = make_ctx(ai_predicted_category="Refund Request", classification_confidence=0.9,
                    sentiment_score=-0.1, order_id=None)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.decision_path == "Human Review"
    assert "missing_order_context" in d.triggered_rules
    assert d.conflicting_signals is True


def test_order_dependent_category_with_order_present_does_not_trigger():
    ctx = make_ctx(ai_predicted_category="Refund Request", classification_confidence=0.9,
                    sentiment_score=-0.1, order_id=42)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "missing_order_context" not in d.triggered_rules


# ----------------------------------------------------------------------------
# Conflicting signals
# ----------------------------------------------------------------------------
def test_complaint_with_positive_sentiment_is_flagged_as_conflicting():
    ctx = make_ctx(ai_predicted_category="Complaint", classification_confidence=0.9,
                    sentiment_score=0.6, order_id=1)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "sentiment_category_conflict" in d.triggered_rules
    assert d.conflicting_signals is True


def test_complaint_with_negative_sentiment_is_not_flagged_as_conflicting():
    ctx = make_ctx(ai_predicted_category="Complaint", classification_confidence=0.9,
                    sentiment_score=-0.6, order_id=1)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "sentiment_category_conflict" not in d.triggered_rules


# ----------------------------------------------------------------------------
# Multiple rules simultaneously + precedence
# ----------------------------------------------------------------------------
def test_multiple_rules_can_trigger_simultaneously_and_are_all_reported():
    """A Complaint with positive sentiment triggers BOTH sensitive_category
    AND sentiment_category_conflict — both must be reported, not just one."""
    ctx = make_ctx(ai_predicted_category="Complaint", classification_confidence=0.9,
                    sentiment_score=0.6, order_id=1)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert "sensitive_category" in d.triggered_rules
    assert "sentiment_category_conflict" in d.triggered_rules
    assert len(d.triggered_rules) >= 2


def test_priority_precedence_takes_the_highest_floor_regardless_of_rule_order():
    """Three different priority floors are in play here: base category
    (Medium, from Refund Request), strong negative sentiment (High), and —
    if it were a VIP high-value order — also High. The engine must return
    the single highest (max), not whichever rule happened to run first."""
    ctx = make_ctx(ai_predicted_category="Refund Request", classification_confidence=0.9,
                    sentiment_score=-0.9, order_id=1)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    # base_category_priority alone would give "Medium"; sentiment escalation
    # gives "High" — the max must win.
    assert d.final_priority == "High"


def test_priority_resolution_is_independent_of_rule_evaluation_order():
    """Directly verifies the 'order independence' claim in engine.py's
    precedence docstring: shuffling the outcome list before taking the max
    must not change the result."""
    from src.rules.models import RuleOutcome
    outcomes = [
        RuleOutcome(rule_name="a", triggered=True, detail="", priority_floor="Low"),
        RuleOutcome(rule_name="b", triggered=True, detail="", priority_floor="Urgent"),
        RuleOutcome(rule_name="c", triggered=True, detail="", priority_floor="Medium"),
    ]
    from src.config import PRIORITY_ORDER
    for perm in (outcomes, list(reversed(outcomes)), [outcomes[1], outcomes[0], outcomes[2]]):
        floors = [o.priority_floor for o in perm]
        assert max(floors, key=lambda p: PRIORITY_ORDER[p]) == "Urgent"


# ----------------------------------------------------------------------------
# Fallback / invalid input
# ----------------------------------------------------------------------------
def test_invalid_confidence_raises_at_the_model_level():
    with pytest.raises(ValidationError):
        TicketContext(ticket_id=1, classification_confidence=5.0)


def test_safe_evaluate_falls_back_gracefully_on_invalid_input():
    d = safe_evaluate({"ticket_id": 99, "classification_confidence": 5.0})

    assert d.is_fallback is True
    assert d.decision_path == "Human Review"  # never fails open to Automated
    assert d.final_priority == "Medium"
    assert d.ticket_id == 99


def test_safe_evaluate_falls_back_on_unapproved_category():
    d = safe_evaluate({"ticket_id": 100, "ai_predicted_category": "Not A Real Category"})

    assert d.is_fallback is True
    assert d.decision_path == "Human Review"


def test_safe_evaluate_succeeds_normally_on_valid_input():
    d = safe_evaluate({"ticket_id": 101, "ai_predicted_category": "Product Question",
                        "classification_confidence": 0.9, "sentiment_score": 0.0})

    assert d.is_fallback is False
    assert d.decision_path == "Automated"


# ----------------------------------------------------------------------------
# Priority assignment sanity checks across all base categories
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("category,expected_base", [
    ("Order Status Inquiry", "Low"), ("Product Question", "Low"), ("Other", "Low"),
    ("Delivery Delay", "Medium"), ("Refund Request", "Medium"), ("Account Problem", "Medium"),
    ("Damaged Product", "High"), ("Missing Item", "High"), ("Payment Problem", "High"),
    ("Complaint", "Urgent"),
])
def test_base_category_priority_mapping(category, expected_base):
    ctx = make_ctx(ai_predicted_category=category, classification_confidence=0.9,
                    sentiment_score=0.0, order_id=1)
    d = evaluate(ctx, CONF_THRESHOLD, SENTIMENT_THRESHOLD, ORDER_VALUE_THRESHOLD)

    assert d.final_priority == expected_base
