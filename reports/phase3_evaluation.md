# Phase 3 Evaluation Report

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Date:** 2026-09-12

## Status: Live LLM evaluation could not be run — no API credentials available

This report documents what was and wasn't possible to actually execute, per
the explicit instruction not to fabricate results when something can't be run.

**What happened when checked:** this development environment has network
access to `api.anthropic.com` but no `ANTHROPIC_API_KEY` is configured. A
direct unauthenticated request to the API confirmed this:

```
HTTP 401 — {"type":"error","error":{"type":"authentication_error","message":"x-api-key header is required"}}
```

Running the actual CLI confirms the same thing end-to-end, failing gracefully
rather than crashing:

```
$ python -m src.pipeline classify --limit 3
2026-09-12 17:07:05 [INFO] Starting classification run: limit=3, dry_run=True
2026-09-12 17:07:05 [ERROR] Cannot start: No API key provided to AnthropicLLMClient.

Cannot start classification run: No API key provided to AnthropicLLMClient.
Set ANTHROPIC_API_KEY in your .env file (see .env.example) and try again.
```

**Consequently, sections 18–21 of the Phase 3 brief — accuracy, per-category
precision/recall/F1, the confusion matrix, and average latency computed from
real LLM predictions on the 1,500 historical tickets — have no real numbers
to report yet.** None are fabricated here. Once `ANTHROPIC_API_KEY` is set
(e.g., by running this project locally or in an environment where a key is
provisioned), the exact same code — unchanged — will produce real results:

```
python -m src.pipeline classify --limit 10          # inspect a small batch first
python -m src.pipeline classify --limit 1500 --live  # then the full set
python -m src.pipeline evaluate                       # then real metrics
```

---

## What WAS actually verified in this environment

Everything that doesn't require a live LLM call was built and genuinely
executed, not just written:

| Component | Verification performed | Result |
|---|---|---|
| Unit test suite (15 tests) | `pytest tests/ -v` | **15/15 passed** — see below |
| Database connectivity | Connected to the real Phase 2 PostgreSQL database, ran `fetch_ticket_batch`, `count_classified`, `fetch_evaluation_data` | Returned real rows from the live 1,500-ticket table |
| `update_ticket_classification` | Ran against real ticket_id=1 in the live database, inspected before/after state, then reverted the test write | Confirmed only `ai_predicted_category`, `classification_confidence`, `sentiment_score`, `decision_at` changed — `category`, `priority`, `created_at`, `customer_id`, `order_id`, `status`, `decision_path` were untouched |
| Dry-run safety guarantee | `classify_batch()` run directly with a fake (mocked) LLM client returning valid predictions, `dry_run=True` | `update_ticket_classification` was called **zero times**, confirmed via mock call-count assertion |
| Failed-prediction safety guarantee | Same, with the fake client raising a timeout error, `dry_run=False` (live) | `update_ticket_classification` was still called **zero times** — a failed prediction never reaches the database |
| CLI error handling | Actually ran `python -m src.pipeline classify --limit 3` and `python -m src.pipeline evaluate` with no API key and no classified data respectively | Both failed/reported gracefully with clear messages, not stack traces |
| Metrics module (`compute_metrics`) | Ran on a small hand-built example (5 labeled examples, NOT real classification output) | Accuracy, per-category precision/recall/F1, and confusion matrix all computed correctly and matched manual calculation |

### Unit test results (actual pytest output)

```
tests/test_classifier.py::test_valid_structured_response_succeeds PASSED
tests/test_classifier.py::test_invalid_category_is_rejected PASSED
tests/test_classifier.py::test_invalid_priority_is_rejected PASSED
tests/test_classifier.py::test_malformed_response_is_marked_failed_not_raised PASSED
tests/test_classifier.py::test_missing_required_field_is_rejected PASSED
tests/test_classifier.py::test_out_of_range_sentiment_is_rejected PASSED
tests/test_classifier.py::test_timeout_error_is_marked_failed_not_raised PASSED
tests/test_classifier.py::test_order_id_extraction_when_present PASSED
tests/test_database.py::test_update_ticket_classification_writes_only_ai_fields_and_commits PASSED
tests/test_database.py::test_fetch_ticket_batch_filters_unclassified_by_default PASSED
tests/test_database.py::test_fetch_evaluation_data_only_returns_classified_tickets PASSED
tests/test_pipeline.py::test_dry_run_never_writes_to_database PASSED
tests/test_pipeline.py::test_live_run_writes_successful_classifications PASSED
tests/test_pipeline.py::test_failed_classification_never_triggers_a_database_write PASSED
tests/test_pipeline.py::test_mixed_batch_only_writes_the_successful_ones PASSED

============================== 15 passed in 1.23s ==============================
```

