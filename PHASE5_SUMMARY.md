# Phase 5: AI Support Decision & Response Layer

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Phase:** 5
**Status:** Complete. 128/128 tests passing (62 new + all 66 from Phases 3–4.1, unmodified). Schema migration applied to the real database; full read → dry-run → live-write → verify → revert cycle performed on a real ticket row, including a live verification that an unsafe draft is blocked and never persisted.

---

## 1. Pre-Work: What I Found Inspecting Phases 1–4.1

I inspected the live database schema, all four summary docs, both evaluation
reports, and every module under `src/` before writing code. Findings:

1. **Docs and code are in sync** — the Phase 4.1 cleanup left no drift I could find. `urgent_human_review_rate` is consistently named across code, tests, and all docs; no stale `escalation_rate` references remain outside the passages that explain the rename.
2. **The live schema matches the migrations exactly**: `tickets` has 18 original columns plus `final_priority`/`rule_decision_at` from Phase 4. 1,500 tickets, `classified=0`, `phase4_decided=0`.
3. **The upstream bottleneck persists and now propagates two phases deep.** No API key → Phase 3 never classified → Phase 4 has no classification to rule on → Phase 5 has no Phase 4 decision to act on. This isn't a new problem, but Phase 5 is where its effect is most visible, and I've reported it plainly rather than working around it.
4. **`LLMClient.classify()` is already generic** — it's a "forced tool-use → structured output" call whose name is a Phase-3-era artifact. This meant Phase 5 needed no new client architecture (see §5).
5. **Existing safety patterns to preserve, not reinvent:** the `DRY_RUN=false` **AND** `--live` double-confirmation; `safe_*()` wrappers that fall back rather than raise; minimal-field `UPDATE` functions; `[stated]`-style provenance labeling in evaluation; and Phase 4.1's lesson about derived values (don't persist what you can compute, or the two will drift).

---

## 2. Architecture

```
Ticket (message + Phase 3 outputs + Phase 4 decision + order/product context)
                    │
                    ▼
        ResponseContext (Pydantic — the ONLY thing Phase 5 sees;
                          no customer name/email/phone, no order total)
                    │
                    ▼
        eligibility.py — deterministic. Reads Phase 4's decision;
          re-verifies its preconditions as defense-in-depth.
          Outcome: no_phase4_decision | human_review | automated_eligible
                    │
          ┌─────────┼──────────────────────┐
          ▼         ▼                      ▼
   NOT_ELIGIBLE   human_review        automated_eligible
   (no LLM call)      │                      │
                      ▼                      ▼
              generator.py (internal)  generator.py (customer-facing candidate)
                      │                      │
                      ▼                      ▼
              safety.py scan          safety.py scan
                      │                      │
                      ▼                      ▼
          HUMAN_REVIEW_DRAFT          DRAFT_GENERATED (pass)
          customer_facing=False        customer_facing=True
                                       or BLOCKED (fail — text discarded)
```

**Phase 4 remains authoritative.** Phase 5 never overrides a Human Review
ruling and never promotes a ticket to automation. Its re-verification can
only ever move a decision *toward* human review, never away from it.

---

## 3. Response Decision Logic

| Phase 4 decision | Phase 5 eligibility | Generation | → response_status |
|---|---|---|---|
| (none yet) | no_phase4_decision | not attempted | **NOT_ELIGIBLE** |
| Human Review | human_review | attempted (best-effort) | **HUMAN_REVIEW_DRAFT** |
| Automated | human_review (re-verification disagreed) | attempted | **HUMAN_REVIEW_DRAFT** |
| Automated | automated_eligible | succeeded + passed scan | **DRAFT_GENERATED** |
| Automated | automated_eligible | failed / declined / blocked | **BLOCKED** |

Statuses are the brief's suggested names, kept as-is — they mapped cleanly
onto the actual decision tree and conflicted with no existing Phase 1–4
terminology.

**`customer_facing` and `requires_human_review` are derived, never stored**
(`derive_response_flags()`), and a Pydantic `model_validator` makes an
inconsistent `ResponseDecision` **impossible to construct** — you cannot
build a `DRAFT_GENERATED` that isn't customer-facing, or a `BLOCKED` that
carries a draft. This is the Phase 4.1 lesson applied preemptively.

**Response types** map 1:1 from ticket category. One addition beyond the
brief's example list, documented rather than silently invented:
**`ORDER_ISSUE`** for Missing Item / Damaged Product. `REFUND_SUPPORT` would
presuppose the resolution is a refund — a claim Phase 5 has no authority to
make. `response_type` names the response *purpose*, never an outcome:
`REFUND_SUPPORT` means "a message about a refund request," never "a refund
happened."

`response_type` is nullable because a ticket can be routed to Human Review
*precisely because classification is missing* — in which case there's no
category to derive a purpose from. None in, None out; no guessed default.

---

## 4. Safety Rules & How They're Enforced

Three independent layers, because the project's established pattern is never
to rely on prompt instructions alone:

