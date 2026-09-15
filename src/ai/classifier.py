"""
Meridian Commerce — Phase 3: Classifier

Orchestrates prompt-building, the LLM call, and — critically — validation of
the LLM's output before anything is trusted. Per Phase 3 requirements, the
LLM's raw output is NEVER written to the database directly: it passes through
`ValidatedClassification` (a Pydantic model with strict enum + range
constraints) first. Any failure produces a `ClassificationResult` with
`success=False` and a specific `error_type`, and the caller is expected to
skip the database write entirely for that ticket.
"""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import APPROVED_CATEGORIES, APPROVED_PRIORITIES
from .llm_client import LLMClient, LLMClientError
from .prompts import CLASSIFY_TICKET_TOOL, SYSTEM_PROMPT, build_user_prompt


# ----------------------------------------------------------------------------
# Strict validation model — this is the actual gate. Even though the tool
# schema sent to the API already declares enums, a model can still return
# out-of-vocabulary values (or a provider without native enum support could
# be plugged in later), so this check is authoritative regardless of what
# the LLM claims to have done.
# ----------------------------------------------------------------------------
class ValidatedClassification(BaseModel):
    category: str
    priority: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    order_id: Optional[int] = None
    mentions_customer_info: bool = False

    @field_validator("category")
    @classmethod
    def category_must_be_approved(cls, v):
        if v not in APPROVED_CATEGORIES:
            raise ValueError(f"'{v}' is not an approved category")
        return v

    @field_validator("priority")
    @classmethod
    def priority_must_be_approved(cls, v):
        if v not in APPROVED_PRIORITIES:
            raise ValueError(f"'{v}' is not an approved priority")
        return v


@dataclass
class ClassificationResult:
    ticket_id: int
    success: bool
    validated: Optional[ValidatedClassification] = None
    error_type: Optional[str] = None      # e.g. "invalid_category", "timeout", "malformed_response"
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class TicketClassifier:
    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    def classify(self, ticket_id: int, message_text: str) -> ClassificationResult:
        user_prompt = build_user_prompt(message_text)

        try:
            response = self._llm_client.classify(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tool_schema=CLASSIFY_TICKET_TOOL,
            )
        except LLMClientError as e:
            return ClassificationResult(
                ticket_id=ticket_id,
                success=False,
                error_type=e.error_type,
                error_message=str(e),
            )

        try:
            validated = ValidatedClassification.model_validate(response.tool_input)
        except ValidationError as e:
            # Distinguish invalid-category / invalid-priority from other
            # validation failures for clearer logging & evaluation stats.
            error_type = "invalid_response_schema"
            for err in e.errors():
                loc = err.get("loc", ())
                if loc and loc[0] == "category":
                    error_type = "invalid_category"
                    break
                if loc and loc[0] == "priority":
                    error_type = "invalid_priority"
                    break
            return ClassificationResult(
                ticket_id=ticket_id,
                success=False,
                error_type=error_type,
                error_message=str(e),
                latency_ms=response.latency_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )

        return ClassificationResult(
            ticket_id=ticket_id,
            success=True,
            validated=validated,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
