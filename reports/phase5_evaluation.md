# Phase 5 Evaluation Report

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Date:** 2026-09-16

Every number below is labeled **REAL** (from the actual database), **SIMULATED**
(fixture data and/or FakeLLMClient, illustrative only), or **NOT AVAILABLE**.
No LLM quality metric is reported, because none could be measured — see
"Why no response-quality metrics exist" below.

---

## REAL — Full dataset, dry-run, current database state

All 1,500 real tickets, run through the real Phase 5 decision layer in
dry-run mode (no writes, no LLM available):

```json
{
  "dry_run": true,
  "tickets_processed": 10,
  "n_draft_generated": 0,
  "n_human_review_draft": 0,
  "n_blocked": 0,
  "n_not_eligible": 10,
  "generator_available": false,
  "evaluation": {
    "metric_provenance": "REAL (in-memory batch run)",
    "automated_response_eligible_rate": 0.0,
    "human_review_response_rate": 0.0,
    "blocked_response_rate": 0.0,
    "not_eligible_rate": 1.0,
    "response_status_distribution": { "NOT_ELIGIBLE": 10 },
    "response_type_distribution": { "(unknown/unclassified)": 10 },
    "draft_generation_attempted": 0,
    "draft_generation_succeeded": 0,
    "draft_generation_success_rate": null,
    "missing_context_rate": 0.0,
    "fallback_rate": 0.0
  }
}
```

**Why every real ticket is NOT_ELIGIBLE:** Phase 5 requires a Phase 4
decision to act on, and `decision_path IS NULL` on all 1,500 real tickets —
because Phase 4 has never been run live against real data, because Phase 3
has never classified a real ticket, because no `ANTHROPIC_API_KEY` has been
available in this environment since Phase 3. This is the same upstream
bottleneck documented in `reports/phase3_evaluation.md` and
`reports/phase4_evaluation.md`, propagating one phase further down the
pipeline. Phase 5 is behaving correctly: it declines to act on tickets
nothing upstream has ruled on, rather than inventing a decision.

`draft_generation_success_rate` is `null` (NOT AVAILABLE), not `0` —
deliberately. Zero would wrongly imply generation was attempted and failed;
in fact it was never attempted.

---

## REAL — Database verification (performed on a real row, then reverted)

Full read → dry-run → confirm-no-change → live-write → verify → revert cycle,
on real `ticket_id=2`:

| Step | Result |
|---|---|
| 1. Read original state | All Phase 3/4/5 fields NULL; `category='Order Status Inquiry'`, `priority='Low'`, real `customer_id=721`, real `order_id=3480` |
| 2. Seed **test** (not real-LLM) Phase 3+4 values | So Phase 5 had something to act on — stated plainly as test data |
| 3. Dry run (`respond --limit 2`) | `response_status` still NULL — **zero writes** |
| 4. `RESPONSE_DRY_RUN=false` but **no** `--live` | Still `dry_run: true`, still zero writes — **double-confirmation confirmed intact** |
| 5. Live write (both conditions, FakeLLMClient, safe draft) | `DRAFT_GENERATED` / `ORDER_STATUS`, draft persisted |
| 6. Verify changed fields | **Only** `response_status`, `response_type`, `response_draft`, `response_generated_at` changed. `category`, `priority`, `ai_predicted_category`, `classification_confidence`, `sentiment_score`, `decision_path`, `final_priority`, `created_at`, `customer_id`, `order_id`, `status` all byte-identical |
| 7. Live write with an **unsafe** FakeLLMClient draft | Draft claimed "your refund has been processed" → `BLOCKED`, and `response_draft` in the database is **NULL** — the offending text was never persisted |
| 8. `sql/08_phase5_validation.sql` against the written rows | **All checks returned 0 rows** |
| 9. Revert | Database confirmed back to `1500 total / 0 classified / 0 phase4_decided / 0 phase5_processed` |

Step 7 is the most important line in this table: the safety scanner was
verified blocking a real write to a real database, not just in a unit test.

---

## SIMULATED — Fixture data + FakeLLMClient, full decision space

