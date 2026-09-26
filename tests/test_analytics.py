"""
Unit tests for Phase 6's analytics validation layer.

Pure logic — no database, no network. Crucially, these test the validator
against DELIBERATELY BROKEN snapshots as well as healthy ones: a validator
that only ever sees good data proves nothing about whether it would catch a
bad view.
"""

import pytest

from src.evaluation.analytics import (
    AnalyticsSnapshot,
    ValidationIssue,
    approx_equal,
    compute_median,
    safe_pct,
    summarize_analytics,
    validate_analytics,
)


# ----------------------------------------------------------------------------
# Percentage calculation & zero-denominator handling
# ----------------------------------------------------------------------------
def test_safe_pct_basic_calculation():
    assert safe_pct(25, 100) == 25.0
    assert safe_pct(1, 3) == 33.33      # rounded to 2dp, matching the views
    assert safe_pct(0, 100) == 0.0


def test_safe_pct_zero_denominator_returns_none_not_zero():
    """The distinction the whole honest-reporting discipline rests on:
    'no population to measure' is not 'measured zero'."""
    assert safe_pct(0, 0) is None
    assert safe_pct(5, 0) is None


def test_safe_pct_null_handling():
    assert safe_pct(None, 100) is None
    assert safe_pct(10, None) is None
    assert safe_pct(None, None) is None


def test_safe_pct_full_population():
    assert safe_pct(1500, 1500) == 100.0


# ----------------------------------------------------------------------------
# Median calculations
# ----------------------------------------------------------------------------
def test_median_odd_length():
    assert compute_median([1.0, 3.0, 2.0]) == 2.0


def test_median_even_length_interpolates_like_percentile_cont():
    """PostgreSQL's PERCENTILE_CONT interpolates between the two central
    values (unlike PERCENTILE_DISC); the Python recomputation must match, or
    the cross-check would produce false alarms on every even-sized dataset."""
    assert compute_median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_single_value():
    assert compute_median([42.0]) == 42.0


def test_median_empty_returns_none_not_zero():
    assert compute_median([]) is None


def test_median_ignores_nulls():
    assert compute_median([1.0, None, 3.0]) == 2.0


def test_median_all_nulls_returns_none():
    assert compute_median([None, None]) is None


# ----------------------------------------------------------------------------
# approx_equal semantics
# ----------------------------------------------------------------------------
def test_approx_equal_treats_both_none_as_agreement():
    assert approx_equal(None, None, 0.01) is True


def test_approx_equal_flags_none_versus_number_as_disagreement():
    assert approx_equal(None, 0.0, 0.01) is False
    assert approx_equal(0.0, None, 0.01) is False


def test_approx_equal_within_tolerance():
    assert approx_equal(33.33, 33.333, 0.01) is True
    assert approx_equal(33.33, 33.50, 0.01) is False


# ----------------------------------------------------------------------------
# Snapshot fixtures
# ----------------------------------------------------------------------------
def healthy_snapshot(**overrides):
    """A fully consistent snapshot resembling a system where every phase has
    run. Overrides let individual tests break exactly one thing."""
    classification = dict(total_tickets=100, classified_tickets=80, unclassified_tickets=20,
                          classification_coverage_pct=80.0, confidence_available=80,
                          low_confidence_tickets=8, low_confidence_rate_pct=10.0,
                          average_confidence=0.9, minimum_confidence=0.5, maximum_confidence=1.0,
                          exact_category_matches=72, exact_category_match_rate_pct=90.0)
    rule_decisions = dict(total_tickets=100, tickets_with_rule_decision=80,
                          automated_decisions=50, human_review_decisions=30,
                          automated_rate_pct=62.5, human_review_rate_pct=37.5,
                          urgent_human_review=10, urgent_human_review_rate_pct=12.5,
                          final_priority_set=80, average_priority_score=1.2)
    responses = dict(total_tickets=100, response_processed=80, response_not_processed=20,
                     drafts_generated=40, human_review_drafts=30, blocked_responses=5,
                     not_eligible_responses=5, response_processed_rate_pct=80.0,
                     draft_generation_rate_pct=50.0, human_review_response_rate_pct=37.5,
                     blocked_rate_pct=6.25, not_eligible_rate_pct=6.25)
    operational = dict(total_tickets=100, tickets_with_first_response=4,
                       avg_first_response_minutes=25.0, median_first_response_minutes=25.0,
                       resolved_tickets=3, avg_resolution_hours=2.0, median_resolution_hours=2.0,
                       tickets_with_rule_decision=80, avg_rule_decision_hours=1.0,
                       responses_generated=80, avg_response_generation_hours=1.5)

    snapshot = AnalyticsSnapshot(
        classification=classification, rule_decisions=rule_decisions,
        responses=responses, operational=operational,
        ticket_row_count=100, distinct_ticket_ids=100,
        first_response_minutes=[10.0, 20.0, 30.0, 40.0],   # median 25.0
        resolution_hours=[1.0, 2.0, 3.0],                   # median 2.0
    )
    for key, value in overrides.items():
        setattr(snapshot, key, value)
    return snapshot


