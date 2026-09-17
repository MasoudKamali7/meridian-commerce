"""
Meridian Commerce — Phase 5: Response Decision Engine

Combines the deterministic eligibility ruling (eligibility.py) with the LLM
generation attempt (generator.py) into a single validated `ResponseDecision`.

DECISION TABLE — the whole of Phase 5's logic in one place:

  Phase 4 decision      Phase 5 eligibility    Generation      -> response_status
  ------------------------------------------------------------------------------
  (none yet)            no_phase4_decision     not attempted   -> NOT_ELIGIBLE
  Human Review          human_review           attempted*      -> HUMAN_REVIEW_DRAFT
  Automated             human_review**         attempted*      -> HUMAN_REVIEW_DRAFT
  Automated             automated_eligible     succeeded       -> DRAFT_GENERATED
  Automated             automated_eligible     failed/blocked  -> BLOCKED

   * For human-review cases the draft is INTERNAL ONLY (customer_facing=False)
     and is best-effort: if generation fails, the status stays
     HUMAN_REVIEW_DRAFT with response_draft=None. A human is handling the
     ticket either way, so a missing internal draft is an inconvenience, not
     a safety problem — whereas downgrading the status would misrepresent
     Phase 4's ruling.
  ** Phase 5's defense-in-depth re-verification disagreed with the stored
     decision_path; it fails safe toward human review (see eligibility.py).

BLOCKED is reserved for the genuinely notable case: Phase 4 authorized
automation, Phase 5 agreed, and generation still could not produce a safe
customer-facing draft (model declined, returned nothing, errored, or
produced text that failed the safety scan). That's the case worth surfacing
in evaluation as "automation was available but we couldn't safely use it."
"""

import logging
from typing import Optional

from .eligibility import check_response_eligibility
from .generator import ResponseGenerator
from .models import ResponseContext, ResponseDecision, category_to_response_type, derive_response_flags

logger = logging.getLogger("meridian.response")


def _build(ticket_id: int, status: str, response_type: Optional[str],
           draft: Optional[str], rationale: list, is_fallback: bool = False) -> ResponseDecision:
    customer_facing, requires_human_review = derive_response_flags(status)
    return ResponseDecision(
        ticket_id=ticket_id,
        response_status=status,
        response_type=response_type,
        response_draft=draft,
        customer_facing=customer_facing,
        requires_human_review=requires_human_review,
        rationale=rationale,
        is_fallback=is_fallback,
    )


def decide_response(ctx: ResponseContext, generator: Optional[ResponseGenerator],
                     low_confidence_threshold: float = 0.75,
                     strong_negative_sentiment_threshold: float = -0.7,
                     generate_internal_drafts: bool = True) -> ResponseDecision:
    """`generator` may be None to run eligibility-only (no LLM calls at all) —
    useful for evaluating the decision layer's routing behavior without
    requiring API access, which is exactly the situation this project is in."""
    response_type = category_to_response_type(ctx.ai_predicted_category)

    eligibility = check_response_eligibility(
        ctx, low_confidence_threshold, strong_negative_sentiment_threshold)

    # --- Phase 4 hasn't run: nothing for Phase 5 to act on ---
    if eligibility.outcome == "no_phase4_decision":
        return _build(ctx.ticket_id, "NOT_ELIGIBLE", response_type, None, eligibility.reasons)

    # --- Human review (Phase 4's ruling, or Phase 5 failing safe) ---
    if eligibility.outcome == "human_review":
        rationale = list(eligibility.reasons)
        draft = None
        if generate_internal_drafts and generator is not None:
            result = generator.generate(ctx, response_type)
            if result.success:
                draft = result.draft_text
                rationale.append("Internal draft generated for agent reference (not customer-facing).")
            else:
                rationale.append(f"Internal draft not produced ({result.failure}); "
                                 f"ticket still awaits human review regardless.")
        elif generator is None:
            rationale.append("Draft generation skipped (no generator configured).")
        return _build(ctx.ticket_id, "HUMAN_REVIEW_DRAFT", response_type, draft, rationale)

    # --- Automated and eligible: try to produce a customer-facing draft ---
    rationale = list(eligibility.reasons)
    if generator is None:
        rationale.append("Eligible for an automated response, but no generator was configured, "
                         "so no customer-facing draft was produced.")
        return _build(ctx.ticket_id, "BLOCKED", response_type, None, rationale)

    result = generator.generate(ctx, response_type)
    if result.success:
        rationale.append("Draft generated and passed the response safety scan.")
        return _build(ctx.ticket_id, "DRAFT_GENERATED", response_type, result.draft_text, rationale)

    if result.failure == "safety_violation":
        codes = sorted({code for code, _ in result.safety_violations})
        rationale.append(f"Draft was generated but BLOCKED by the safety scan: {', '.join(codes)}. "
                         f"The offending text is deliberately not retained.")
    elif result.failure == "model_declined":
        missing = ", ".join(result.missing_information) if result.missing_information else "unspecified"
        rationale.append(f"No draft produced — insufficient grounded context (missing: {missing}).")
    else:
        rationale.append(f"No draft produced — generation failed ({result.failure}).")

    return _build(ctx.ticket_id, "BLOCKED", response_type, None, rationale)


def safe_decide_response(raw: dict, generator: Optional[ResponseGenerator],
                          low_confidence_threshold: float = 0.75,
                          strong_negative_sentiment_threshold: float = -0.7,
                          generate_internal_drafts: bool = True) -> ResponseDecision:
    """Validates `raw` into a ResponseContext and decides. On ANY validation
    failure returns a safe fallback (NOT_ELIGIBLE, no draft, flagged
    is_fallback) rather than raising — mirroring Phase 4's `safe_evaluate`.

    NOT_ELIGIBLE is the right fallback status here rather than BLOCKED: we
    could not even establish what this ticket is, so claiming automation was
    "available but blocked" would overstate what we know. Either way no
    customer-facing text is produced."""
    ticket_id = raw.get("ticket_id")
    try:
        ctx = ResponseContext.model_validate(raw)
    except Exception as e:
        logger.warning(f"Ticket {ticket_id}: response decision fell back — invalid input: {e}",
                        extra={"event": "response_fallback", "ticket_id": ticket_id})
        return _build(
            ticket_id if isinstance(ticket_id, int) else -1,
            "NOT_ELIGIBLE", None, None,
            [f"Input validation failed, defaulted to safe NOT_ELIGIBLE fallback: {e}"],
            is_fallback=True,
        )

    return decide_response(ctx, generator, low_confidence_threshold,
                            strong_negative_sentiment_threshold, generate_internal_drafts)
