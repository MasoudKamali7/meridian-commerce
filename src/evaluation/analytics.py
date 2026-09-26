"""
Meridian Commerce — Phase 6: Analytics Validation (READ-ONLY)

Reads the analytical views created by sql/09_phase6_analytics_views.sql and
independently re-derives the metrics that can be cross-checked, so a broken
view is caught rather than trusted. Every database interaction in this module
is a SELECT — Phase 6 never mutates operational data.

Why re-derive at all, when the SQL already computed it? The same reason
Phase 4.1 extracted `derive_recommended_action` into one shared function: two
independent definitions of a number will eventually disagree, and you want to
find out from a test rather than from a dashboard. Here the SQL and the
Python are deliberately INDEPENDENT implementations — the Python recomputes
percentages from the raw counts in the same view, and recomputes medians from
the ticket-grain rows — so agreement is meaningful evidence.

Honest-reporting rule carried forward from Phases 3-5: a metric whose
population is empty is NOT AVAILABLE (None), never 0. "0% accuracy" and "no
predictions exist to score" are completely different statements.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from ..database.connection import get_cursor

# Tolerance for comparing a Python-recomputed percentage against the SQL one.
# The views round to 2 decimals, so anything within half a unit in the last
# place is agreement, not a discrepancy.
PCT_TOLERANCE = 0.01
MEDIAN_TOLERANCE = 0.02

ANALYTICS_VIEWS = [
    "vw_ticket_analytics",
    "vw_classification_metrics",
    "vw_rule_decision_metrics",
    "vw_response_metrics",
    "vw_operational_metrics",
]


# ----------------------------------------------------------------------------
# Pure helpers (no database — unit-testable in isolation)
# ----------------------------------------------------------------------------
def safe_pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Percentage, or None when the population is empty/unknown. Mirrors the
    views' NULLIF(denominator, 0) behavior exactly, which is what makes the
    SQL-vs-Python comparison a real check rather than a tautology."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return round(float(numerator) * 100.0 / float(denominator), 2)


def compute_median(values: List[float]) -> Optional[float]:
    """Continuous median matching PostgreSQL's PERCENTILE_CONT(0.5):
    linear interpolation between the two central values, not the discrete
    PERCENTILE_DISC behavior. None for an empty list (not 0)."""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    n = len(clean)
    pos = 0.5 * (n - 1)
    lower = int(pos)
    upper = min(lower + 1, n - 1)
    frac = pos - lower
    return clean[lower] + (clean[upper] - clean[lower]) * frac


def approx_equal(a: Optional[float], b: Optional[float], tolerance: float) -> bool:
    """None == None is agreement (both say 'not available'); None vs a number
    is a genuine disagreement worth flagging."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tolerance


# ----------------------------------------------------------------------------
# Snapshot + validation results
# ----------------------------------------------------------------------------
@dataclass
class ValidationIssue:
    severity: str    # "ERROR" (metrics disagree / impossible value) or "INFO"
    check: str
    detail: str


@dataclass
class AnalyticsSnapshot:
    classification: dict
    rule_decisions: dict
    responses: dict
    operational: dict
    ticket_row_count: int
    distinct_ticket_ids: int
    first_response_minutes: List[float] = field(default_factory=list)
    resolution_hours: List[float] = field(default_factory=list)