def empty_snapshot():
    """The system's ACTUAL current state: real tickets, but no AI stage has
    run, so every derived rate is NULL rather than 0."""
    classification = dict(total_tickets=1500, classified_tickets=0, unclassified_tickets=1500,
                          classification_coverage_pct=0.0, confidence_available=0,
                          low_confidence_tickets=0, low_confidence_rate_pct=None,
                          average_confidence=None, minimum_confidence=None, maximum_confidence=None,
                          exact_category_matches=0, exact_category_match_rate_pct=None)
    rule_decisions = dict(total_tickets=1500, tickets_with_rule_decision=0,
                          automated_decisions=0, human_review_decisions=0,
                          automated_rate_pct=None, human_review_rate_pct=None,
                          urgent_human_review=0, urgent_human_review_rate_pct=None,
                          final_priority_set=0, average_priority_score=None)
    responses = dict(total_tickets=1500, response_processed=0, response_not_processed=1500,
                     drafts_generated=0, human_review_drafts=0, blocked_responses=0,
                     not_eligible_responses=0, response_processed_rate_pct=0.0,
                     draft_generation_rate_pct=None, human_review_response_rate_pct=None,
                     blocked_rate_pct=None, not_eligible_rate_pct=None)
    operational = dict(total_tickets=1500, tickets_with_first_response=0,
                       avg_first_response_minutes=None, median_first_response_minutes=None,
                       resolved_tickets=0, avg_resolution_hours=None, median_resolution_hours=None,
                       tickets_with_rule_decision=0, avg_rule_decision_hours=None,
                       responses_generated=0, avg_response_generation_hours=None)
    return AnalyticsSnapshot(classification=classification, rule_decisions=rule_decisions,
                              responses=responses, operational=operational,
                              ticket_row_count=1500, distinct_ticket_ids=1500)


# ----------------------------------------------------------------------------
# Validator: healthy and empty data both pass
# ----------------------------------------------------------------------------
def test_healthy_snapshot_produces_no_issues():
    assert validate_analytics(healthy_snapshot()) == []


def test_empty_pipeline_snapshot_is_consistent_not_an_error():
    """Zero coverage is a valid, internally-consistent state — the validator
    must not confuse 'nothing has run' with 'something is broken'."""
    assert validate_analytics(empty_snapshot()) == []


# ----------------------------------------------------------------------------
# Validator: it actually catches inconsistencies
# ----------------------------------------------------------------------------
def test_grain_violation_is_caught():
    snapshot = healthy_snapshot(distinct_ticket_ids=90)   # rows multiplied by a bad join
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "ticket_grain" in checks


def test_classification_count_partition_violation_is_caught():
    snapshot = healthy_snapshot()
    snapshot.classification["unclassified_tickets"] = 10   # 80 + 10 != 100
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "classification_counts" in checks


def test_wrong_coverage_percentage_is_caught():
    snapshot = healthy_snapshot()
    snapshot.classification["classification_coverage_pct"] = 95.0   # should be 80.0
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "classification_coverage_pct" in checks


