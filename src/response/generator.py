"""
Meridian Commerce — Phase 5: Response Generator

Wraps the LLM call for response drafting and applies the same
"never trust raw model output" discipline Phase 3 applied to classification:
the model's structured output is validated in Python, and the generated TEXT
is additionally run through the deterministic safety scanner
(`response/safety.py`) before it can ever be marked customer-facing.

The generator itself makes no eligibility decision — it is only ever called
with context that `eligibility.py` has already ruled on. Its outcomes:

    GenerationResult(success=True,  draft_text=...)   -> a clean draft
    GenerationResult(success=False, failure="model_declined")   -> model said
        it couldn't write a grounded response (can_generate=false)
    GenerationResult(success=False, failure="safety_violation") -> a draft was
        produced but the safety scanner rejected it
    GenerationResult(success=False, failure="<llm error_type>") -> API/timeout/
        malformed-response failure, reusing Phase 3's typed error codes
"""

from dataclasses import dataclass, field
from typing import List, Optional

from ..ai.llm_client import LLMClient, LLMClientError
from .models import ResponseContext
from .prompts import DRAFT_RESPONSE_TOOL, SYSTEM_PROMPT, build_user_prompt
from .safety import scan_for_forbidden_claims


@dataclass
class GenerationResult:
    success: bool
    draft_text: Optional[str] = None
    failure: Optional[str] = None
    detail: Optional[str] = None
    missing_information: List[str] = field(default_factory=list)
    safety_violations: List[tuple] = field(default_factory=list)
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


def _build_llm_context(ctx: ResponseContext, response_type: Optional[str]) -> dict:
    """The explicit allow-list of what reaches the model. Anything not named
    here is never sent — in particular no customer name, email, phone,
    customer_id, payment method, or order total. Order VALUE is deliberately
    excluded too: a response never needs to quote the amount back, and
    including it would only create an opportunity to misstate it."""
    return {
        "message_text": ctx.message_text,
        "ai_predicted_category": ctx.ai_predicted_category,
        "sentiment_score": ctx.sentiment_score,
        "final_priority": ctx.final_priority,
        "customer_segment": ctx.customer_segment,
        "response_type": response_type,
        "order_id": ctx.order_id,
        "order_status": ctx.order_status,
        "expected_delivery_date": ctx.expected_delivery_date,
        "actual_delivery_date": ctx.actual_delivery_date,
        "product_names": ctx.product_names,
    }


class ResponseGenerator:
    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    def generate(self, ctx: ResponseContext, response_type: Optional[str]) -> GenerationResult:
        llm_context = _build_llm_context(ctx, response_type)
        user_prompt = build_user_prompt(llm_context)

        try:
            response = self._llm_client.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tool_schema=DRAFT_RESPONSE_TOOL,
            )
        except LLMClientError as e:
            return GenerationResult(success=False, failure=e.error_type, detail=str(e))

        tool_input = response.tool_input or {}
        usage = dict(latency_ms=response.latency_ms,
                     input_tokens=response.input_tokens,
                     output_tokens=response.output_tokens)

        if not isinstance(tool_input, dict) or "can_generate" not in tool_input:
            return GenerationResult(success=False, failure="malformed_response",
                                     detail="Tool output missing required 'can_generate' field.",
                                     **usage)

        if not tool_input.get("can_generate"):
            return GenerationResult(
                success=False, failure="model_declined",
                detail="Model reported it could not write a grounded response from the given context.",
                missing_information=list(tool_input.get("missing_information") or []),
                **usage,
            )

        draft_text = tool_input.get("draft_text")
        if not draft_text or not str(draft_text).strip():
            return GenerationResult(success=False, failure="empty_draft",
                                     detail="Model set can_generate=true but returned no draft text.",
                                     **usage)

        draft_text = str(draft_text).strip()

        violations = scan_for_forbidden_claims(draft_text)
        if violations:
            # The draft is deliberately NOT returned — a blocked draft is
            # exactly the text that failed the safety scan, and persisting or
            # surfacing it would defeat the block. Only the reason codes
            # travel onward, for auditability.
            return GenerationResult(success=False, failure="safety_violation",
                                     detail="Generated draft failed the response safety scan.",
                                     safety_violations=violations, **usage)

        return GenerationResult(success=True, draft_text=draft_text, **usage)
