"""
Meridian Commerce — Phase 5: Response Safety Scanner

A deterministic, keyword/phrase-based post-generation check — the same
"don't blindly trust the LLM output" principle Phase 3 applied to
classification output is applied here to generated TEXT. The system prompt
(prompts.py) already instructs the model not to do any of this; this module
exists because Phase 2/3/4 all treat prompt instructions as a first line of
defense, never the only one.

Honest limitation, stated once here rather than re-litigated at every call
site: this is a substring/pattern scanner, not a semantic understanding of
the text. It reliably catches direct, plainly-worded violations (e.g. "your
refund has been processed") but can miss paraphrased or indirect ones (e.g.
"you'll see the money back in your account soon"). It's a deterministic
safety NET, not a guarantee — see PHASE5_SUMMARY.md for why that's still
worth having.
"""

import re

# Each entry: (short reason code, compiled case-insensitive regex).
# Grouped by which "never" rule from the Phase 5 brief they enforce.
#
# Patterns require a specific COMPLETION verb (processed/issued/approved/...)
# rather than matching on any word following "has been" — an earlier version
# of this list matched "your refund request has been received" (a safe,
# appropriate message — the REQUEST was received, not the refund itself) as
# a false positive. Precision matters here: a scanner that blocks safe
# messages erodes trust in the safety net as much as one that misses unsafe
# ones.
_COMPLETION_VERBS = r"(?:processed|issued|approved|completed|applied|sent|given|credited|refunded|finalized|granted)"
_ACTION_VERBS = r"(?:processed|issued|approved|completed|applied|resolved|fixed|corrected|finalized|granted)"

_FORBIDDEN_PATTERNS = [
    # never promise a refund / claim one was issued
    ("refund_claimed_or_promised",
     rf"\brefund(?:s|ed|ing)?\b.{{0,30}}\b(?:has been|have been|will be|is being|was)\s+{_COMPLETION_VERBS}\b"),
    ("refund_claimed_or_promised", r"\b(we have|we've|i have|i've)\b.{0,15}\bissued\s+(?:a|the|your)\s+refund"),
    # never claim payment reversal
    ("payment_reversal_claimed",
     r"\b(payment|charge|transaction)\b.{0,25}\b(has been|have been|was|is being)\s+(?:reversed|refunded|cancelled|voided)\b"),
    # never promise compensation
    ("compensation_promised",
     r"\b(compensation|store credit|discount)\b.{0,25}\b(will be (?:applied|given|issued|provided)|has been (?:applied|given|issued|provided))\b"),
    # never claim an account change was performed
    ("account_change_claimed",
     r"\byour account\b.{0,25}\b(?:has been|have been|was)\b.{0,15}\b(?:updated|changed|fixed|corrected|reset)\b"),
    # never claim shipment/order changes were performed
    ("shipment_or_order_change_claimed",
     r"\b(your order|your shipment|your shipping address)\b.{0,25}\b(?:has been|have been|was)\b.{0,15}\b(?:updated|changed|cancelled|expedited|resent)\b"),
    # never claim an action was performed in general ("I have processed...")
    ("action_performed_claimed",
     rf"\b(i have|i've|we have|we've)\b.{{0,10}}\b{_ACTION_VERBS}\b.{{0,15}}\b(?:your|the)\b"),
    # never mention the AI/model/classification apparatus
    ("internal_architecture_mentioned",
     r"\b(ai model|language model|large language model|\bllm\b|classification model|machine learning|artificial intelligence|confidence score)\b"),
    ("internal_architecture_mentioned", r"\b(as an ai|i am an ai|i'm an ai)\b"),
]

_COMPILED = [(reason, re.compile(pattern, re.IGNORECASE)) for reason, pattern in _FORBIDDEN_PATTERNS]


def scan_for_forbidden_claims(text: str) -> list:
    """Returns a list of (reason_code, matched_text) tuples — empty list
    means the text passed every check. Never raises; a scanner that can
    itself fail on weird input would be a bad safety net."""
    if not text:
        return []
    violations = []
    for reason, pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            violations.append((reason, match.group(0)))
    return violations
