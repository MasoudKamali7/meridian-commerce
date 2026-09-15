"""
Meridian Commerce — Phase 4: Deterministic Rules

Each rule is a small, pure function: TicketContext -> RuleOutcome. Every
rule is ALWAYS evaluated (the engine never short-circuits), so the final
decision can honestly report every rule that was considered, not just the
first one that happened to fire — this is what makes "were there conflicting
signals" and "which rules fired" answerable rather than guessed.

Two kinds of rules:
  - Priority rules contribute a `priority_floor` (an absolute minimum
    priority level, not a relative "+1"). The engine combines them by taking
    the single highest floor across every triggered rule — see engine.py for
    why that's the deterministic, order-independent way to resolve several
    rules firing at once.
  - Human-review rules contribute `forces_human_review=True`. The engine
    OR's these together: ANY single one firing is enough to require a human,
    regardless of how many others did or didn't.

Threshold rationale is documented alongside each rule and centralized in
config.py (so a threshold is changed in exactly one place).
"""

from ..config import (
    CATEGORY_BASE_PRIORITY,
    ORDER_DEPENDENT_CATEGORIES,
    SENSITIVE_CATEGORIES,
)
from .models import RuleOutcome, TicketContext

# ----------------------------------------------------------------------------
# Priority rules
# ----------------------------------------------------------------------------

def rule_base_category_priority(ctx: TicketContext) -> RuleOutcome:
    """Every ticket gets a base priority from its (AI-predicted) category,
    using the same category->priority table Phase 2 used to generate the
    historical data — reused here for consistency of vocabulary, now serving
    as the deterministic starting point for a live decision rather than a
    fabrication rule.

    When there's no AI-predicted category yet (Phase 3 hasn't classified
    this ticket), there's no category signal to map from. Rather than
    guessing Low or High, this defaults to "Medium" — a deliberate, neutral
    placeholder reflecting genuine uncertainty. (Note: an unclassified
    ticket will separately be forced into Human Review by
    `rule_missing_classification` regardless of this default — see below.)
    """
    if ctx.ai_predicted_category is None:
        return RuleOutcome(
            rule_name="base_category_priority",
            triggered=True,
            detail="No AI-predicted category available; defaulting to Medium pending classification.",
            priority_floor="Medium",
        )
    base = CATEGORY_BASE_PRIORITY.get(ctx.ai_predicted_category, "Medium")
    return RuleOutcome(
        rule_name="base_category_priority",
        triggered=True,
        detail=f"Category '{ctx.ai_predicted_category}' maps to base priority '{base}'.",
        priority_floor=base,
    )


def rule_strong_negative_sentiment_priority(ctx: TicketContext, threshold: float) -> RuleOutcome:
    """A strongly upset customer deserves at least High priority regardless
    of which category the message falls into — sentiment can signal urgency
    that category alone misses (e.g. a furious "Product Question")."""
    if ctx.sentiment_score is not None and ctx.sentiment_score <= threshold:
        return RuleOutcome(
            rule_name="strong_negative_sentiment_priority",
            triggered=True,
            detail=f"sentiment_score={ctx.sentiment_score} <= {threshold}: raising priority floor to High.",
            priority_floor="High",
        )
    return RuleOutcome(
        rule_name="strong_negative_sentiment_priority", triggered=False,
        detail="Sentiment not strongly negative (or not available).",
    )


def rule_high_value_vip_order_priority(ctx: TicketContext, threshold: float) -> RuleOutcome:
    """A VIP customer's high-value order (~90th percentile of real order
    values, $450+) is treated as at least High priority — protecting the
    relationships and revenue that matter most, independent of category."""
    if (ctx.order_value is not None and ctx.order_value >= threshold
            and ctx.customer_segment == "VIP"):
        return RuleOutcome(
            rule_name="high_value_vip_order_priority",
            triggered=True,
            detail=f"VIP customer with order_value={ctx.order_value} >= {threshold}: raising priority floor to High.",
            priority_floor="High",
        )
    return RuleOutcome(
        rule_name="high_value_vip_order_priority", triggered=False,
        detail="Not a high-value VIP order (or order/segment data unavailable).",
    )


# ----------------------------------------------------------------------------
# Human-review rules
# ----------------------------------------------------------------------------

def rule_missing_classification(ctx: TicketContext) -> RuleOutcome:
    """Condition #4/#6 from the brief: missing critical information / can't
    safely determine an action. Without a category, there is nothing for
    any downstream rule to reason about."""
    if ctx.ai_predicted_category is None:
        return RuleOutcome(
            rule_name="missing_classification", triggered=True,
            detail="No AI classification available for this ticket yet.",
            forces_human_review=True,
        )
    return RuleOutcome(rule_name="missing_classification", triggered=False,
                        detail="AI classification is present.")