1. **Prompt-level** (`response/prompts.py`): explicit NEVER rules for refunds, compensation, payment reversal, account/order changes, claiming actions, and mentioning AI/models/confidence. The model can also set `can_generate=false` rather than write something speculative.
2. **Deterministic post-generation scan** (`response/safety.py`): regex patterns for each forbidden claim class. Any hit → `BLOCKED`, **and the offending text is discarded, not persisted** — a blocked draft is exactly the text that failed the scan.
3. **Structural** (`response/models.py`): the validator described above makes unsafe state unrepresentable.

**Honest limitation, stated once and not oversold:** layer 2 is a pattern
matcher, not semantic understanding. It reliably catches direct phrasings
("your refund has been processed") and can miss indirect ones ("you'll see
the money back soon"). It's a floor, not a guarantee. It's still worth
having because it's deterministic, auditable, testable, and costs nothing at
runtime.

**Context minimization:** `_build_llm_context()` is an explicit allow-list.
Customer name, email, phone, customer_id, and payment method are never sent.
Order *value* is deliberately excluded too — a response never needs to quote
the amount, and including it only creates an opportunity to misstate it.

**Log hygiene:** draft *text* is never logged, only whether a draft exists.
Drafts can echo the customer's own words; the log isn't the place for message content.

---

## 5. Reuse vs. New Code

Per the brief's "do not create a completely separate client architecture":
`LLMClient` gained one method — `generate_structured()`, a thin alias for
`classify()` on the base class. `classify()` already *is* a generic
forced-tool-use call; only its name was Phase-3-specific. This gives Phase 5
an accurately-named entry point while reusing all of Phase 3's retry,
backoff, timeout, and typed-error handling, with zero changes to Phase 3
call sites and zero risk to existing tests (verified: all 8 classifier tests
still pass).

---

## 6. Database Changes

`sql/07_phase5_schema.sql` — **four** new nullable columns on `tickets`, not
the six the brief listed:

| Column | Type | Why |
|---|---|---|
| `response_status` | VARCHAR(20), CHECK'd | The core decision |
| `response_type` | VARCHAR(20), CHECK'd, nullable | Response purpose |
| `response_draft` | TEXT | The work product |
| `response_generated_at` | TIMESTAMP, CHECK ≥ created_at | Distinct from `decision_at` (Phase 3) and `rule_decision_at` (Phase 4) |

**`response_customer_facing` and `response_requires_human_review` were
deliberately NOT added** — both are 1:1 functions of `response_status`.
Storing them would let them drift out of sync through a partial UPDATE,
which is precisely the bug class Phase 4.1 fixed. This also mirrors Phase
4's own choice not to add a redundant boolean beside `decision_path`.

Plus a `CHECK` enforcing draft/status consistency at the database level
(BLOCKED and NOT_ELIGIBLE can never carry a draft), and two indexes on the
columns evaluation actually filters by.

`update_phase5_response()` writes **only** those four columns — verified by
a unit test that inspects the literal SQL and by a real before/after row read.

---

## 7. Dry-Run / Live Safety

Unchanged and unweakened: `RESPONSE_DRY_RUN=false` **AND** `--live` are both
required. Verified live — with the env var set to false but `--live` omitted,
the run reported `dry_run: true` and wrote nothing.

The layer also **degrades honestly without an API key**: it still makes real
eligibility and routing decisions, produces no drafts, sets
`generator_available: false`, and says so. It does not crash, and it does not
pretend drafts exist.

---

## 8. Tests

**62 new tests** across three files, all using a FakeLLMClient — no API key,
no network, no cost:

- `tests/test_response_models.py` (35) — valid/invalid model construction, every flag/status invariant, the full category→type mapping, context validation, and 14 safety-scanner cases (safe text passes, forbidden claims caught).
- `tests/test_response_engine.py` (20) — automated eligibility, unsafe-draft blocking with text-discard verification, model declining, LLM errors, malformed/empty output, Phase 4 human-review respect, internal-draft toggling, all three sensitive categories, low confidence, strong negative sentiment, missing order context, no-Phase-4-decision (asserts **no LLM call is made**), fallback, decision-only mode, and prompt hygiene (grounding facts present, order value absent).
- `tests/test_response_pipeline.py` (7) — dry-run writes nothing, live writes everything, only Phase 5 fields in the UPDATE, PII absent from the fetch query, draft text absent from the evaluation query.

## 9. Actual Test Results

```
python -m pytest tests/ -q
128 passed in 1.11s
```

All 66 pre-existing tests pass **unmodified**. Nothing was deleted or weakened.

## 10. Evaluation Results

See `reports/phase5_evaluation.md`. Summary:

- **REAL, dry-run, 1,500 tickets:** 100% `NOT_ELIGIBLE` — no Phase 4 decision exists on any real ticket (upstream bottleneck, §1.3). `draft_generation_success_rate` is `null` (NOT AVAILABLE), not 0.
- **REAL database verification:** performed and reverted; only the four Phase 5 columns changed; unsafe draft confirmed blocked and not persisted.
- **SIMULATED (fixtures + FakeLLMClient):** 50% DRAFT_GENERATED, 35.7% HUMAN_REVIEW_DRAFT, 14.3% NOT_ELIGIBLE — all three sensitive categories correctly produced internal-only drafts despite the fake client returning perfectly usable text.
- **No LLM quality metrics of any kind** — no real model output exists to measure.

## 11. Bugs Found and Fixed During This Phase

1. **Safety scanner false positive (real bug, caught by my own testing before any test file existed).** The first pattern set flagged *"Your refund request has been received and is under review"* as a forbidden refund claim — a safe, appropriate message. The patterns matched "refund" + any "has been", rather than requiring a completion verb. Fixed by requiring an explicit completion verb (`processed|issued|approved|...`), then re-verified against 17 cases (6 safe, 11 unsafe) with 100% correct classification. A scanner that blocks safe messages erodes trust as much as one that misses unsafe ones.
2. **Test-harness signature mismatch (mine, not the code's).** My first live-verification script defined `generate_structured(self, s, u, t)` positionally while the generator calls it with keywords. Fixed the harness; the production code was correct.

## 12. Architectural Trade-offs

- **Internal drafts for human-review tickets are ON by default.** They cost an LLM call on tickets a human handles anyway, but that's the agent-assist value of the feature. Configurable via `GENERATE_INTERNAL_DRAFTS`, and a test verifies that disabling it makes zero LLM calls.
- **Phase 5 re-verifies Phase 4's preconditions** rather than trusting `decision_path` alone. Slight duplication of Phase 4 logic, but it can only ever fail *safe*, and it matches the project's existing "validate at every boundary" posture. It is explicitly not a competing escalation system: it cannot promote anything to automation.
- **Rationale strings aren't persisted**, following Phase 4's precedent (audit detail lives in the log). Cost: `missing_context_rate` and `fallback_rate` are NOT AVAILABLE from `respond-evaluate`. Documented in the metrics module rather than silently reported as 0.
- **Regex-based safety rather than a second LLM judge.** A model-based checker would catch paraphrases but adds cost, latency, and a non-deterministic component to the one layer that most needs to be deterministic and auditable.

## 13. What Phase 5 Explicitly Does NOT Do

No emails. No WhatsApp or any messaging. No refunds, payments, or
chargebacks. No order modification. No account modification. No RAG, no
vector database, no embeddings. No autonomous agents. No FastAPI. No
frontend or UI. No Power BI. Phase 5 produces *text and a decision about
that text* — nothing in this phase can take an action in the world.

## 14. Limitations

- **The dominant one, unchanged since Phase 3:** no API key, so no real LLM response has ever been generated. Everything downstream is verified structurally, never against real model output.
- The safety scanner is pattern-based and can miss paraphrased violations (§4).
- Real-data Phase 5 metrics are entirely gated on Phases 3 and 4 running for real first.
- `response_type` is a deterministic 1:1 category mapping, not a learned or contextual judgment — intentional, but it means an unusual ticket within a category still gets its category's default type.

## 15. Assumptions

- A ticket's linked order (`tickets.order_id`) is sufficient order grounding; no customer order-history aggregation.
- One response decision per ticket (no revision history) — matches the one-decision-per-phase pattern of Phases 3 and 4.
- Phase 4's thresholds are the right ones for Phase 5's re-verification too, rather than a separate set — a second set of thresholds would be a second source of truth.

## 16. Files Created / Modified

**Created (11):**
`sql/07_phase5_schema.sql`, `sql/08_phase5_validation.sql`,
`src/response/__init__.py`, `src/response/models.py`, `src/response/eligibility.py`,
`src/response/prompts.py`, `src/response/generator.py`, `src/response/engine.py`,
`src/response/safety.py`, `src/evaluation/response_metrics.py`,
`tests/test_response_models.py`, `tests/test_response_engine.py`,
`tests/test_response_pipeline.py`, `reports/phase5_evaluation.md`,
`PHASE5_SUMMARY.md`

**Modified (5):**
`src/config.py` (Phase 5 settings), `src/database/tickets.py` (4 new functions),
`src/pipeline.py` (`respond` / `respond-evaluate` commands + batch loop),
`src/logging_config.py` (Phase 5 log fields),
`src/ai/llm_client.py` (one additive alias method), `README.md`, `.env.example`

**Not modified:** all Phase 2/3/4 SQL migrations, `src/rules/*`, `src/ai/prompts.py`,
`src/ai/classifier.py`, `src/evaluation/metrics.py`, `src/evaluation/rules_metrics.py`,
all pre-existing test files, `scripts/`, `data/`.

## 17. Commands

```bash
psql -U meridian_app -d meridian_commerce -f sql/07_phase5_schema.sql
psql -U meridian_app -d meridian_commerce -f sql/08_phase5_validation.sql
python -m pytest tests/ -v
python -m src.pipeline respond --limit 10                  # dry run (safe default)
python -m src.pipeline respond --limit 1500 --live          # requires RESPONSE_DRY_RUN=false too
python -m src.pipeline respond-evaluate
```

## 18. Git

No commit was created, no history changed, nothing pushed. `.env` remains
git-ignored and was deleted from the working tree before packaging; no API
key exists anywhere in the codebase.

---

**Phase 6 was NOT started.** Stopping here for review.
