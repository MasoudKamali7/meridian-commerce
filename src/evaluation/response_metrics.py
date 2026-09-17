"""
Meridian Commerce — Phase 5: Response Evaluation Metrics

Follows the Phase 4.1 metric-naming discipline exactly: every rate below
names precisely what it measures, and every one shares the SAME denominator
(n_processed = all tickets processed in the run/query) unless its name says
otherwise. Numerator/denominator for each is spelled out here so the Phase
4.1 "escalation_rate" ambiguity can't recur in this module.

METRIC DEFINITIONS (denominator = n_processed for all of these):

  automated_response_eligible_rate
      numerator: response_status == "DRAFT_GENERATED"
      meaning:   share of processed tickets that got an APPROVED,
                 customer-facing draft. Named "...eligible_rate" to match
                 the brief's requested metric, but note it measures
                 eligibility AND successful generation together — a ticket
                 eligible for automation whose draft failed the safety scan
                 lands in BLOCKED, not here. See blocked_response_rate.

  human_review_response_rate
      numerator: response_status == "HUMAN_REVIEW_DRAFT"
      meaning:   share routed to a human (Phase 4's ruling, or Phase 5
                 failing safe). Says nothing about whether an internal
                 draft was produced — see internal_draft_rate.

  blocked_response_rate
      numerator: response_status == "BLOCKED"
      meaning:   automation was authorized and Phase 5 agreed, but no safe
                 customer-facing draft could be produced.

  not_eligible_rate
      numerator: response_status == "NOT_ELIGIBLE"
      meaning:   Phase 4 hasn't decided this ticket yet (or input validation
                 failed). Nothing was attempted.

  draft_generation_success_rate
      numerator: decisions where a draft text was actually produced
                 (DRAFT_GENERATED, or HUMAN_REVIEW_DRAFT with a draft)
      denominator: decisions where generation was ATTEMPTED — i.e. NOT
                 not_eligible, and not skipped for lack of a generator.
                 This is the one metric with a different denominator, and
                 it's named and documented accordingly, because "success
                 rate" over tickets that never attempted generation would
                 be meaningless.

  missing_context_rate
      numerator: decisions whose rationale cites missing/insufficient
                 grounded context
      meaning:   how often the pipeline lacked the facts to answer.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from ..response.models import ResponseDecision


@dataclass
class ResponseEvaluationReport:
    metric_provenance: str
    n_processed: int
    automated_response_eligible_rate: Optional[float]
    human_review_response_rate: Optional[float]
    blocked_response_rate: Optional[float]
    not_eligible_rate: Optional[float]
    response_status_distribution: dict
    response_type_distribution: dict
    draft_generation_attempted: int
    draft_generation_succeeded: int
    draft_generation_success_rate: Optional[float]
    internal_draft_rate: Optional[float]       # share of HUMAN_REVIEW_DRAFT that got an internal draft
    missing_context_rate: Optional[float]
    fallback_rate: Optional[float]
    notes: List[str] = field(default_factory=list)


_MISSING_CONTEXT_MARKERS = (
    "insufficient grounded context",
    "requires order context",
    "classification is missing",
    "no order is linked",
)


def compute_response_evaluation(decisions: List[ResponseDecision],
                                 provenance_label: str = "REAL (in-memory batch run)"
                                 ) -> ResponseEvaluationReport:
    n = len(decisions)
    if n == 0:
        return ResponseEvaluationReport(
            metric_provenance=provenance_label, n_processed=0,
            automated_response_eligible_rate=None, human_review_response_rate=None,
            blocked_response_rate=None, not_eligible_rate=None,
            response_status_distribution={}, response_type_distribution={},
            draft_generation_attempted=0, draft_generation_succeeded=0,
            draft_generation_success_rate=None, internal_draft_rate=None,
            missing_context_rate=None, fallback_rate=None,
            notes=["No decisions were processed in this run."],
        )

    status_counts = Counter(d.response_status for d in decisions)
    type_counts = Counter(d.response_type or "(unknown/unclassified)" for d in decisions)

    human_review_decisions = [d for d in decisions if d.response_status == "HUMAN_REVIEW_DRAFT"]
    internal_drafts = sum(1 for d in human_review_decisions if d.response_draft)

    # Generation was "attempted" for anything that wasn't NOT_ELIGIBLE and
    # wasn't explicitly skipped for lack of a generator.
    skipped_marker = "no generator was configured"
    skipped_marker2 = "generation skipped (no generator configured)"
    attempted = [
        d for d in decisions
        if d.response_status != "NOT_ELIGIBLE"
        and not any(skipped_marker in r.lower() or skipped_marker2 in r.lower() for r in d.rationale)
    ]
    succeeded = [d for d in attempted if d.response_draft]

    missing_context = sum(
        1 for d in decisions
        if any(marker in r.lower() for r in d.rationale for marker in _MISSING_CONTEXT_MARKERS)
    )

    notes = []
    if not attempted:
        notes.append("No generation was attempted in this run (no generator configured, or every "
                      "ticket was NOT_ELIGIBLE) — draft_generation_success_rate is NOT AVAILABLE "
                      "rather than 0, since 0 would wrongly imply attempts that failed.")

    return ResponseEvaluationReport(
        metric_provenance=provenance_label,
        n_processed=n,
        automated_response_eligible_rate=status_counts["DRAFT_GENERATED"] / n,
        human_review_response_rate=status_counts["HUMAN_REVIEW_DRAFT"] / n,
        blocked_response_rate=status_counts["BLOCKED"] / n,
        not_eligible_rate=status_counts["NOT_ELIGIBLE"] / n,
        response_status_distribution=dict(status_counts),
        response_type_distribution=dict(type_counts),
        draft_generation_attempted=len(attempted),
        draft_generation_succeeded=len(succeeded),
        draft_generation_success_rate=(len(succeeded) / len(attempted)) if attempted else None,
        internal_draft_rate=(internal_drafts / len(human_review_decisions))
                             if human_review_decisions else None,
        missing_context_rate=missing_context / n,
        fallback_rate=sum(1 for d in decisions if d.is_fallback) / n,
        notes=notes,
    )


def compute_response_evaluation_from_db(rows: List[dict]) -> ResponseEvaluationReport:
    """Reconstructed from `fetch_phase5_results` rows. Rationale strings
    aren't persisted (by design — they're in the audit log, matching Phase
    4's precedent), so missing_context_rate and fallback_rate are explicitly
    NOT AVAILABLE here rather than silently reported as 0."""
    n = len(rows)
    notes = ["missing_context_rate and fallback_rate are NOT AVAILABLE from the database — "
             "rationale detail lives only in the audit log from the run that produced these "
             "decisions, not in ticket columns."]
    if n == 0:
        return ResponseEvaluationReport(
            metric_provenance="REAL (derived from database)", n_processed=0,
            automated_response_eligible_rate=None, human_review_response_rate=None,
            blocked_response_rate=None, not_eligible_rate=None,
            response_status_distribution={}, response_type_distribution={},
            draft_generation_attempted=0, draft_generation_succeeded=0,
            draft_generation_success_rate=None, internal_draft_rate=None,
            missing_context_rate=None, fallback_rate=None,
            notes=["No tickets have a Phase 5 response decision in the database yet."],
        )

    status_counts = Counter(r["response_status"] for r in rows)
    type_counts = Counter(r["response_type"] or "(unknown/unclassified)" for r in rows)

    human_review_rows = [r for r in rows if r["response_status"] == "HUMAN_REVIEW_DRAFT"]
    internal_drafts = sum(1 for r in human_review_rows if r["has_draft"])

    attempted_rows = [r for r in rows if r["response_status"] != "NOT_ELIGIBLE"]
    succeeded_rows = [r for r in attempted_rows if r["has_draft"]]
    notes.append("draft_generation_attempted here counts all non-NOT_ELIGIBLE rows; unlike the "
                 "in-memory version it cannot tell 'generation was skipped for lack of a "
                 "generator' apart from 'generation was attempted and failed'.")

    return ResponseEvaluationReport(
        metric_provenance="REAL (derived from database)",
        n_processed=n,
        automated_response_eligible_rate=status_counts["DRAFT_GENERATED"] / n,
        human_review_response_rate=status_counts["HUMAN_REVIEW_DRAFT"] / n,
        blocked_response_rate=status_counts["BLOCKED"] / n,
        not_eligible_rate=status_counts["NOT_ELIGIBLE"] / n,
        response_status_distribution=dict(status_counts),
        response_type_distribution=dict(type_counts),
        draft_generation_attempted=len(attempted_rows),
        draft_generation_succeeded=len(succeeded_rows),
        draft_generation_success_rate=(len(succeeded_rows) / len(attempted_rows))
                                       if attempted_rows else None,
        internal_draft_rate=(internal_drafts / len(human_review_rows)) if human_review_rows else None,
        missing_context_rate=None,
        fallback_rate=None,
        notes=notes,
    )