def test_more_matches_than_classified_is_caught():
    snapshot = healthy_snapshot()
    snapshot.classification["exact_category_matches"] = 90   # > 80 classified
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "exact_category_matches" in checks


def test_rule_decision_partition_violation_is_caught():
    snapshot = healthy_snapshot()
    snapshot.rule_decisions["human_review_decisions"] = 20   # 50 + 20 != 80
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "rule_decision_counts" in checks


def test_wrong_automated_rate_is_caught():
    snapshot = healthy_snapshot()
    snapshot.rule_decisions["automated_rate_pct"] = 80.0   # should be 62.5
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "automated_rate_pct" in checks


def test_urgent_exceeding_human_review_is_caught():
    """Urgent human review is a strict subset of human review — Phase 4.1's
    definition made this an invariant, so violating it must be an error."""
    snapshot = healthy_snapshot()
    snapshot.rule_decisions["urgent_human_review"] = 40   # > 30 human reviews
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "urgent_human_review" in checks


def test_decision_rates_not_summing_to_100_is_caught():
    snapshot = healthy_snapshot()
    snapshot.rule_decisions["automated_rate_pct"] = 62.5
    snapshot.rule_decisions["human_review_rate_pct"] = 20.0   # 82.5 != 100
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "decision_rates_sum" in checks


def test_response_status_counts_not_summing_is_caught():
    snapshot = healthy_snapshot()
    snapshot.responses["blocked_responses"] = 20   # 40+30+20+5 != 80
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "response_status_counts" in checks


def test_wrong_response_rate_is_caught():
    snapshot = healthy_snapshot()
    snapshot.responses["draft_generation_rate_pct"] = 12.0   # should be 50.0
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "draft_generation_rate_pct" in checks


def test_median_disagreement_between_sql_and_python_is_caught():
    snapshot = healthy_snapshot()
    snapshot.operational["median_first_response_minutes"] = 99.0   # real median is 25.0
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "median_first_response_minutes" in checks


def test_percentage_out_of_range_is_caught():
    snapshot = healthy_snapshot()
    snapshot.responses["blocked_rate_pct"] = 150.0
    checks = [i.check for i in validate_analytics(snapshot)]
    assert any("blocked_rate_pct" in c for c in checks)


def test_negative_duration_is_caught():
    snapshot = healthy_snapshot()
    snapshot.operational["avg_resolution_hours"] = -5.0
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "operational.avg_resolution_hours" in checks


def test_null_rate_where_a_number_is_expected_is_caught():
    """A view that silently returns NULL for a measurable population is just
    as wrong as one returning the wrong number."""
    snapshot = healthy_snapshot()
    snapshot.rule_decisions["automated_rate_pct"] = None   # 80 decided -> should be 62.5
    checks = [i.check for i in validate_analytics(snapshot)]
    assert "automated_rate_pct" in checks


# ----------------------------------------------------------------------------
# Summary rendering
# ----------------------------------------------------------------------------
def test_summary_renders_unavailable_metrics_as_not_available_not_zero():
    summary = summarize_analytics(empty_snapshot(), [])

    assert summary["classification"]["exact_category_match_rate_pct"] == "NOT AVAILABLE"
    assert summary["classification"]["average_confidence"] == "NOT AVAILABLE"
    assert summary["rule_decisions"]["automated_rate_pct"] == "NOT AVAILABLE"
    # Coverage IS genuinely measurable over all tickets, so it stays numeric
    assert summary["classification"]["classification_coverage_pct"] == 0.0
    assert summary["read_only"] is True


def test_summary_reports_issues_it_was_given():
    issues = [ValidationIssue("ERROR", "some_check", "something disagreed")]
    summary = summarize_analytics(healthy_snapshot(), issues)

    assert summary["validation"]["issues_found"] == 1
    assert summary["validation"]["issues"][0]["check"] == "some_check"


def test_summary_flags_grain_problem():
    summary = summarize_analytics(healthy_snapshot(distinct_ticket_ids=90), [])
    assert summary["ticket_grain_ok"] is False
