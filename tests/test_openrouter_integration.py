"""
Phase 3 and Phase 5 running on the REAL OpenRouterLLMClient, with only the
network boundary faked (FakeOpenAI). Proves both LLM phases use OpenRouter
end-to-end while every existing guarantee still holds: Pydantic validation in
Phase 3, Phase 4 authority, the deterministic safety scan, and the
ResponseDecision invariants in Phase 5. Offline, no real key.
"""

import copy

import pytest

from src.ai.classifier import TicketClassifier
from src.ai.llm_client import OpenRouterLLMClient
from src.ai.prompts import CLASSIFY_TICKET_TOOL
from src.response.engine import decide_response
from src.response.generator import ResponseGenerator
from src.response.models import ResponseContext, ResponseDecision
from src.response.prompts import DRAFT_RESPONSE_TOOL
from src.response.safety import scan_for_forbidden_claims

from .conftest import VALID_TOOL_INPUT
from .openrouter_fakes import (
    TEST_KEY,
    install_fake_openai,
    text_only_response,
    timeout_error,
    tool_call_response,
)

CONF, SENT = 0.75, -0.7
SAFE_REFUND_ACK = "Your refund request has been received and is under review."


def openrouter_client(max_retries=1):
    return OpenRouterLLMClient(api_key=TEST_KEY, model="openrouter/free",
                               max_tokens=512, timeout_seconds=5, max_retries=max_retries)


def ctx(**overrides):
    base = dict(ticket_id=1, message_text="Where is my order?", decision_path="Automated",
                final_priority="Low", ai_predicted_category="Order Status Inquiry",
                classification_confidence=0.95, sentiment_score=0.1, order_id=10,
                order_status="Delayed", customer_segment="Returning")
    base.update(overrides)
    return ResponseContext(**base)


# ---------------------------------------------------------------------------
# Phase 3 — classification over OpenRouter
# ---------------------------------------------------------------------------
def test_phase3_classifies_through_openrouter(monkeypatch):
    latest = install_fake_openai(monkeypatch, [tool_call_response("classify_ticket", VALID_TOOL_INPUT)])
    result = TicketClassifier(openrouter_client()).classify(1, "I want a refund please.")

    assert result.success is True
    assert result.validated.category == "Refund Request"
    assert result.input_tokens == 120 and result.output_tokens == 45
    call = latest().calls[0]
    assert call["tool_choice"]["function"]["name"] == "classify_ticket"
    assert call["tools"][0]["function"]["parameters"] == CLASSIFY_TICKET_TOOL["input_schema"]
    assert latest().init_kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_phase3_pydantic_validation_still_rejects_bad_model_output(monkeypatch):
    bad = copy.deepcopy(VALID_TOOL_INPUT)
    bad["category"] = "Totally Made Up"
    install_fake_openai(monkeypatch, [tool_call_response("classify_ticket", bad)])
    result = TicketClassifier(openrouter_client()).classify(2, "test")
    assert result.success is False
    assert result.error_type == "invalid_category"
    assert result.validated is None


def test_phase3_malformed_openrouter_reply_is_a_failed_result_not_a_crash(monkeypatch):
    install_fake_openai(monkeypatch, [text_only_response()])
    result = TicketClassifier(openrouter_client()).classify(3, "test")
    assert result.success is False
    assert result.error_type == "malformed_response"


def test_phase3_timeout_is_a_failed_result(monkeypatch):
    install_fake_openai(monkeypatch, [timeout_error()])
    result = TicketClassifier(openrouter_client()).classify(4, "test")
    assert result.success is False
    assert result.error_type == "timeout"


# ---------------------------------------------------------------------------
# Phase 5 — response drafting over OpenRouter
# ---------------------------------------------------------------------------
def draft(text):
    return tool_call_response("draft_support_response", {"can_generate": True, "draft_text": text})


def test_phase5_generates_a_customer_facing_draft_through_openrouter(monkeypatch):
    good = ("Thanks for getting in touch. Your order is currently marked as Delayed, "
            "and we're sorry for the wait.")
    latest = install_fake_openai(monkeypatch, [draft(good)])
    d = decide_response(ctx(), ResponseGenerator(openrouter_client()), CONF, SENT)

    assert d.response_status == "DRAFT_GENERATED"
    assert d.customer_facing is True and d.requires_human_review is False
    assert d.response_draft == good
    call = latest().calls[0]
    assert call["tool_choice"]["function"]["name"] == "draft_support_response"
    assert call["tools"][0]["function"]["parameters"] == DRAFT_RESPONSE_TOOL["input_schema"]


