"""
Meridian Commerce — Phase 5: Response Eligibility

Phase 4 is authoritative for the automate-vs-human-review decision — this
module does NOT compete with it or re-decide it. What it does is a
defense-in-depth RE-VERIFICATION: decision_path == "Automated" already
implies (by construction of Phase 4's rule engine) that classification
exists, confidence met the threshold, the category isn't sensitive, sentiment
isn't strongly negative, and no order-context conflict exists — because any
one of those would have forced Human Review instead. This module checks
those same conditions again at the Phase 5 boundary rather than blindly
trusting a stored column, the same way Phase 4 re-validates a database row
with `TicketContext` rather than trusting it was written correctly.

Three possible outcomes, matching the Phase 5 brief's two categories (A/B)
plus the precondition Phase 4 must exist at all:

  "no_phase4_decision"   -> Phase 4 hasn't processed this ticket yet.
                             response_status will be NOT_ELIGIBLE.
  "human_review"         -> Phase 4 said Human Review. Phase 5 must respect
                             it — response_status will be HUMAN_REVIEW_DRAFT.
  "automated_eligible"   -> Phase 4 said Automated AND Phase 5's own
                             re-verification agrees. response_status becomes
                             DRAFT_GENERATED if generation then succeeds, or
                             BLOCKED if it doesn't.
"""

from dataclasses import dataclass, field
from typing import List

from ..config import ORDER_DEPENDENT_CATEGORIES, SENSITIVE_CATEGORIES
from .models import ResponseContext


@dataclass
class EligibilityResult:
    outcome: str   # "no_phase4_decision" / "human_review" / "automated_eligible"
    reasons: List[str] = field(default_factory=list)


def check_response_eligibility(ctx: ResponseContext, low_confidence_threshold: float,
                                strong_negative_sentiment_threshold: float) -> EligibilityResult:
    if ctx.decision_path is None:
        return EligibilityResult(
            outcome="no_phase4_decision",
            reasons=["No Phase 4 decision exists yet for this ticket."],
        )

    if ctx.decision_path == "Human Review":
        return EligibilityResult(
            outcome="human_review",
            reasons=["Phase 4 decision_path is 'Human Review' — Phase 5 respects this decision "
                     "and will not produce a customer-facing response."],
        )

    # decision_path == "Automated" from here on — re-verify, don't just trust.
    reasons_ok = []
    problems = []

    if ctx.ai_predicted_category is None:
        problems.append("classification is missing (unexpected: decision_path is Automated).")
    else:
        reasons_ok.append(f"classification present ({ctx.ai_predicted_category}).")

    if ctx.classification_confidence is None:
        problems.append("classification_confidence is missing.")
    elif ctx.classification_confidence < low_confidence_threshold:
        problems.append(f"classification_confidence {ctx.classification_confidence} is below "
                         f"the {low_confidence_threshold} threshold.")
    else:
        reasons_ok.append(f"confidence {ctx.classification_confidence} meets threshold.")

    if ctx.ai_predicted_category in SENSITIVE_CATEGORIES:
        problems.append(f"category '{ctx.ai_predicted_category}' is sensitive.")

    if (ctx.sentiment_score is not None
            and ctx.sentiment_score <= strong_negative_sentiment_threshold):
        problems.append(f"sentiment_score {ctx.sentiment_score} is strongly negative.")

    if ctx.ai_predicted_category in ORDER_DEPENDENT_CATEGORIES and ctx.order_id is None:
        problems.append(f"category '{ctx.ai_predicted_category}' requires order context, "
                         f"but no order is linked.")
    elif ctx.order_id is not None:
        reasons_ok.append("required order context is present.")

    if problems:
        # Defense-in-depth caught something inconsistent with decision_path
        # == "Automated". Fail safe: treat exactly like Human Review rather
        # than trusting the (apparently stale or inconsistent) stored value.
        return EligibilityResult(
            outcome="human_review",
            reasons=(["Phase 4 says Automated, but Phase 5's re-verification found a "
                       "safety concern — failing safe to human review:"] + problems),
        )

    return EligibilityResult(outcome="automated_eligible", reasons=reasons_ok)
