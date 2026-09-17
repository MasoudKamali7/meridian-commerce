"""
Unit tests for the Phase 5 response decision engine — eligibility routing,
generation handling, and the safety guarantees around what can ever become
customer-facing. Uses a FakeLLMClient throughout: no API key, no network.
"""

import pytest

from src.ai.llm_client import LLMClientError, LLMResponse, LLMTimeoutError
from src.response.engine import decide_response, safe_decide_response
from src.response.generator import ResponseGenerator
from src.response.models import ResponseContext

CONF = 0.75
SENT = -0.7


class FakeResponseLLMClient:
    """Implements the same interface AnthropicLLMClient does (Phase 3's
    abstraction), returning a canned tool_input or raising a canned error."""

    def __init__(self, tool_input=None, error=None):
        self._tool_input = tool_input
        self._error = error
        self.call_count = 0
        self.last_user_prompt = None
        self.last_system_prompt = None

    def classify(self, system_prompt, user_prompt, tool_schema):
        self.call_count += 1
        self.last_user_prompt = user_prompt
        self.last_system_prompt = system_prompt
        if self._error is not None:
            raise self._error
        return LLMResponse(tool_input=self._tool_input, input_tokens=100, output_tokens=40,
                            latency_ms=120.0, raw_stop_reason="tool_use")

    def generate_structured(self, system_prompt, user_prompt, tool_schema):
        return self.classify(system_prompt, user_prompt, tool_schema)


GOOD_DRAFT = {"can_generate": True,
              "draft_text": "Thanks for getting in touch. Your order is currently marked as Delayed, "
                             "and we're sorry for the wait. We'll update you as soon as it moves."}
UNSAFE_DRAFT = {"can_generate": True,
                "draft_text": "Good news — your refund has been processed and will arrive shortly."}
DECLINED = {"can_generate": False, "missing_information": ["order number"]}


def automated_ctx(**overrides):
    base = dict(ticket_id=1, message_text="Where is my order?", decision_path="Automated",
                final_priority="Low", ai_predicted_category="Order Status Inquiry",
                classification_confidence=0.95, sentiment_score=0.1, order_id=10,
                order_status="Delayed", customer_segment="Returning")
    base.update(overrides)
    return ResponseContext(**base)


# ----------------------------------------------------------------------------
# Automated eligibility -> customer-facing draft
# ----------------------------------------------------------------------------
def test_automated_eligible_with_good_draft_becomes_customer_facing():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "DRAFT_GENERATED"
    assert d.customer_facing is True
    assert d.requires_human_review is False
    assert d.response_draft == GOOD_DRAFT["draft_text"]
    assert d.response_type == "ORDER_STATUS"


def test_unsafe_draft_is_blocked_and_text_is_not_retained():
    """The single most important safety test in Phase 5: a draft that fails
    the scan must never reach the customer AND must not be persisted."""
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=UNSAFE_DRAFT))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "BLOCKED"
    assert d.customer_facing is False
    assert d.response_draft is None                      # text deliberately discarded
    assert UNSAFE_DRAFT["draft_text"] not in " ".join(d.rationale)
    assert any("refund_claimed_or_promised" in r for r in d.rationale)


def test_model_declining_to_generate_results_in_blocked_not_a_partial_draft():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=DECLINED))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "BLOCKED"
    assert d.response_draft is None
    assert any("order number" in r for r in d.rationale)


def test_llm_error_results_in_blocked_never_a_customer_facing_response():
    gen = ResponseGenerator(FakeResponseLLMClient(error=LLMTimeoutError("timed out")))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "BLOCKED"
    assert d.customer_facing is False


def test_empty_draft_text_is_blocked():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input={"can_generate": True, "draft_text": "   "}))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "BLOCKED"


def test_malformed_tool_output_is_blocked():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input={"unexpected": "shape"}))
    d = decide_response(automated_ctx(), gen, CONF, SENT)

    assert d.response_status == "BLOCKED"


# ----------------------------------------------------------------------------
# Human review — Phase 4 is authoritative
# ----------------------------------------------------------------------------
def test_phase4_human_review_is_respected_and_draft_is_internal_only():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    ctx = automated_ctx(decision_path="Human Review", ai_predicted_category="Complaint")
    d = decide_response(ctx, gen, CONF, SENT)

    assert d.response_status == "HUMAN_REVIEW_DRAFT"
    assert d.customer_facing is False       # never customer-facing, even though the draft is fine
    assert d.requires_human_review is True
    assert d.response_draft == GOOD_DRAFT["draft_text"]   # internal agent reference


