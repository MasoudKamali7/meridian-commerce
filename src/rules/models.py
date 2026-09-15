"""
Meridian Commerce — Phase 4: Rule Engine Data Models

`TicketContext` is the engine's ONLY input — a validated snapshot of exactly
the signals the rules are allowed to see. Building it from a raw DB row (or a
test fixture) is where invalid data gets caught, before any rule runs.

Design note: `TicketContext` deliberately does NOT include the historical
`priority` field or any LLM-guessed priority. Phase 4 computes
`final_priority` from scratch (category + sentiment + order context) — see
PHASE3_SUMMARY.md and PHASE4_SUMMARY.md for why neither historical nor
LLM-guessed priority is trusted as the operational value.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..config import APPROVED_CATEGORIES, APPROVED_PRIORITIES


class TicketContext(BaseModel):
    ticket_id: int

    # Phase 3 outputs — all Optional because, as of this project's real
    # database state, Phase 3 has not actually classified any ticket yet
    # (no LLM credentials were available). The engine must handle that
    # honestly, not assume it away.
    ai_predicted_category: Optional[str] = None
    classification_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sentiment_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)

    # Order / customer context (joined in from orders/customers — see
    # database/tickets.py). None when the ticket has no linked order.
    order_id: Optional[int] = None
    order_value: Optional[float] = Field(default=None, ge=0.0)
    customer_segment: Optional[str] = None

    @field_validator("ai_predicted_category")
    @classmethod
    def category_must_be_approved_or_none(cls, v):
        if v is not None and v not in APPROVED_CATEGORIES:
            raise ValueError(f"'{v}' is not an approved category")
        return v

    @field_validator("customer_segment")
    @classmethod
    def segment_must_be_known_or_none(cls, v):
        if v is not None and v not in ("New", "Returning", "VIP"):
            raise ValueError(f"'{v}' is not a known customer segment")
        return v


class RuleOutcome(BaseModel):
    """The result of evaluating a single rule. Always returned, even when
    `triggered=False` — this is what makes "which rules were even
    considered" auditable, not just "which ones fired"."""
    rule_name: str
    triggered: bool
    detail: str
    priority_floor: Optional[str] = None   # set only by priority-related rules
    forces_human_review: bool = False
    is_conflict_signal: bool = False       # True for rules specifically about conflicting/contradictory signals


class Decision(BaseModel):
    ticket_id: int
    final_priority: str
    decision_path: str                # "Automated" or "Human Review"
    recommended_action: str           # AUTO_RESOLVE / HUMAN_REVIEW_STANDARD / HUMAN_REVIEW_URGENT
    triggered_rules: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    conflicting_signals: bool = False
    is_fallback: bool = False         # True only when input validation failed and a safe default was used

    @field_validator("final_priority")
    @classmethod
    def priority_must_be_approved(cls, v):
        if v not in APPROVED_PRIORITIES:
            raise ValueError(f"'{v}' is not an approved priority")
        return v

    @field_validator("decision_path")
    @classmethod
    def decision_path_must_be_valid(cls, v):
        if v not in ("Automated", "Human Review"):
            raise ValueError(f"'{v}' is not a valid decision_path")
        return v
