"""
Meridian Commerce — Phase 5: Response Decision Models

Mirrors Phase 4's models.py pattern deliberately: plain `str` fields +
`field_validator` membership checks against module-level approved-value
lists (not native Python Enums), for consistency with `rules/models.py`.

Terminology choice: the brief's example statuses (NOT_ELIGIBLE,
DRAFT_GENERATED, HUMAN_REVIEW_DRAFT, BLOCKED) are used as-is — they map
cleanly onto this system's actual decision tree (see engine.py) and there
was no existing terminology in Phases 1–4 they'd conflict with. Kept
unchanged rather than substituted for the sake of it.
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import APPROVED_CATEGORIES

# ----------------------------------------------------------------------------
# Controlled vocabularies
# ----------------------------------------------------------------------------
APPROVED_RESPONSE_STATUSES = ["NOT_ELIGIBLE", "DRAFT_GENERATED", "HUMAN_REVIEW_DRAFT", "BLOCKED"]

APPROVED_RESPONSE_TYPES = [
    "ORDER_STATUS", "PRODUCT_QUESTION", "PAYMENT_SUPPORT", "ACCOUNT_SUPPORT",
    "REFUND_SUPPORT", "ORDER_ISSUE", "COMPLAINT", "GENERAL_SUPPORT",
]

# Category -> response type. Mostly the brief's example list; one addition
# beyond it, documented here rather than silently invented:
#   ORDER_ISSUE (new) covers Missing Item / Damaged Product. Neither fits
#   REFUND_SUPPORT cleanly — that would presuppose the resolution is a
#   refund, which Phase 5 has no authority to imply (response_type describes
#   response PURPOSE, not an outcome). ORDER_ISSUE names the purpose
#   ("something's wrong with what arrived") without presupposing how it
#   gets resolved.
CATEGORY_TO_RESPONSE_TYPE = {
    "Order Status Inquiry": "ORDER_STATUS",
    "Delivery Delay": "ORDER_STATUS",
    "Product Question": "PRODUCT_QUESTION",
    "Payment Problem": "PAYMENT_SUPPORT",
    "Account Problem": "ACCOUNT_SUPPORT",
    "Refund Request": "REFUND_SUPPORT",
    "Missing Item": "ORDER_ISSUE",
    "Damaged Product": "ORDER_ISSUE",
    "Complaint": "COMPLAINT",
    "Other": "GENERAL_SUPPORT",
}
assert set(CATEGORY_TO_RESPONSE_TYPE.keys()) == set(APPROVED_CATEGORIES), \
    "Every approved ticket category must map to a response type."


def category_to_response_type(category: Optional[str]) -> Optional[str]:
    """None in, None out — a ticket with no AI classification yet has no
    determinable response purpose either. This is a real, common case: a
    ticket can be routed to Human Review by Phase 4 PRECISELY BECAUSE
    classification is missing, in which case a Phase 4 decision exists but
    category (and therefore response_type) still doesn't."""
    if category is None:
        return None
    return CATEGORY_TO_RESPONSE_TYPE[category]


def derive_response_flags(response_status: str) -> tuple:
    """Pure function of response_status alone — see sql/07_phase5_schema.sql
    for why customer_facing/requires_human_review are NOT persisted columns.
    Returns (customer_facing, requires_human_review)."""
    return {
        "DRAFT_GENERATED": (True, False),
        "HUMAN_REVIEW_DRAFT": (False, True),
        "BLOCKED": (False, True),
        "NOT_ELIGIBLE": (False, False),
    }[response_status]


# ----------------------------------------------------------------------------
# Input context — everything Phase 5 is allowed to reason over
# ----------------------------------------------------------------------------
class ResponseContext(BaseModel):
    """What Phase 5 sees. Deliberately narrow: message text, Phase 3
    outputs, Phase 4's decision, and the minimum order/product context
    needed to ground a response — never raw customer PII (name/email/phone),
    payment details, or anything not listed in the Phase 5 brief's own
    'potential context' list."""
    ticket_id: int
    message_text: str

    # Phase 3 outputs (may be None — see category_to_response_type above)
    ai_predicted_category: Optional[str] = None
    classification_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sentiment_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)

    # Phase 4 decision — Phase 5 reads this, never recomputes it
    decision_path: Optional[str] = None      # None means Phase 4 hasn't run for this ticket yet
    final_priority: Optional[str] = None

    # Minimal order/product grounding (factual, never fabricated by the LLM)
    order_id: Optional[int] = None
    order_status: Optional[str] = None
    order_value: Optional[float] = Field(default=None, ge=0.0)
    expected_delivery_date: Optional[str] = None   # ISO date string or None
    actual_delivery_date: Optional[str] = None
    product_names: Optional[str] = None            # comma-joined, or None

    customer_segment: Optional[str] = None

    @field_validator("ai_predicted_category")
    @classmethod
    def category_must_be_approved_or_none(cls, v):
        if v is not None and v not in APPROVED_CATEGORIES:
            raise ValueError(f"'{v}' is not an approved category")
        return v

    @field_validator("decision_path")
    @classmethod
    def decision_path_must_be_valid_or_none(cls, v):
        if v is not None and v not in ("Automated", "Human Review"):
            raise ValueError(f"'{v}' is not a valid decision_path")
        return v


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
class ResponseDecision(BaseModel):
    ticket_id: int
    response_status: str
    response_type: Optional[str] = None
    response_draft: Optional[str] = None
    customer_facing: bool
    requires_human_review: bool
    rationale: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_fallback: bool = False   # True only when input validation failed and a safe default was used

    @field_validator("response_status")
    @classmethod
    def status_must_be_approved(cls, v):
        if v not in APPROVED_RESPONSE_STATUSES:
            raise ValueError(f"'{v}' is not an approved response_status")
        return v

    @field_validator("response_type")
    @classmethod
    def type_must_be_approved_or_none(cls, v):
        if v is not None and v not in APPROVED_RESPONSE_TYPES:
            raise ValueError(f"'{v}' is not an approved response_type")
        return v

    @model_validator(mode="after")
    def flags_must_match_status(self):
        """Structurally impossible to construct an inconsistent decision —
        e.g. DRAFT_GENERATED with customer_facing=False. This is the same
        kind of invariant Phase 4.1 wished it had enforced at the type level
        for recommended_action instead of leaving it as a convention two
        code paths had to independently honor."""
        expected_facing, expected_review = derive_response_flags(self.response_status)
        if self.customer_facing != expected_facing or self.requires_human_review != expected_review:
            raise ValueError(
                f"customer_facing/requires_human_review ({self.customer_facing}, "
                f"{self.requires_human_review}) don't match what response_status "
                f"'{self.response_status}' requires ({expected_facing}, {expected_review})"
            )
        if self.response_status == "DRAFT_GENERATED" and not self.response_draft:
            raise ValueError("DRAFT_GENERATED requires a non-empty response_draft")
        if self.response_status in ("BLOCKED", "NOT_ELIGIBLE") and self.response_draft:
            raise ValueError(f"{self.response_status} must not carry a response_draft")
        return self
