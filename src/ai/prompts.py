"""
Meridian Commerce — Phase 3: Prompts

Kept separate from the LLM client and classifier so the prompt wording can be
iterated on independently (and diffed/reviewed on its own) as evaluation
results come in.

Design note on vocabulary formatting: the Phase 3 brief's example used
snake_case / lowercase values (e.g. "refund_request", "high"). This project's
approved controlled vocabularies (Phase 1, enforced by Phase 2's CHECK
constraints) use Title Case with spaces (e.g. "Refund Request", "High").
The model is instructed to use the exact approved strings — not the example's
casing — since those are what the database will actually accept.

Design note on sentiment: Phase 1's schema stores `sentiment_score` as a
NUMERIC(3,2) in [-1, 1], not a categorical label. The model is asked for a
numeric score directly so its output maps straight onto the schema without a
lossy categorical-to-numeric conversion step.
"""

from ..config import APPROVED_CATEGORIES, APPROVED_PRIORITIES

SYSTEM_PROMPT = f"""You are a classification component inside Meridian Commerce's \
customer support system. You will be shown a single customer support message. \
Your only job is to extract structured information from it — you do not resolve \
issues, write replies, or make business decisions.

You must call the `classify_ticket` tool exactly once with your structured output.

Rules:
- `category` MUST be exactly one of these {len(APPROVED_CATEGORIES)} approved values \
(copy the spelling and casing exactly): {", ".join(APPROVED_CATEGORIES)}.
- `priority` MUST be exactly one of these approved values: {", ".join(APPROVED_PRIORITIES)}. \
Judge this from the message content alone (urgency, severity, tone) — you are not \
applying business policy, just estimating urgency as a reader would.
- `sentiment_score` is a number from -1.00 (extremely negative) to 1.00 (extremely \
positive), with 0 being neutral.
- `order_id` is an integer ONLY if the customer explicitly states an order number in \
the message text (e.g. "order #54821" or "order 54821"). If no order number appears \
in the text, return null — do not guess.
- `mentions_customer_info` is true only if the message explicitly contains customer \
identifying details (name, email, phone) written out in the text. Do not repeat the \
details themselves, just flag whether any appear.
- `confidence` is your own self-assessed confidence in this classification, from 0.0 \
to 1.0. This is a subjective self-report, not a calibrated statistical probability.

If the message is ambiguous, still make your best single choice for category and \
priority — do not refuse and do not return multiple options."""


def build_user_prompt(message_text: str) -> str:
    return f'Customer support message:\n"""\n{message_text}\n"""'


# JSON Schema for the forced tool-use call (Anthropic "tool use" structured
# output). Enums are declared here too, as a first line of defense — but the
# authoritative check is still the Python-side Pydantic validation in
# classifier.py, since a model can produce schema-shaped output with an
# unexpected value regardless of the declared enum.
CLASSIFY_TICKET_TOOL = {
    "name": "classify_ticket",
    "description": "Return the structured classification of a customer support message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": APPROVED_CATEGORIES},
            "priority": {"type": "string", "enum": APPROVED_PRIORITIES},
            "sentiment_score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "order_id": {"type": ["integer", "null"]},
            "mentions_customer_info": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["category", "priority", "sentiment_score", "confidence"],
    },
}