These tests use a `FakeLLMClient` test double (implementing the same
`LLMClient` interface `AnthropicLLMClient` does) — no real API calls, no
network, no cost. That's the entire point of the client abstraction: the
validation, error-handling, and dry-run logic can be proven correct
independently of whether a real model is reachable.

---

## Methodology (ready to run, not yet executed against real predictions)

Once credentials are available:

1. **Test methodology:** a held-out comparison against the 1,500 historical
   tickets generated in Phase 2. Each ticket's `message_text` is sent to the
   classifier; the resulting `ai_predicted_category` is compared against the
   ticket's existing `category` (ground truth, never modified).
2. **Model used:** configurable via `MODEL_NAME` (default in `.env.example`:
   `claude-sonnet-4-6` — verify this string against current Anthropic API
   documentation before running, since model identifiers change over time).
3. **Configuration:** `LLM_MAX_TOKENS=1024`, `LLM_TIMEOUT_SECONDS=30`,
   `LLM_MAX_RETRIES=3`, forced tool-use (`classify_ticket` tool, see
   `src/ai/prompts.py`) for structured output.
4. **Rollout plan (per the Phase 3 brief):** 10 tickets → inspect → 100
   tickets → inspect → all 1,500.
5. **Metrics:** overall accuracy, macro F1 (see rationale in
   `src/evaluation/metrics.py` — the ticket categories are non-uniformly
   distributed, from 39 "Other" tickets to 262 "Order Status Inquiry"
   tickets per Phase 2's actual generated data, so macro F1 matters alongside
   accuracy: a classifier could score well on accuracy by nailing the common
   categories while doing poorly on rare ones, and macro F1 — which weights
   every category equally regardless of its size — would expose that, while
   plain accuracy would not), per-category precision/recall/F1, and the full
   confusion matrix.
6. **Known limitation on order_id extraction:** Phase 2's synthetic message
   templates (see `PHASE2_SUMMARY.md`) don't embed literal order numbers in
   the message text (e.g., they say "my order was supposed to arrive days
   ago," never "order #54821"). So while the classifier supports extracting
   an explicitly-stated `order_id` from a message, this specific historical
   dataset gives it essentially nothing to find — that part of the
   evaluation won't be meaningful against this dataset regardless of model
   quality. This is a property of the Phase 2 data, not a pipeline bug.

## Errors

None to report — no live classification attempts were made, so there are no
live-run errors yet. The only failure observed was the expected, correctly-
handled authentication failure documented above.

## Limitations

- No real classification accuracy, F1, or confusion matrix numbers exist yet.
- Token usage and cost are entirely unmeasured — no real API calls were made,
  so there is nothing to report and nothing has been estimated.
- The `order_id`-extraction capability can't be meaningfully evaluated
  against this specific historical dataset (see above).
- Model self-reported `confidence` has not been checked for any correlation
  with actual correctness in this environment, since no real predictions
  exist yet to check it against (see `PHASE3_SUMMARY.md` for the broader
  point that self-reported confidence isn't a calibrated probability
  regardless).

## Observations

The infrastructure — prompt construction, forced tool-use schema, strict
Python-side validation (category/priority enums, numeric ranges, required
fields), retry/backoff logic, dry-run gating, and the database read/write
layer — is built, unit-tested, and confirmed working against the real Phase 2
database. The only missing piece to produce real evaluation numbers is a
valid `ANTHROPIC_API_KEY`.
