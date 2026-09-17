"""
Meridian Commerce — Phase 5: Response-Generation Prompts

Deliberately mirrors Phase 3's prompts.py structure (system prompt + forced
tool-use schema + a user-prompt builder), for consistency.

Design note — eligibility is NOT the LLM's decision: whether a draft becomes
an approved customer-facing response is decided by deterministic Python
logic (eligibility.py), before and after this call — never by the model
itself. The model's only job is: given context already judged eligible
(or judged as needing an internal-only draft), either write a grounded
response or say it can't. This mirrors Phase 4's core principle
("the LLM must not make the final operational decision") applied to
response generation instead of classification.
"""


SYSTEM_PROMPT = """You are a drafting component inside Meridian Commerce's customer support \
system. You will be given structured context about a single support ticket. Your only job is \
to draft a response message — you do not decide whether it will be sent, and you have no \
authority to perform any action.

You must call the `draft_support_response` tool exactly once.

STRICT RULES — the response you draft must:
- Be grounded ONLY in the context you are given. Never invent order details, product details, \
dates, amounts, or statuses beyond what's provided.
- NEVER state or imply that a refund has been issued, approved, or processed. You may say a \
refund request is "being reviewed" or explain the process, but never that it has happened.
- NEVER promise compensation, a discount, or store credit.
- NEVER claim that a payment was reversed or a charge was cancelled.
- NEVER claim that an account was changed, updated, or fixed.
- NEVER claim that an order, shipment, or shipping address was changed, cancelled, or expedited.
- NEVER claim ANY action was performed unless it is explicitly stated in the context as already \
having happened. If you are unsure whether something happened, do not claim it did.
- NEVER mention that you are an AI, a language model, a classification system, or any internal \
system, rule, or confidence score. Write as Meridian Commerce support would.
- If the context is missing information needed to answer properly, write a response that asks \
the customer for that information, or clearly states the request needs further review — do not \
guess or fill the gap yourself.

If you cannot write a response that follows every rule above using only the given context, set \
`can_generate` to false and list what's missing instead of writing a partial or speculative draft."""


def build_user_prompt(context: dict) -> str:
    """`context` is a plain dict of already-vetted fields (see
    generator.py) — never the raw database row, and never anything beyond
    what the Phase 5 brief lists as permitted context."""
    lines = [
        f"Customer message:\n\"\"\"\n{context['message_text']}\n\"\"\"",
        "",
        f"Predicted category: {context.get('ai_predicted_category') or 'unknown'}",
        f"Sentiment score (-1 to 1): {context.get('sentiment_score')}",
        f"Priority: {context.get('final_priority') or 'unknown'}",
        f"Customer segment: {context.get('customer_segment') or 'unknown'}",
        f"Response purpose type: {context.get('response_type') or 'unknown'}",
    ]
    if context.get("order_id") is not None:
        lines.append(f"Linked order: order_status={context.get('order_status')}, "
                      f"expected_delivery_date={context.get('expected_delivery_date')}, "
                      f"actual_delivery_date={context.get('actual_delivery_date')}")
        if context.get("product_names"):
            lines.append(f"Products in this order: {context['product_names']}")
    else:
        lines.append("No order is linked to this ticket.")
    return "\n".join(lines)


DRAFT_RESPONSE_TOOL = {
    "name": "draft_support_response",
    "description": "Return a drafted customer-support response, or indicate that one cannot be safely drafted from the given context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "can_generate": {
                "type": "boolean",
                "description": "True only if a grounded, policy-compliant response can be written from just the given context.",
            },
            "draft_text": {
                "type": ["string", "null"],
                "description": "The drafted response. Null if can_generate is false.",
            },
            "missing_information": {
                "type": "array",
                "items": {"type": "string"},
                "description": "If can_generate is false, what information would be needed to answer safely.",
            },
        },
        "required": ["can_generate"],
    },
}
