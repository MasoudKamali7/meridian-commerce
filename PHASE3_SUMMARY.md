# Phase 3: AI Ticket Classification & Information Extraction

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Phase:** 3 of N
**Status:** Pipeline built, unit-tested, and verified against the real Phase 2 database. **Live LLM evaluation was not run — no API credentials were available in this environment.** See §I for the full, honest accounting; nothing below is fabricated.

---

## Design Decision 1: How Should AI Confidence Be Represented?

**Recommendation: store the model's self-reported confidence, but never treat it as a calibrated probability — anywhere in this system.**

An LLM asked to output a number like `"confidence": 0.94` is producing a
subjective self-report in the same generative pass as its answer, not a
statistic derived from calibration testing. Research on LLM calibration
consistently finds these self-reported numbers correlate only loosely with
actual accuracy — models tend toward overconfidence, and the number can shift
based on phrasing that has nothing to do with correctness. Treating `0.94` as
"94% chance this is right" would be a real business risk if Phase 4 ever used
it directly to gate automatic ticket processing.

What this project actually does:
- `classification_confidence` stores the raw model self-report, clearly
  documented (in the schema comment from Phase 1/2, in `prompts.py`, and
  here) as **model-reported confidence, not a statistically calibrated
  probability**.
- **Recommended alternative for anything that matters operationally**
  (i.e., Phase 4's automate-vs-escalate decision): derive an *empirical*
  reliability signal from the evaluation dataset instead — per-category
  precision/recall from `src/evaluation/metrics.py`, computed against the
  1,500 historical tickets' known ground truth. "This model is 92% precise
  on 'Refund Request' specifically" is a measured, falsifiable number in a
  way "the model said 0.94" is not. Phase 4's business rules should key
  automation eligibility off of category-level empirical performance (once
  measured), using the model's raw confidence at most as a secondary,
  clearly-labeled signal — never the sole gate.
- A further option worth knowing about, not implemented here (added cost):
  *self-consistency* — sample the model N times at nonzero temperature and
  use the agreement rate across samples as a confidence proxy. This is a
  legitimate calibration heuristic in the LLM literature but multiplies API
  cost by N, which isn't justified for Phase 3's scope.

---

## Design Decision 2: Should the AI Predict Priority Directly, or Should Priority Be Derived by Business Rules?

**Recommendation: B — priority is derived later by deterministic business rules, not trusted as a raw, authoritative LLM output.** This is the option the Phase 3 brief asked me to argue for explicitly (strongest separation between AI classification and business logic), and it's also what the implementation actually does.

Reasoning:
- **Category, sentiment, and extraction are language-understanding tasks** —
  exactly what an LLM is suited for. **Priority is a policy decision**
  ("Complaints are always at least Medium," "Delayed high-value VIP orders
  are Urgent") — a business rule, not a linguistic judgment. Blending the two
  into one LLM call blurs "what did the model understand" with "what does
  the business want to happen," which makes both harder to audit and change
  independently.
- Phase 1 already defines priority-by-category rules. Re-deriving priority
  from `ai_predicted_category` (+ optionally `sentiment_score`, order value,
  or customer segment) in Phase 4's deterministic rule layer reuses that
  existing, approved design rather than asking the LLM to reinvent it per
  ticket.
- **Concretely, in this implementation:** the LLM is still asked for a raw
  `priority` guess in its structured output (useful as a diagnostic signal —
  "how often does the model's instinct agree with our rules?"), but:
  - it is captured **only** in the classification log (`logs/classification.jsonl`,
    field `predicted_priority`) for later analysis,
  - it is **never written to `tickets.priority`**.
  - `tickets.priority` is treated the same way as `tickets.category` for
    these historical seed tickets: it's an existing, human-assigned
    historical value from Phase 2 and Phase 3 does not overwrite it (the
    Phase 3 brief's do-not-overwrite list didn't explicitly name `priority`,
    but the same logic that protects `category` applies here, and there's no
    approved `ai_predicted_priority` column to write it into even if we
    wanted to — adding one would be an unapproved Phase 2 schema change).
  - Phase 4, when it exists, should compute priority for **new** tickets
    deterministically from `ai_predicted_category` and `sentiment_score`
    (plus any DB-verified signals), per Phase 1's approved rules.

---

## Other Decisions Made Explicit (not asked for by name, but necessary to build this)

- **Vocabulary casing:** the brief's JSON example used snake_case/lowercase
  (`"refund_request"`, `"high"`). The approved Phase 1 vocabulary (enforced
  by Phase 2's `CHECK` constraints) is Title Case (`"Refund Request"`,
  `"High"`). The model is instructed to use the approved strings exactly —
  matching the example's casing instead would have violated "use ONLY the
  approved categories."
- **Sentiment as a number, not a label:** the brief's example showed
  `"sentiment": "negative"` (categorical). Phase 1's schema stores
  `sentiment_score` as `NUMERIC(3,2)` in `[-1, 1]`. The model is asked for
  the numeric score directly, so it maps onto the schema without a lossy
  categorical→numeric conversion step.
- **`status` and `decision_path` are never touched by Phase 3.** These are
  historical, mostly-closed tickets being retroactively evaluated, not live
  tickets moving through the pipeline for the first time — flipping an
  already-`Closed` ticket to `Classified` would misrepresent its real
  lifecycle. `decision_path` is explicitly a Phase 4 (business-rule routing)
  concept, and Phase 3's brief explicitly excludes business-rule execution.
- **Structured output via forced tool-use, not "please reply in JSON."**
  Anthropic's tool-use mechanism (`tool_choice={"type": "tool", ...}`) is
  used to get schema-shaped output reliably, rather than asking the model to
  emit JSON in free text and hoping it's parseable. The Python-side Pydantic
  validation in `classifier.py` remains the authoritative check regardless —
  tool-use makes malformed output less likely, not impossible, so nothing
  downstream trusts it without that validation step.

---

## A. Final Phase 3 Architecture

See the architecture diagram in `README.md` ("Phase 3: AI Ticket
Classification & Information Extraction" → Architecture). In short:
`prompts.py` builds the request → `llm_client.py` calls the provider with
retries and typed errors → `classifier.py` validates the raw output against
a strict Pydantic schema (approved categories/priorities, numeric ranges,
required fields) → `pipeline.py` logs the outcome and, only for validated
successes and only outside dry-run, writes the AI-derived fields via
`database/tickets.py`.

## B. Final Project Structure

See `README.md` for the full tree. Summary of what's new in Phase 3:
`src/` (config, logging, pipeline, `ai/`, `database/`, `evaluation/`),
`tests/`, `reports/`, `.env.example`, `.gitignore`.

## C. All New/Modified Files

**New:**
`src/config.py`, `src/logging_config.py`, `src/pipeline.py`,
`src/ai/prompts.py`, `src/ai/llm_client.py`, `src/ai/classifier.py`,
`src/database/connection.py`, `src/database/tickets.py`,
`src/evaluation/metrics.py`, `tests/conftest.py`, `tests/test_classifier.py`,
`tests/test_database.py`, `tests/test_pipeline.py`,
`reports/phase3_evaluation.md`, `.env.example`, `.gitignore`,
plus package `__init__.py` files.

**Modified:** `requirements.txt` (added `anthropic`, `python-dotenv`,
`pydantic`, `scikit-learn`, `pytest`), `README.md` (added the full Phase 3
section).

**Unchanged:** everything from Phase 2 (`sql/`, `scripts/`, `data/`) — Phase
3 reads from that schema and data but never modifies the schema or the
original ticket fields.

## D. Setup Instructions

See `README.md` → "Phase 3" → "Setup". Short version: copy `.env.example` to
`.env`, fill in `DB_PASSWORD` and `ANTHROPIC_API_KEY`, `pip install -r requirements.txt`.

## E. Environment Variables

See the full table in `README.md` → "Phase 3" → "Environment variables".
Nothing is hard-coded: DB credentials, the API key, the model name, timeouts,
retries, batch size, the dry-run switch, log settings, and (optional) token
pricing are all environment-driven.

## F. Example Dry-Run Command

```
python -m src.pipeline classify --limit 10
```
Actually run in this environment — see §I for the real output (a graceful,
informative failure, since no API key is configured here).

## G. Example Batch-Processing Command

```
python -m src.pipeline classify --limit 100 --live
```
Requires `DRY_RUN=false` in `.env` **and** `--live` (see the double-
confirmation safety rule in `README.md`). Not run in this environment for
the same credential reason.

## H. Evaluation Methodology

Compare `ai_predicted_category` against each ticket's existing `category`
across all 1,500 historical tickets (once classified), computing overall
accuracy, macro F1 (see rationale below), per-category precision/recall/F1,
and a confusion matrix. Full detail in `reports/phase3_evaluation.md`.

**Why macro F1 matters here:** Phase 2 generated ticket categories with
deliberately non-uniform frequency — from 39 "Other" tickets up to 262
"Order Status Inquiry" tickets (real counts from `PHASE2_SUMMARY.md`).
Overall accuracy can look strong purely by nailing the frequent categories
while quietly failing on rare ones. Macro F1 averages per-category F1
**unweighted**, so "Other" counts exactly as much as "Order Status Inquiry"
in the final score — a much more honest signal of whether the classifier
generalizes across the whole approved vocabulary, not just the easy majority
cases.

## I. Actual Evaluation Results

**No real classification accuracy/F1/confusion-matrix numbers exist yet.**
This environment has network access to `api.anthropic.com` but no
`ANTHROPIC_API_KEY` configured — confirmed by both a direct unauthenticated
request (`HTTP 401: x-api-key header is required`) and by actually running
the CLI:

```
$ python -m src.pipeline classify --limit 3
2026-09-12 17:07:05 [INFO] Starting classification run: limit=3, dry_run=True
2026-09-12 17:07:05 [ERROR] Cannot start: No API key provided to AnthropicLLMClient.

Cannot start classification run: No API key provided to AnthropicLLMClient.
Set ANTHROPIC_API_KEY in your .env file (see .env.example) and try again.
```

Per your explicit instruction, I'm stopping here rather than inventing
numbers. **What I verified instead, for real, against the live Phase 2
database:**
- `fetch_ticket_batch`, `count_classified`, and `fetch_evaluation_data` all
  ran against the real 1,500-ticket table and returned real rows.
- `update_ticket_classification` was run against real `ticket_id=1`,
  confirmed (by inspecting the row before/after) that it changed only
  `ai_predicted_category`, `classification_confidence`, `sentiment_score`,
  and `decision_at` — then the test write was reverted so the database
  accurately reflects "zero tickets classified so far."
- The metrics module (`compute_metrics`) was sanity-checked on a small
  hand-built example (clearly not real classification output) and its
  accuracy/precision/recall/F1 matched manual calculation.

Full detail, including the methodology that's ready to run the moment a key
is available, is in `reports/phase3_evaluation.md`.

## J. Unit-Test Results (actual)

```
15 passed in 1.23s
```
All 15 tests listed individually in §7 of `reports/phase3_evaluation.md`
(and in the test files themselves) passed, using a fake LLM client — no
network calls, no API cost, and no dependency on the credential gap above.
These specifically verify: valid response handling, invalid category
rejection, invalid priority rejection, malformed/missing-tool-use handling,
missing required fields, out-of-range values, the dry-run write guarantee,
the failed-classification write guarantee, and correct SQL/params in the
database update.

## K. Known Limitations

- **No real evaluation numbers yet** — the central limitation (§I).
- **`order_id` extraction can't be meaningfully evaluated against this
  dataset.** Phase 2's synthetic message templates don't embed literal order
  numbers in the text (e.g., "my order was supposed to arrive days ago,"
  never "order #54821"), so the classifier has nothing to extract from these
  specific historical messages regardless of model quality. The capability
  is implemented and would work on messages that do contain an order number.
- **Cost is entirely unmeasured** — no real API calls were made, so there's
  no token usage to report and no cost estimate (the pipeline supports both,
  gated on real usage and on the operator supplying current pricing).
- **Model self-reported confidence hasn't been checked against real outcomes**
  in this environment, for the same credential reason — see Design Decision 1
  for why it shouldn't be trusted as calibrated even once it has been.
- **`MODEL_NAME` default may drift.** Model identifiers change over time;
  verify the configured string against current Anthropic API documentation
  before running.

## L. Phase 3 Complete — Checklist

- [x] AI classification pipeline designed (prompts / client / classifier / database / config / evaluation, cleanly separated)
- [x] Python connects to the real Phase 2 PostgreSQL database (verified live)
- [x] Reads a batch of historical tickets (verified live)
- [x] Structured JSON output enforced via forced tool-use, not free-text JSON
- [x] Classifier restricted to the approved Phase 1 categories and priorities (enforced twice: tool schema enum + Pydantic validation)
- [x] Clean separation: prompts / llm_client / classifier / database / config / evaluation, each in its own file
- [x] API credentials via environment variables only; `.env` git-ignored; `.env.example` provided
- [x] Error handling for auth, timeout, rate-limit, API, malformed-response, invalid-category, invalid-priority, missing-fields, and database errors — each with its own typed exception or `error_type`
- [x] LLM output validated in Python before any database write — never trusted directly
- [x] Structured logging (ticket_id, timestamp, success/failure, predicted category/priority, latency, error type) — no PII (no email, no raw message text) in logs
- [x] Confidence representation decided and explained, not silently assumed (Design Decision 1)
- [x] Batch processing works for any `--limit` without code changes
- [x] `DRY_RUN` mode implemented, with an explicit double-confirmation safety rule to go live
- [x] Small-batch-first workflow supported (`--limit 10` before `--limit 1500`)
- [x] Database writes touch only AI-derived fields — category, created_at, customer/order info, status, and decision_path all verified untouched
- [x] Evaluation dataset defined (the 1,500 historical tickets' ground-truth category) — no fine-tuning performed or implied
- [x] Evaluation code built for accuracy, per-category precision/recall/F1, macro F1, confusion matrix, success/failure counts, and latency
- [x] Class imbalance addressed explicitly — macro F1 alongside accuracy, with rationale
- [x] Evaluation report created (`reports/phase3_evaluation.md`) — honest about what is and isn't measured yet
- [x] Unit tests written and **actually run** for all required cases (15/15 passed)
- [x] Model/API choice configurable via `MODEL_NAME`, not hard-coded
- [x] Cost-tracking mechanism implemented (real token counts from API usage, no invented pricing)
- [x] Security: no hard-coded credentials anywhere; `.env` git-ignored; customer email never logged
- [x] README updated with Phase 3 architecture, setup, env vars, and example commands specific to this project
- [x] **Actually ran the code** rather than only generating it — including deliberately re-testing after finding and fixing two real bugs during that process (a broken relative import, and a dry-run flag that silently ignored the `DRY_RUN` env var)
- [x] Stopped and reported honestly at the one point real execution wasn't possible (live LLM evaluation), rather than fabricating results
- [x] No autonomous agents, RAG, vector databases, FastAPI, automated refunds/responses, business-rule execution, or Power BI included

**Ready for your review before Phase 4.**
