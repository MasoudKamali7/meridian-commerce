"""
Meridian Commerce — Phase 4: Rule Engine

Orchestrates every rule in `rules.py` against a `TicketContext` and produces
a single, deterministic `Decision`. The LLM never makes this call — it only
supplied the signals (category, confidence, sentiment) that the rules below
reason over.

PRECEDENCE — documented explicitly, per the Phase 4 brief:

  Priority: every priority rule (base category + any escalation rules that
  triggered) proposes an absolute priority FLOOR (Low/Medium/High/Urgent),
  never a relative "+1". The final priority is the single HIGHEST floor
  proposed by any triggered rule (using PRIORITY_ORDER as the ordinal
  ranking). This is deliberately order-independent: it doesn't matter which
  rule ran first, because max() of a set gives the same answer regardless of
  evaluation order — there is no ambiguous "which rule wins" case to argue
  about, which is exactly what a deterministic, auditable engine needs.

  Human review: every human-review rule contributes a plain
  forces_human_review=True/False. These are OR'd together — ANY single
  triggered rule is sufficient to require human review, full stop. There is
  no rule that can override another rule's "this needs a human" verdict; the
  system fails toward caution, never away from it.

  Fallback: if the input itself fails validation (out-of-range confidence/
  sentiment, an unapproved category slipping through, etc.), the engine
  NEVER crashes and NEVER defaults to Automated. It returns a hard-coded
  safe fallback Decision (Human Review, Medium priority, clearly flagged
  `is_fallback=True`) — see `safe_evaluate`.
"""

import logging
from typing import List

from ..config import PRIORITY_ORDER
from .models import Decision, RuleOutcome, TicketContext
from .rules import (
    rule_base_category_priority,
    rule_high_value_vip_order_priority,
    rule_low_confidence,
    rule_missing_classification,
    rule_missing_order_context,
    rule_sensitive_category,
    rule_sentiment_category_conflict,
    rule_strong_negative_sentiment_priority,
    rule_strong_negative_sentiment_review,
)

logger = logging.getLogger("meridian.rules")

FALLBACK_PRIORITY = "Medium"


def derive_recommended_action(decision_path: str, final_priority: str) -> str:
    """Pure function of exactly the two fields Phase 4 persists to the
    database (decision_path, final_priority) — nothing else feeds into it.
    That means recommended_action can be reconstructed EXACTLY from database
    rows after the fact, not just approximated — see
    evaluation/rules_metrics.py, which calls this same function rather than
    re-deriving the logic separately (avoids the two ever drifting apart)."""
    if decision_path == "Automated":
        return "AUTO_RESOLVE"
    if final_priority in ("Urgent", "High"):
        return "HUMAN_REVIEW_URGENT"
    return "HUMAN_REVIEW_STANDARD"


def _run_all_rules(ctx: TicketContext, low_confidence_threshold: float,
                    strong_negative_sentiment_threshold: float,
                    high_value_order_threshold: float = 450.0) -> List[RuleOutcome]:
    """Every rule, every time — no short-circuiting. This is what makes
    'which rules were even considered' auditable, not just 'which fired'."""
    return [
        rule_base_category_priority(ctx),
        rule_strong_negative_sentiment_priority(ctx, strong_negative_sentiment_threshold),
        rule_high_value_vip_order_priority(ctx, high_value_order_threshold),
        rule_missing_classification(ctx),
        rule_low_confidence(ctx, low_confidence_threshold),
        rule_sensitive_category(ctx),
        rule_strong_negative_sentiment_review(ctx, strong_negative_sentiment_threshold),
        rule_missing_order_context(ctx),
        rule_sentiment_category_conflict(ctx),
    ]


def evaluate(ctx: TicketContext, low_confidence_threshold: float = 0.75,
             strong_negative_sentiment_threshold: float = -0.7,
             high_value_order_threshold: float = 450.0) -> Decision:
    """Pure evaluation — assumes `ctx` is already a valid TicketContext.
    Use `safe_evaluate` at any integration boundary (pipeline/database) where
    the input hasn't already been validated."""
    outcomes = _run_all_rules(ctx, low_confidence_threshold, strong_negative_sentiment_threshold,
                               high_value_order_threshold)

    triggered = [o for o in outcomes if o.triggered]

    # --- Priority: take the single highest floor among triggered rules ---
    priority_floors = [o.priority_floor for o in triggered if o.priority_floor is not None]
    final_priority = max(priority_floors, key=lambda p: PRIORITY_ORDER[p]) if priority_floors else "Medium"

    # --- Human review: OR of every triggered rule's verdict ---
    forces_review = any(o.forces_human_review for o in triggered)
    decision_path = "Human Review" if forces_review else "Automated"

    conflicting_signals = any(o.is_conflict_signal for o in triggered)

    recommended_action = derive_recommended_action(decision_path, final_priority)

    return Decision(
        ticket_id=ctx.ticket_id,
        final_priority=final_priority,
        decision_path=decision_path,
        recommended_action=recommended_action,
        triggered_rules=[o.rule_name for o in triggered],
        reasons=[o.detail for o in triggered],
        conflicting_signals=conflicting_signals,
        is_fallback=False,
    )


def safe_evaluate(raw: dict, low_confidence_threshold: float = 0.75,
                   strong_negative_sentiment_threshold: float = -0.7,
                   high_value_order_threshold: float = 450.0) -> Decision:
    """Validates `raw` into a TicketContext and evaluates it. On ANY
    validation failure, returns a safe fallback decision instead of raising —
    a rule engine must always produce SOME decision, and that decision must
    never fail open to Automated. `raw` is typically a dict assembled from a
    database row (see database/tickets.py)."""
    ticket_id = raw.get("ticket_id")
    try:
        ctx = TicketContext.model_validate(raw)
    except Exception as e:
        logger.warning(f"Ticket {ticket_id}: falling back to safe default — invalid input: {e}",
                        extra={"event": "rules_fallback", "ticket_id": ticket_id})
        return Decision(
            ticket_id=ticket_id if isinstance(ticket_id, int) else -1,
            final_priority=FALLBACK_PRIORITY,
            decision_path="Human Review",
            recommended_action="HUMAN_REVIEW_STANDARD",
            triggered_rules=["fallback_invalid_input"],
            reasons=[f"Input validation failed, defaulted to safe human-review fallback: {e}"],
            conflicting_signals=False,
            is_fallback=True,
        )

    return evaluate(ctx, low_confidence_threshold, strong_negative_sentiment_threshold,
                     high_value_order_threshold)