**Not real tickets. Not real LLM output.** 14 hand-built fixtures run
through the real, unmodified `decide_response()` with a deterministic fake
client, to exercise paths the real data can't currently reach:

| ticket | response_type | response_status | customer_facing | draft |
|---|---|---|---|---|
| 9001 | ORDER_STATUS | DRAFT_GENERATED | True | yes |
| 9002 | PRODUCT_QUESTION | DRAFT_GENERATED | True | yes |
| 9003 | ORDER_STATUS | DRAFT_GENERATED | True | yes |
| 9004 | REFUND_SUPPORT | DRAFT_GENERATED | True | yes |
| 9005 | ORDER_ISSUE | DRAFT_GENERATED | True | yes |
| 9006 | PAYMENT_SUPPORT | HUMAN_REVIEW_DRAFT | False | yes (internal) |
| 9007 | ACCOUNT_SUPPORT | HUMAN_REVIEW_DRAFT | False | yes (internal) |
| 9008 | COMPLAINT | HUMAN_REVIEW_DRAFT | False | yes (internal) |
| 9009 | GENERAL_SUPPORT | HUMAN_REVIEW_DRAFT | False | yes (internal) |
| 9010 | ORDER_ISSUE | HUMAN_REVIEW_DRAFT | False | yes (internal) |
| 9011 | — | NOT_ELIGIBLE | False | no |
| 9012 | — | NOT_ELIGIBLE | False | no |
| 9013 | ORDER_STATUS | DRAFT_GENERATED | True | yes |
| 9014 | GENERAL_SUPPORT | DRAFT_GENERATED | True | yes |

```json
{
  "metric_provenance": "SIMULATED (fixture data + FakeLLMClient, not real tickets or real LLM output)",
  "n_processed": 14,
  "automated_response_eligible_rate": 0.5,
  "human_review_response_rate": 0.3571,
  "blocked_response_rate": 0.0,
  "not_eligible_rate": 0.1429,
  "draft_generation_attempted": 12,
  "draft_generation_succeeded": 12,
  "draft_generation_success_rate": 1.0,
  "internal_draft_rate": 1.0,
  "missing_context_rate": 0.0,
  "fallback_rate": 0.0
}
```

Note what these numbers do and don't mean. `draft_generation_success_rate:
1.0` means **the fake client returned a draft that passed the safety scan
every time it was asked** — it is a property of the fixture setup, not
evidence that a real model would succeed at that rate. The genuinely
informative rows are the routing ones: all three sensitive categories
(9006/9007/9008) correctly produced internal-only drafts with
`customer_facing=False` despite the fake client returning perfectly usable
text, and low confidence (9009) and missing order context (9010) did the
same. That's the human-in-the-loop guarantee holding under conditions where
a naive implementation would have sent the draft.

The BLOCKED path shows 0.0 in this particular batch because this fixture
client always returned safe text; BLOCKED is exercised separately in the
database verification (step 7 above) and in six unit tests.

---

## Why no response-quality metrics exist

No `ANTHROPIC_API_KEY` is available in this environment, so **no real LLM
response has ever been generated by this project**. Accordingly this report
contains no hallucination rate, no groundedness score, no tone/quality
rating, and no customer-satisfaction proxy. Those would each require either
real model output or human evaluation of it, and inventing them would be
worse than useless.

What the deterministic safety scanner (`src/response/safety.py`) provides is
not a quality metric but a **floor**: a set of claims that cannot appear in a
customer-facing draft regardless of what the model writes. Its own honest
limitation — it is a pattern matcher, not a semantic check, so it catches
plainly-worded violations and can miss paraphrased ones — is documented in
the module itself and in `PHASE5_SUMMARY.md`.

## NOT AVAILABLE

- Real automated-response eligibility rate on real tickets (needs Phase 3 → Phase 4 to have run for real).
- Any real response-quality, hallucination, groundedness, or satisfaction measure.
- Real token usage or cost for response generation — no real calls were made.

## Limitations

See `PHASE5_SUMMARY.md` for the full list. The dominant one is unchanged
since Phase 3: without an API key, the entire downstream pipeline can be
verified structurally but not exercised on real model output.