def fetch_analytics(conn) -> AnalyticsSnapshot:
    """READ-ONLY. Pulls the four aggregate views plus the ticket-grain columns
    needed to independently recompute medians."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT * FROM vw_classification_metrics;")
        classification = dict(cur.fetchone())
        cur.execute("SELECT * FROM vw_rule_decision_metrics;")
        rule_decisions = dict(cur.fetchone())
        cur.execute("SELECT * FROM vw_response_metrics;")
        responses = dict(cur.fetchone())
        cur.execute("SELECT * FROM vw_operational_metrics;")
        operational = dict(cur.fetchone())

        cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT ticket_id) AS d FROM vw_ticket_analytics;")
        grain = cur.fetchone()

        cur.execute("""
            SELECT first_response_minutes, resolution_hours
            FROM vw_ticket_analytics
            WHERE first_response_minutes IS NOT NULL OR resolution_hours IS NOT NULL;
        """)
        rows = cur.fetchall()

    return AnalyticsSnapshot(
        classification=classification,
        rule_decisions=rule_decisions,
        responses=responses,
        operational=operational,
        ticket_row_count=grain["n"],
        distinct_ticket_ids=grain["d"],
        first_response_minutes=[float(r["first_response_minutes"]) for r in rows
                                 if r["first_response_minutes"] is not None],
        resolution_hours=[float(r["resolution_hours"]) for r in rows
                           if r["resolution_hours"] is not None],
    )


def validate_analytics(snapshot: AnalyticsSnapshot) -> List[ValidationIssue]:
    """Independently re-derives what can be re-derived and reports every
    disagreement. An empty list means the analytical layer is internally
    consistent — it does NOT mean the metrics are meaningful (they can be
    consistently NOT AVAILABLE, which is exactly the current situation)."""
    issues: List[ValidationIssue] = []
    c, r, resp, op = (snapshot.classification, snapshot.rule_decisions,
                      snapshot.responses, snapshot.operational)

    def err(check, detail):
        issues.append(ValidationIssue("ERROR", check, detail))

    # --- Ticket grain: the foundation every other count rests on ---
    if snapshot.ticket_row_count != snapshot.distinct_ticket_ids:
        err("ticket_grain",
            f"vw_ticket_analytics has {snapshot.ticket_row_count} rows but only "
            f"{snapshot.distinct_ticket_ids} distinct ticket_ids — a join is multiplying rows.")
    if snapshot.ticket_row_count != c["total_tickets"]:
        err("ticket_grain_vs_total",
            f"vw_ticket_analytics rows ({snapshot.ticket_row_count}) != total_tickets "
            f"({c['total_tickets']}).")

    # --- Classification: counts partition, percentages re-derive ---
    if c["classified_tickets"] + c["unclassified_tickets"] != c["total_tickets"]:
        err("classification_counts",
            "classified + unclassified != total_tickets.")
    if not approx_equal(c["classification_coverage_pct"],
                         safe_pct(c["classified_tickets"], c["total_tickets"]), PCT_TOLERANCE):
        err("classification_coverage_pct", "SQL coverage disagrees with the Python recomputation.")
    if not approx_equal(c["low_confidence_rate_pct"],
                         safe_pct(c["low_confidence_tickets"], c["confidence_available"]), PCT_TOLERANCE):
        err("low_confidence_rate_pct", "SQL low-confidence rate disagrees with the recomputation.")
    if not approx_equal(c["exact_category_match_rate_pct"],
                         safe_pct(c["exact_category_matches"], c["classified_tickets"]), PCT_TOLERANCE):
        err("exact_category_match_rate_pct", "SQL match rate disagrees with the recomputation.")
    if c["exact_category_matches"] > c["classified_tickets"]:
        err("exact_category_matches", "More exact matches than classified tickets — impossible.")

    # --- Rule decisions: Phase 4's two paths must partition the decided set ---
    decided = r["tickets_with_rule_decision"]
    if r["automated_decisions"] + r["human_review_decisions"] != decided:
        err("rule_decision_counts",
            "automated + human_review != tickets_with_rule_decision.")
    if not approx_equal(r["automated_rate_pct"],
                         safe_pct(r["automated_decisions"], decided), PCT_TOLERANCE):
        err("automated_rate_pct", "SQL automated rate disagrees with the recomputation.")
    if not approx_equal(r["human_review_rate_pct"],
                         safe_pct(r["human_review_decisions"], decided), PCT_TOLERANCE):
        err("human_review_rate_pct", "SQL human-review rate disagrees with the recomputation.")
    if r["urgent_human_review"] > r["human_review_decisions"]:
        err("urgent_human_review",
            "Urgent human reviews exceed total human reviews — urgent is a strict subset.")
    if (r["automated_rate_pct"] is not None and r["human_review_rate_pct"] is not None
            and not approx_equal(float(r["automated_rate_pct"]) + float(r["human_review_rate_pct"]),
                                  100.0, 0.05)):
        err("decision_rates_sum", "automated_rate_pct + human_review_rate_pct != 100.")

    # --- Responses: the four Phase 5 statuses must partition the processed set ---
    processed = resp["response_processed"]
    status_sum = (resp["drafts_generated"] + resp["human_review_drafts"]
                  + resp["blocked_responses"] + resp["not_eligible_responses"])
    if status_sum != processed:
        err("response_status_counts",
            f"Status counts sum to {status_sum} but response_processed is {processed} — "
            f"an unexpected status value may exist.")
    if resp["response_processed"] + resp["response_not_processed"] != resp["total_tickets"]:
        err("response_processed_partition", "processed + not_processed != total_tickets.")
    for pct_field, count_field in [("draft_generation_rate_pct", "drafts_generated"),
                                    ("human_review_response_rate_pct", "human_review_drafts"),
                                    ("blocked_rate_pct", "blocked_responses"),
                                    ("not_eligible_rate_pct", "not_eligible_responses")]:
        if not approx_equal(resp[pct_field], safe_pct(resp[count_field], processed), PCT_TOLERANCE):
            err(pct_field, f"SQL {pct_field} disagrees with the recomputation.")

    # --- Operational: medians recomputed independently from ticket-grain rows ---
    if not approx_equal(op["median_first_response_minutes"],
                         compute_median(snapshot.first_response_minutes), MEDIAN_TOLERANCE):
        err("median_first_response_minutes",
            "SQL PERCENTILE_CONT median disagrees with the Python recomputation.")
    if not approx_equal(op["median_resolution_hours"],
                         compute_median(snapshot.resolution_hours), MEDIAN_TOLERANCE):
        err("median_resolution_hours",
            "SQL PERCENTILE_CONT median disagrees with the Python recomputation.")
    if op["tickets_with_first_response"] != len(snapshot.first_response_minutes):
        err("first_response_count",
            "tickets_with_first_response disagrees with the ticket-grain row count.")
    if op["resolved_tickets"] != len(snapshot.resolution_hours):
        err("resolved_count", "resolved_tickets disagrees with the ticket-grain row count.")

    # --- Universal sanity: no percentage outside 0-100, no negative duration ---
    for name, block in [("classification", c), ("rule_decisions", r), ("responses", resp)]:
        for key, value in block.items():
            if key.endswith("_pct") and value is not None and not (0 <= float(value) <= 100):
                err(f"{name}.{key}", f"Percentage out of range: {value}")
    for key in ("avg_first_response_minutes", "median_first_response_minutes",
                 "avg_resolution_hours", "median_resolution_hours"):
        if op[key] is not None and float(op[key]) < 0:
            err(f"operational.{key}", f"Negative duration: {op[key]}")

    return issues


def summarize_analytics(snapshot: AnalyticsSnapshot, issues: List[ValidationIssue]) -> dict:
    """Concise summary for the CLI and the Phase 6 report. Any metric whose
    population is empty is rendered as the string 'NOT AVAILABLE' rather than
    a number, so a reader can never mistake 'nothing ran' for 'measured zero'."""
    def na(value):
        return "NOT AVAILABLE" if value is None else float(value)

    c, r, resp, op = (snapshot.classification, snapshot.rule_decisions,
                      snapshot.responses, snapshot.operational)

    return {
        "read_only": True,
        "ticket_grain_ok": snapshot.ticket_row_count == snapshot.distinct_ticket_ids,
        "total_tickets": c["total_tickets"],
        "classification": {
            "classified_tickets": c["classified_tickets"],
            "classification_coverage_pct": na(c["classification_coverage_pct"]),
            "average_confidence": na(c["average_confidence"]),
            "low_confidence_rate_pct": na(c["low_confidence_rate_pct"]),
            "exact_category_match_rate_pct": na(c["exact_category_match_rate_pct"]),
            "note": ("exact_category_match_rate_pct is an accuracy-STYLE backtest against "
                     "synthetic seed labels once predictions exist — never validated "
                     "production accuracy."),
        },
        "rule_decisions": {
            "tickets_with_rule_decision": r["tickets_with_rule_decision"],
            "automated_rate_pct": na(r["automated_rate_pct"]),
            "human_review_rate_pct": na(r["human_review_rate_pct"]),
            "urgent_human_review_rate_pct": na(r["urgent_human_review_rate_pct"]),
            "average_priority_score": na(r["average_priority_score"]),
        },
        "responses": {
            "response_processed": resp["response_processed"],
            "response_processed_rate_pct": na(resp["response_processed_rate_pct"]),
            "draft_generation_rate_pct": na(resp["draft_generation_rate_pct"]),
            "blocked_rate_pct": na(resp["blocked_rate_pct"]),
        },
        "operational": {
            "tickets_with_first_response": op["tickets_with_first_response"],
            "avg_first_response_minutes": na(op["avg_first_response_minutes"]),
            "median_first_response_minutes": na(op["median_first_response_minutes"]),
            "resolved_tickets": op["resolved_tickets"],
            "avg_resolution_hours": na(op["avg_resolution_hours"]),
            "median_resolution_hours": na(op["median_resolution_hours"]),
        },
        "validation": {
            "issues_found": len(issues),
            "issues": [{"severity": i.severity, "check": i.check, "detail": i.detail} for i in issues],
        },
    }
