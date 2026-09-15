"""
Meridian Commerce — Phase 4: Evaluation Metrics

Two entry points, because they can answer different questions depending on
what data is available:

  compute_rules_evaluation(decisions)
      Works on the full, in-memory list of `Decision` objects produced
      during a batch run. This is the ONLY way to get rule-frequency,
      conflict-frequency, and fallback-frequency numbers, because those
      details (which rules fired, why) are written to the audit log, not to
      new database columns (see PHASE4_SUMMARY.md for why) — so they can't
      be recovered from the database after the fact.

  compute_rules_evaluation_from_db(rows)
      Works on rows fetched back from the database (`fetch_phase4_results`).
      Can report totals, automated/human-review rates, urgent_human_review_rate
      (see below — this one IS exactly reconstructible, not approximated),
      priority distribution, and category/sentiment/confidence breakdowns —
      but explicitly reports rule-frequency/conflict/fallback as NOT
      AVAILABLE, rather than guessing or omitting them silently.

METRIC DEFINITIONS (Phase 4.1 cleanup — see PHASE4_SUMMARY.md §"Phase 4.1"):
Every rate below shares the SAME denominator: n_processed, the count of
ALL tickets processed in this run/query. None of them are conditioned on
another metric already having narrowed the population.

  automated_rate
      numerator:   count where decision_path == "Automated"
      denominator: n_processed
      meaning:     share of processed tickets the rule engine judged safe
                   to handle without a human.

  human_review_rate
      numerator:   count where decision_path == "Human Review"
      denominator: n_processed
      meaning:     share of processed tickets routed to a human — this IS
                   the "automation rejection rate": there is no separate
                   concept beyond this one, so no third metric was invented
                   for it. automated_rate + human_review_rate == 1.0 always,
                   since decision_path is a binary field.

  urgent_human_review_rate
      numerator:   count where recommended_action == "HUMAN_REVIEW_URGENT"
      denominator: n_processed  (NOT count of human-review tickets — this
                   was the exact ambiguity Phase 4.1 fixes. Renamed from the
                   old "escalation_rate", which read to a reviewer as "% of
                   tickets escalated" i.e. % of ALL tickets routed to human
                   review — but was actually computed as % of ALL tickets
                   recommended urgent, a narrower and differently-scoped
                   number under an ambiguous name.)
      meaning:     share of ALL processed tickets that are BOTH routed to a
                   human AND flagged urgent (High/Urgent priority). This is
                   a subset of human_review_rate by construction — urgent
                   human review requires the ticket to have gone to human
                   review at all — so urgent_human_review_rate <=
                   human_review_rate always. It is never computed as a share
                   of human-reviewed tickets alone; see engine.py's
                   `derive_recommended_action` for the exact rule.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from ..rules.engine import derive_recommended_action
from ..rules.models import Decision


def _bucket_sentiment(score: Optional[float]) -> str:
    if score is None:
        return "missing"
    if score <= -0.7:
        return "very_negative (<= -0.7)"
    if score <= -0.3:
        return "negative (-0.7 to -0.3)"
    if score < 0.3:
        return "neutral (-0.3 to 0.3)"
    if score < 0.7:
        return "positive (0.3 to 0.7)"
    return "very_positive (>= 0.7)"


def _bucket_confidence(score: Optional[float], threshold: float) -> str:
    if score is None:
        return "missing"
    if score < threshold:
        return f"below_threshold (< {threshold})"
    return f"at_or_above_threshold (>= {threshold})"


@dataclass
class RulesEvaluationReport:
    metric_provenance: str   # "REAL (in-memory batch run)" / "REAL (derived from database)" / "SIMULATED (...)"
    n_processed: int
    automated_rate: Optional[float]              # numerator: decision_path == "Automated";   denom: n_processed
    human_review_rate: Optional[float]           # numerator: decision_path == "Human Review"; denom: n_processed
    urgent_human_review_rate: Optional[float]    # numerator: recommended_action == "HUMAN_REVIEW_URGENT"; denom: n_processed
    priority_distribution: dict
    decisions_by_category: dict
    decisions_by_sentiment_bucket: dict
    decisions_by_confidence_bucket: dict
    rule_frequency: Optional[dict]             # None when NOT AVAILABLE
    multi_rule_frequency: Optional[float]       # fraction of tickets with >1 rule triggered; None when NOT AVAILABLE
    conflict_frequency: Optional[float]         # None when NOT AVAILABLE
    fallback_frequency: Optional[float]         # None when NOT AVAILABLE
    notes: List[str] = field(default_factory=list)


def compute_rules_evaluation(decisions: List[Decision], confidence_threshold: float,
                              contexts_by_ticket_id: Optional[dict] = None,
                              provenance_label: str = "REAL (in-memory batch run)") -> RulesEvaluationReport:
    """Full evaluation from an in-memory batch run. `contexts_by_ticket_id`
    (ticket_id -> TicketContext), if supplied, enables the category/
    sentiment/confidence breakdowns; without it those breakdowns are
    reported as empty, with a note, rather than guessed.

    `provenance_label` MUST be overridden by the caller when `decisions`
    came from simulated/fixture data rather than real database tickets —
    e.g. "SIMULATED (fixture data, not real tickets)" — so this report can
    never be mistaken for a real-data result downstream."""
    n = len(decisions)
    if n == 0:
        return RulesEvaluationReport(
            metric_provenance=provenance_label, n_processed=0,
            automated_rate=None, human_review_rate=None, urgent_human_review_rate=None,
            priority_distribution={}, decisions_by_category={},
            decisions_by_sentiment_bucket={}, decisions_by_confidence_bucket={},
            rule_frequency={}, multi_rule_frequency=None, conflict_frequency=None,
            fallback_frequency=None, notes=["No decisions were processed in this run."],
        )

    automated = sum(1 for d in decisions if d.decision_path == "Automated")
    human = n - automated
    urgent_human_review = sum(1 for d in decisions if d.recommended_action == "HUMAN_REVIEW_URGENT")
    fallback = sum(1 for d in decisions if d.is_fallback)
    conflicts = sum(1 for d in decisions if d.conflicting_signals)
    multi_rule = sum(1 for d in decisions if len(d.triggered_rules) > 1)

    priority_dist = dict(Counter(d.final_priority for d in decisions))

    rule_freq = dict(Counter(
        rule for d in decisions for rule in d.triggered_rules
    ))

    category_breakdown, sentiment_breakdown, confidence_breakdown = {}, {}, {}
    notes = []
    if contexts_by_ticket_id:
        cat_counter = Counter()
        sent_counter = Counter()
        conf_counter = Counter()
        for d in decisions:
            ctx = contexts_by_ticket_id.get(d.ticket_id)
            if ctx is None:
                continue
            cat_counter[ctx.ai_predicted_category or "(unclassified)"] += 1
            sent_counter[_bucket_sentiment(ctx.sentiment_score)] += 1
            conf_counter[_bucket_confidence(ctx.classification_confidence, confidence_threshold)] += 1
        category_breakdown = dict(cat_counter)
        sentiment_breakdown = dict(sent_counter)
        confidence_breakdown = dict(conf_counter)
    else:
        notes.append("Category/sentiment/confidence breakdowns require ticket contexts, which "
                      "weren't supplied — reported as empty rather than guessed.")

    return RulesEvaluationReport(
        metric_provenance=provenance_label,
        n_processed=n,
        automated_rate=automated / n,
        human_review_rate=human / n,
        urgent_human_review_rate=urgent_human_review / n,
        priority_distribution=priority_dist,
        decisions_by_category=category_breakdown,
        decisions_by_sentiment_bucket=sentiment_breakdown,
        decisions_by_confidence_bucket=confidence_breakdown,
        rule_frequency=rule_freq,
        multi_rule_frequency=multi_rule / n,
        conflict_frequency=conflicts / n,
        fallback_frequency=fallback / n,
        notes=notes,
    )


def compute_rules_evaluation_from_db(rows: List[dict], confidence_threshold: float) -> RulesEvaluationReport:
    """Evaluation reconstructed from `fetch_phase4_results` database rows.

    urgent_human_review_rate IS exactly reconstructible here (not
    approximated): recommended_action is a pure function of exactly the two
    columns Phase 4 persists (decision_path, final_priority) — see
    `derive_recommended_action` in rules/engine.py, which this function
    calls directly so the two can never drift apart. (Phase 4.1 fix: an
    earlier version of this function approximated it as "Human Review AND
    priority in {High, Urgent}", which happens to be numerically identical
    to what derive_recommended_action computes, but was written as a
    separate, hand-copied condition rather than calling the single source
    of truth — this version removes that duplication rather than leaving
    two definitions that could silently diverge if either rule ever
    changes.)

    Rule-level detail (which rules fired, conflicts, fallbacks) is NOT
    available this way — those aren't persisted to the database by design
    (see PHASE4_SUMMARY.md) — so those fields are explicitly None, not 0.
    """
    n = len(rows)
    notes = ["Rule frequency, multi-rule frequency, conflict frequency, and fallback frequency "
             "are NOT AVAILABLE from the database — that detail lives only in the audit log "
             "written during the run that produced these decisions, not in new ticket columns."]
    if n == 0:
        return RulesEvaluationReport(
            metric_provenance="REAL (derived from database)", n_processed=0,
            automated_rate=None, human_review_rate=None, urgent_human_review_rate=None,
            priority_distribution={}, decisions_by_category={},
            decisions_by_sentiment_bucket={}, decisions_by_confidence_bucket={},
            rule_frequency=None, multi_rule_frequency=None, conflict_frequency=None,
            fallback_frequency=None,
            notes=["No tickets have a Phase 4 decision in the database yet."],
        )

    automated = sum(1 for r in rows if r["decision_path"] == "Automated")
    human = n - automated
    urgent_human_review = sum(
        1 for r in rows
        if derive_recommended_action(r["decision_path"], r["final_priority"]) == "HUMAN_REVIEW_URGENT"
    )

    priority_dist = dict(Counter(r["final_priority"] for r in rows))
    category_breakdown = dict(Counter(r["ai_predicted_category"] or "(unclassified)" for r in rows))
    sentiment_breakdown = dict(Counter(_bucket_sentiment(r["sentiment_score"]) for r in rows))
    confidence_breakdown = dict(Counter(
        _bucket_confidence(r["classification_confidence"], confidence_threshold) for r in rows))

    return RulesEvaluationReport(
        metric_provenance="REAL (derived from database)",
        n_processed=n,
        automated_rate=automated / n,
        human_review_rate=human / n,
        urgent_human_review_rate=urgent_human_review / n,
        priority_distribution=priority_dist,
        decisions_by_category=category_breakdown,
        decisions_by_sentiment_bucket=sentiment_breakdown,
        decisions_by_confidence_bucket=confidence_breakdown,
        rule_frequency=None,
        multi_rule_frequency=None,
        conflict_frequency=None,
        fallback_frequency=None,
        notes=notes,
    )