def rule_low_confidence(ctx: TicketContext, threshold: float) -> RuleOutcome:
    """Condition #1: insufficient AI classification confidence. Note
    (Phase 3 decision, preserved): this is the model's self-reported
    confidence, not a calibrated probability — the threshold is a
    deliberately conservative placeholder, not derived from measured
    accuracy, since no real evaluation data exists yet."""
    if ctx.ai_predicted_category is None:
        # Already covered by rule_missing_classification — avoid double
        # counting "no classification" as also "low confidence".
        return RuleOutcome(rule_name="low_confidence", triggered=False,
                            detail="No classification to assess confidence for.")
    if ctx.classification_confidence is None:
        return RuleOutcome(
            rule_name="low_confidence", triggered=True,
            detail="Classification present but no confidence score was recorded.",
            forces_human_review=True,
        )
    if ctx.classification_confidence < threshold:
        return RuleOutcome(
            rule_name="low_confidence", triggered=True,
            detail=f"classification_confidence={ctx.classification_confidence} < {threshold}.",
            forces_human_review=True,
        )
    return RuleOutcome(rule_name="low_confidence", triggered=False,
                        detail="Confidence meets the threshold.")


def rule_sensitive_category(ctx: TicketContext) -> RuleOutcome:
    """Condition #2: sensitive or high-risk ticket categories. Payment
    Problem and Account Problem carry financial/security/fraud risk;
    Complaint carries relationship/reputational risk. All three are judged
    too consequential to fully automate at this stage, regardless of
    confidence — a deliberately conservative starting posture."""
    if ctx.ai_predicted_category in SENSITIVE_CATEGORIES:
        return RuleOutcome(
            rule_name="sensitive_category", triggered=True,
            detail=f"Category '{ctx.ai_predicted_category}' is flagged as sensitive/high-risk.",
            forces_human_review=True,
        )
    return RuleOutcome(rule_name="sensitive_category", triggered=False,
                        detail="Category is not on the sensitive list.")


def rule_strong_negative_sentiment_review(ctx: TicketContext, threshold: float) -> RuleOutcome:
    """Condition #3: strongly negative sentiment. A very upset customer
    risks feeling dismissed by an automated response, independent of what
    category the message falls into."""
    if ctx.sentiment_score is not None and ctx.sentiment_score <= threshold:
        return RuleOutcome(
            rule_name="strong_negative_sentiment_review", triggered=True,
            detail=f"sentiment_score={ctx.sentiment_score} <= {threshold}.",
            forces_human_review=True,
        )
    return RuleOutcome(rule_name="strong_negative_sentiment_review", triggered=False,
                        detail="Sentiment not strongly negative (or not available).")


def rule_missing_order_context(ctx: TicketContext) -> RuleOutcome:
    """Condition #4/#5: missing critical information AND a conflicting
    signal — the category implies an order-specific issue, but no order is
    linked to verify against. (Confirmed against real data: e.g. 21 of the
    195 real 'Refund Request' tickets have no order_id — this isn't a
    hypothetical case.)"""
    if ctx.ai_predicted_category in ORDER_DEPENDENT_CATEGORIES and ctx.order_id is None:
        return RuleOutcome(
            rule_name="missing_order_context", triggered=True,
            detail=(f"Category '{ctx.ai_predicted_category}' is order-specific "
                    f"but no order_id is linked to this ticket."),
            forces_human_review=True,
            is_conflict_signal=True,
        )
    return RuleOutcome(rule_name="missing_order_context", triggered=False,
                        detail="Order context is consistent with the category (or not applicable).")


def rule_sentiment_category_conflict(ctx: TicketContext, positive_threshold: float = 0.3) -> RuleOutcome:
    """Condition #5: conflicting signals — a message classified as a
    Complaint but reading as positive in sentiment is contradictory enough
    to warrant a second look rather than an automated resolution."""
    if (ctx.ai_predicted_category == "Complaint"
            and ctx.sentiment_score is not None
            and ctx.sentiment_score > positive_threshold):
        return RuleOutcome(
            rule_name="sentiment_category_conflict", triggered=True,
            detail=(f"Category is 'Complaint' but sentiment_score={ctx.sentiment_score} "
                    f"> {positive_threshold} reads positive — signals conflict."),
            forces_human_review=True,
            is_conflict_signal=True,
        )
    return RuleOutcome(rule_name="sentiment_category_conflict", triggered=False,
                        detail="No category/sentiment conflict detected.")