def test_internal_draft_generation_can_be_disabled():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    ctx = automated_ctx(decision_path="Human Review")
    d = decide_response(ctx, gen, CONF, SENT, generate_internal_drafts=False)

    assert d.response_status == "HUMAN_REVIEW_DRAFT"
    assert d.response_draft is None
    assert gen._llm_client.call_count == 0   # no LLM call wasted


def test_human_review_stays_human_review_even_if_internal_draft_fails():
    gen = ResponseGenerator(FakeResponseLLMClient(error=LLMTimeoutError("timed out")))
    ctx = automated_ctx(decision_path="Human Review")
    d = decide_response(ctx, gen, CONF, SENT)

    assert d.response_status == "HUMAN_REVIEW_DRAFT"   # not downgraded to BLOCKED
    assert d.response_draft is None


# ----------------------------------------------------------------------------
# Defense-in-depth re-verification (Phase 5 fails safe, never fails open)
# ----------------------------------------------------------------------------
def test_missing_classification_never_produces_customer_facing_response():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    ctx = automated_ctx(ai_predicted_category=None, classification_confidence=None)
    d = decide_response(ctx, gen, CONF, SENT)

    assert d.customer_facing is False
    assert d.response_status == "HUMAN_REVIEW_DRAFT"


def test_low_confidence_never_produces_customer_facing_response():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    d = decide_response(automated_ctx(classification_confidence=0.4), gen, CONF, SENT)

    assert d.customer_facing is False
    assert any("below the 0.75 threshold" in r for r in d.rationale)


@pytest.mark.parametrize("category", ["Payment Problem", "Account Problem", "Complaint"])
def test_sensitive_categories_never_produce_customer_facing_responses(category):
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    d = decide_response(automated_ctx(ai_predicted_category=category), gen, CONF, SENT)

    assert d.customer_facing is False
    assert d.response_status == "HUMAN_REVIEW_DRAFT"


def test_strongly_negative_sentiment_never_produces_customer_facing_response():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    d = decide_response(automated_ctx(sentiment_score=-0.9), gen, CONF, SENT)

    assert d.customer_facing is False


def test_missing_order_context_for_order_dependent_category_blocks_automation():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    ctx = automated_ctx(ai_predicted_category="Refund Request", order_id=None, order_status=None)
    d = decide_response(ctx, gen, CONF, SENT)

    assert d.customer_facing is False
    assert any("requires order context" in r for r in d.rationale)


# ----------------------------------------------------------------------------
# No Phase 4 decision / fallback
# ----------------------------------------------------------------------------
def test_no_phase4_decision_is_not_eligible_and_makes_no_llm_call():
    gen = ResponseGenerator(FakeResponseLLMClient(tool_input=GOOD_DRAFT))
    ctx = ResponseContext(ticket_id=5, message_text="hello", decision_path=None)
    d = decide_response(ctx, gen, CONF, SENT)

    assert d.response_status == "NOT_ELIGIBLE"
    assert gen._llm_client.call_count == 0   # never spend a call on a ticket Phase 4 hasn't ruled on


def test_invalid_input_falls_back_safely():
    d = safe_decide_response({"ticket_id": 9, "message_text": "x", "classification_confidence": 5.0},
                              generator=None)

    assert d.response_status == "NOT_ELIGIBLE"
    assert d.is_fallback is True
    assert d.customer_facing is False


def test_decision_only_mode_without_generator_blocks_rather_than_inventing_a_draft():
    d = decide_response(automated_ctx(), generator=None)

    assert d.response_status == "BLOCKED"
    assert d.response_draft is None
    assert any("no generator was configured" in r for r in d.rationale)


# ----------------------------------------------------------------------------
# Prompt hygiene — what actually reaches the model
# ----------------------------------------------------------------------------
def test_prompt_contains_grounding_context_but_not_sensitive_identifiers():
    fake = FakeResponseLLMClient(tool_input=GOOD_DRAFT)
    gen = ResponseGenerator(fake)
    decide_response(automated_ctx(order_status="Delayed", product_names="Yoga Mat"), gen, CONF, SENT)

    prompt = fake.last_user_prompt
    assert "Delayed" in prompt            # grounded order fact IS provided
    assert "Yoga Mat" in prompt           # grounded product fact IS provided
    # Order VALUE is deliberately excluded from the prompt allow-list
    assert "order_value" not in prompt
    # The system prompt must carry the anti-hallucination rules
    assert "NEVER" in fake.last_system_prompt