def test_phase5_false_refund_claim_is_blocked_and_discarded(monkeypatch):
    unsafe = "Good news, your refund has been processed and will arrive shortly."
    install_fake_openai(monkeypatch, [draft(unsafe)])
    d = decide_response(ctx(ai_predicted_category="Refund Request"),
                        ResponseGenerator(openrouter_client()), CONF, SENT)

    assert d.response_status == "BLOCKED"
    assert d.customer_facing is False
    assert d.response_draft is None
    assert unsafe not in " ".join(d.rationale)
    assert any("refund_claimed_or_promised" in r for r in d.rationale)


def test_phase5_legitimate_refund_acknowledgement_is_not_a_false_positive(monkeypatch):
    install_fake_openai(monkeypatch, [draft(SAFE_REFUND_ACK)])
    d = decide_response(ctx(ai_predicted_category="Refund Request"),
                        ResponseGenerator(openrouter_client()), CONF, SENT)
    assert d.response_status == "DRAFT_GENERATED"
    assert d.response_draft == SAFE_REFUND_ACK


def test_phase5_ai_internals_leak_is_blocked(monkeypatch):
    install_fake_openai(monkeypatch, [draft("As an AI language model, I think your order is late.")])
    d = decide_response(ctx(), ResponseGenerator(openrouter_client()), CONF, SENT)
    assert d.response_status == "BLOCKED"
    assert d.response_draft is None


def test_phase5_never_overrides_phase4_human_review(monkeypatch):
    install_fake_openai(monkeypatch, [draft("Thanks, we are looking into this for you.")])
    d = decide_response(ctx(decision_path="Human Review", ai_predicted_category="Complaint"),
                        ResponseGenerator(openrouter_client()), CONF, SENT)
    assert d.response_status == "HUMAN_REVIEW_DRAFT"
    assert d.customer_facing is False and d.requires_human_review is True


def test_phase5_openrouter_timeout_blocks_instead_of_inventing_text(monkeypatch):
    install_fake_openai(monkeypatch, [timeout_error()])
    d = decide_response(ctx(), ResponseGenerator(openrouter_client()), CONF, SENT)
    assert d.response_status == "BLOCKED"
    assert d.response_draft is None
    assert any("timeout" in r for r in d.rationale)


def test_phase5_no_phase4_decision_is_not_eligible_and_makes_no_openrouter_call(monkeypatch):
    latest = install_fake_openai(monkeypatch, [])
    d = decide_response(ResponseContext(ticket_id=5, message_text="hi", decision_path=None),
                        ResponseGenerator(openrouter_client()), CONF, SENT)
    assert d.response_status == "NOT_ELIGIBLE"
    assert latest().calls == []


# ---------------------------------------------------------------------------
# Safety invariants (provider-independent, re-asserted after the migration)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,code", [
    ("Your refund has been issued.", "refund_claimed_or_promised"),
    ("Your payment has been reversed.", "payment_reversal_claimed"),
    ("Your account has been updated with the new email.", "account_change_claimed"),
    ("Your order has been cancelled as requested.", "shipment_or_order_change_claimed"),
    ("We have processed your request.", "action_performed_claimed"),
    ("Our language model reviewed this.", "internal_architecture_mentioned"),
])
def test_scanner_blocks_completed_action_claims(text, code):
    assert code in {c for c, _ in scan_for_forbidden_claims(text)}


def test_scanner_allows_the_refund_request_received_phrase():
    assert scan_for_forbidden_claims(SAFE_REFUND_ACK) == []


def test_response_decision_invariants_still_enforced():
    with pytest.raises(ValueError):
        ResponseDecision(ticket_id=1, response_status="DRAFT_GENERATED", response_draft="x",
                         customer_facing=False, requires_human_review=False)
    with pytest.raises(ValueError):
        ResponseDecision(ticket_id=1, response_status="BLOCKED", response_draft="leaked",
                         customer_facing=False, requires_human_review=True)
