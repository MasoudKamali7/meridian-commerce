"""
Unit tests for Phase 5's response models and the deterministic safety
scanner. Pure logic — no database, no LLM, no network.
"""

import pytest
from pydantic import ValidationError

from src.config import APPROVED_CATEGORIES
from src.response.models import (
    APPROVED_RESPONSE_STATUSES,
    APPROVED_RESPONSE_TYPES,
    ResponseContext,
    ResponseDecision,
    category_to_response_type,
    derive_response_flags,
)
from src.response.safety import scan_for_forbidden_claims


# ----------------------------------------------------------------------------
# Valid / invalid response model
# ----------------------------------------------------------------------------
def test_valid_response_decision_constructs():
    d = ResponseDecision(ticket_id=1, response_status="DRAFT_GENERATED",
                          response_type="ORDER_STATUS", response_draft="Your order is on the way.",
                          customer_facing=True, requires_human_review=False)
    assert d.response_status == "DRAFT_GENERATED"
    assert d.customer_facing is True
    assert d.generated_at is not None


def test_invalid_response_status_is_rejected():
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status="MADE_UP_STATUS",
                          customer_facing=False, requires_human_review=False)


def test_invalid_response_type_is_rejected():
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status="NOT_ELIGIBLE",
                          response_type="NOT_A_REAL_TYPE",
                          customer_facing=False, requires_human_review=False)


def test_flags_inconsistent_with_status_are_rejected():
    """DRAFT_GENERATED means customer-facing by definition — constructing one
    that isn't must be impossible, not merely discouraged."""
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status="DRAFT_GENERATED",
                          response_draft="text", customer_facing=False, requires_human_review=False)


def test_human_review_draft_cannot_be_customer_facing():
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status="HUMAN_REVIEW_DRAFT",
                          response_draft="internal note", customer_facing=True,
                          requires_human_review=True)


def test_draft_generated_requires_non_empty_draft():
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status="DRAFT_GENERATED", response_draft=None,
                          customer_facing=True, requires_human_review=False)


@pytest.mark.parametrize("status", ["BLOCKED", "NOT_ELIGIBLE"])
def test_blocked_and_not_eligible_must_not_carry_a_draft(status):
    """A blocked draft is exactly the text that failed the safety scan —
    persisting it would defeat the block."""
    facing, review = derive_response_flags(status)
    with pytest.raises(ValidationError):
        ResponseDecision(ticket_id=1, response_status=status, response_draft="leaked text",
                          customer_facing=facing, requires_human_review=review)


def test_human_review_draft_may_have_no_draft():
    """Internal drafts are best-effort — a human handles the ticket either way."""
    d = ResponseDecision(ticket_id=1, response_status="HUMAN_REVIEW_DRAFT", response_draft=None,
                          customer_facing=False, requires_human_review=True)
    assert d.response_draft is None


# ----------------------------------------------------------------------------
# Derived flags & response type mapping
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("status,expected", [
    ("DRAFT_GENERATED", (True, False)),
    ("HUMAN_REVIEW_DRAFT", (False, True)),
    ("BLOCKED", (False, True)),
    ("NOT_ELIGIBLE", (False, False)),
])
def test_derive_response_flags(status, expected):
    assert derive_response_flags(status) == expected


def test_every_approved_category_maps_to_an_approved_response_type():
    for category in APPROVED_CATEGORIES:
        rt = category_to_response_type(category)
        assert rt in APPROVED_RESPONSE_TYPES, f"{category} -> {rt} is not approved"


def test_missing_category_yields_no_response_type():
    """A ticket routed to human review BECAUSE classification is missing has
    no determinable response purpose — None, not a guessed default."""
    assert category_to_response_type(None) is None


def test_sensitive_categories_map_to_their_own_response_types():
    assert category_to_response_type("Payment Problem") == "PAYMENT_SUPPORT"
    assert category_to_response_type("Account Problem") == "ACCOUNT_SUPPORT"
    assert category_to_response_type("Complaint") == "COMPLAINT"


def test_refund_request_maps_to_refund_support_not_an_action():
    """REFUND_SUPPORT names the response PURPOSE — it must never be taken to
    mean a refund was issued. Guarded here as documentation-in-code."""
    assert category_to_response_type("Refund Request") == "REFUND_SUPPORT"


# ----------------------------------------------------------------------------
# ResponseContext validation
# ----------------------------------------------------------------------------
def test_response_context_rejects_unapproved_category():
    with pytest.raises(ValidationError):
        ResponseContext(ticket_id=1, message_text="hi", ai_predicted_category="Nope")


def test_response_context_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        ResponseContext(ticket_id=1, message_text="hi", classification_confidence=1.5)


def test_response_context_rejects_invalid_decision_path():
    with pytest.raises(ValidationError):
        ResponseContext(ticket_id=1, message_text="hi", decision_path="Maybe")


# ----------------------------------------------------------------------------
# Hallucination-prevention safety scanner
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Thanks for reaching out. Your order is currently marked as Delayed, and we appreciate your patience.",
    "To look into this further, could you confirm the order number associated with your request?",
    "Your refund request has been received and is under review by our team.",
    "Your refund is being reviewed and we'll follow up once there's an update.",
    "I have received your message and passed it to the right team.",
])
def test_safe_responses_pass_the_scan(text):
    assert scan_for_forbidden_claims(text) == []


@pytest.mark.parametrize("text,expected_reason", [
    ("Your refund has been processed and the funds will appear shortly.", "refund_claimed_or_promised"),
    ("We have issued a refund to your original payment method.", "refund_claimed_or_promised"),
    ("Your payment has been reversed.", "payment_reversal_claimed"),
    ("As an apology, a discount will be applied to your next order.", "compensation_promised"),
    ("Your account has been updated with the correct details.", "account_change_claimed"),
    ("Your order has been cancelled as requested.", "shipment_or_order_change_claimed"),
    ("I have processed your request already.", "action_performed_claimed"),
    ("As an AI, I can help with that.", "internal_architecture_mentioned"),
    ("Our classification model gave this a high confidence score.", "internal_architecture_mentioned"),
])
def test_forbidden_claims_are_caught(text, expected_reason):
    violations = scan_for_forbidden_claims(text)
    assert violations, f"Expected a violation for: {text}"
    assert expected_reason in [reason for reason, _ in violations]


def test_scanner_handles_empty_and_none_input_without_raising():
    assert scan_for_forbidden_claims("") == []
    assert scan_for_forbidden_claims(None) == []
