# Phase 6: Analytics & Monitoring

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Phase:** 6
**Status:** Complete. 160/160 tests passing (32 new + all 128 from Phases 3–5, unmodified). Five read-only analytical views created and validated against the live database. **Zero operational data mutated.**

---

## 1. Pre-Work: Repository & Schema Inspection

Inspected before writing anything:

- **Live schema is authoritative** — read `information_schema` directly rather than trusting the prompt's field list. Confirmed `tickets` has all 24 columns (18 original + Phase 4's `final_priority`/`rule_decision_at` + Phase 5's four `response_*` columns), and confirmed the exact types (`numeric` for confidence/sentiment, `timestamp without time zone` throughout, `date` for delivery dates — which matters for the `delivery_delay_days` subtraction).
- **Naming conventions** — SQL files are `NN_phaseN_purpose.sql`; Phase 6 continues at `09_` and `10_`. Evaluation modules live in `src/evaluation/`; reports in `reports/phaseN_evaluation.md`. Followed all three rather than introducing new patterns.
- **Data state** — 1,500 tickets, 0 classified, 0 Phase 4 decisions, 0 Phase 5 responses, but **1,410 with a first response and 1,139 resolved**. That last part matters: it means the operational layer has real data to measure even though the AI layers don't.
- **Git** — there is no git repository in this working environment (the repo lives on your machine). I could not inspect `git status` or commit history here, and I have not created, modified, or deleted any git state. Reported honestly rather than fabricating a git inspection.

## 2. Architecture

```
PostgreSQL (operational tables — untouched by Phase 6)
        │  SELECT only
        ▼
Analytical SQL Views  (sql/09_phase6_analytics_views.sql)
  vw_ticket_analytics        <- ticket grain, the Power BI fact table
  vw_classification_metrics  <- Phase 3
  vw_rule_decision_metrics   <- Phase 4
  vw_response_metrics        <- Phase 5
  vw_operational_metrics     <- AI-independent KPIs
        │
        ▼
Python Validation  (src/evaluation/analytics.py)
  independently re-derives every percentage from raw counts
  independently recomputes both medians from ticket-grain rows
  flags any disagreement, impossible value, or broken partition
        │
        ▼
Power BI-ready layer  +  reports/phase6_evaluation.md
```

## 3. Design Decisions

### NULL vs. 0 — the decision that shapes the whole layer

Every rate uses `NULLIF(denominator, 0)`, so an empty population yields
**NULL**, rendered as **"NOT AVAILABLE"**. This is not cosmetic. With the AI
pipeline unrun, `0%` accuracy would read as *"the classifier got everything
wrong"*; NULL reads as *"nothing has been classified"*. Those are opposite
conclusions from the same underlying state, and this project has spent five
phases refusing to blur them.

Coverage is the deliberate exception: `classification_coverage_pct` is
genuinely `0.00%` over all 1,500 tickets, because "what share of the backlog
has been classified" is a real, answerable question with a real answer of
zero.

### Denominator policy — stated, not assumed

Phase 4.1 existed because a metric name didn't match its denominator. So
each rate here names the population it's computed over, documented in the
SQL header and again in the report:

| Metric | Denominator |
|---|---|
| `classification_coverage_pct` | all tickets |
| `low_confidence_rate_pct` | tickets *with* a confidence value |
| `exact_category_match_rate_pct` | tickets *with* a prediction |
| `automated_rate_pct`, `human_review_rate_pct`, `urgent_human_review_rate_pct` | tickets *with* a Phase 4 decision |
| `response_processed_rate_pct` | all tickets |
| `draft/blocked/not_eligible/human_review_response_rate_pct` | tickets Phase 5 *processed* |

`tickets_with_rule_decision` was added to `vw_rule_decision_metrics` (beyond
the requested field list) so the decided population is visible alongside the
rates computed over it, rather than implied.

### Reused vocabulary, not reinvented

- `average_priority_score` uses **Low=0, Medium=1, High=2, Urgent=3** — exactly `PRIORITY_ORDER` from `src/config.py`, not a new 1–4 scale.
- `urgent_human_review` uses **Phase 4.1's** definition (`Human Review` AND priority in High/Urgent) — the same rule `derive_recommended_action` implements.
- `vw_ticket_analytics.recommended_action` reconstructs Phase 4.1's value from the two persisted columns it's a pure function of. Phase 4.1 established that it's exactly reconstructible; this view relies on that rather than re-deriving a second definition.
- Phase 5's four statuses are used verbatim; no additional operational states invented. `response_not_processed` (Phase 5 never reached the ticket) is kept distinct from `NOT_ELIGIBLE` (an actual Phase 5 ruling).

### PostgreSQL type safety — handled deliberately

- `ROUND(x, 2)` has no double-precision overload → **every** rounded value is cast `::numeric`.
- `EXTRACT(EPOCH FROM interval)` returns `numeric` on PG14+ but `double precision` on older versions → explicit casts make the file version-independent.
- `PERCENTILE_CONT` always returns double precision → cast before `ROUND`.
- Verified on PostgreSQL 16.15: all five views created and queried with zero errors.

### Grain protection

`vw_ticket_analytics` joins `customers` (N:1, NOT NULL FK) and `orders`
(N:1, nullable FK) — both row-preserving. `order_items`/`products` are
deliberately **excluded**: an order has many line items, so joining them
would multiply ticket rows and silently inflate every count built on the
view. Product-level analysis belongs in a separate order-item-grain view,
not in this one. Verified: 1,500 tickets → 1,500 rows → 1,500 distinct ids.

## 4. Read-Only Guarantee

Phase 6 contains **no** `INSERT`, `UPDATE`, `DELETE`, or `ALTER` of
operational tables. Only `CREATE OR REPLACE VIEW` and `SELECT`. The
`analytics` CLI command has deliberately **no `--live` flag** — there is
nothing for it to mutate.

One qualification, stated plainly: to verify the views' *populated* code
paths (which would otherwise never execute, since every AI field is NULL), I
ran temporary test data through them inside a **transaction that was rolled
back**. Before and after both confirmed `classified=0, phase4=0, phase5=0`.
Nothing was committed. This is the "isolate and restore state" allowance,
used once, for exactly the purpose it exists for — and worth doing, because
shipping SQL whose main analytical branches have never run would not be
portfolio quality.

## 5. Files Created / Modified

**Created (5):**
- `sql/09_phase6_analytics_views.sql` — the five views
- `sql/10_phase6_validation.sql` — structural/consistency checks
- `src/evaluation/analytics.py` — read-only validation layer
- `tests/test_analytics.py` — 32 tests
- `reports/phase6_evaluation.md`, `PHASE6_SUMMARY.md`

**Modified (2):**
- `src/pipeline.py` — added `run_analytics()` and the `analytics` subcommand
- `README.md` — appended the Phase 6 section (existing content untouched)

**Not modified:** every Phase 1–5 SQL migration, `src/ai/*`, `src/rules/*`,
`src/response/*`, `src/database/*`, `src/config.py`, all pre-existing tests,
`scripts/`, `data/`. No file deleted. No `.env` touched or committed.

## 6. Testing

**32 new tests**, all pure logic (no DB, no network):

- Percentage calculations, including exact rounding agreement with the views
- **Zero-denominator handling** — returns `None`, never 0
- Null handling across all inputs
- **Median calculations** — including interpolation matching `PERCENTILE_CONT` on even-sized populations (a discrete median would produce false alarms)
- Classification coverage, rule decision rates, response rates
- Count↔percentage consistency
- The empty-pipeline snapshot (the system's real current state) validating as **consistent, not broken**
- **14 tests that deliberately break a snapshot** — wrong coverage, broken partitions, urgent exceeding human review, rates not summing to 100, median disagreement, out-of-range percentages, negative durations, NULL where a number is expected — confirming the validator actually catches problems rather than merely passing on good data

```
python -m pytest tests/ -q
160 passed in 1.33s
```

All 128 prior tests pass unmodified.

## 7. Current Results

**Real, substantial data (operational layer only):** 1,500 tickets; 1,410
with a first response (avg 1,015.67 min, median 753.60 min); 1,139 resolved
(avg 50.27 h, median 45.09 h). The mean sitting ~35% above the median
confirms the expected right-skewed support-time distribution.

**NOT AVAILABLE:** all classification quality metrics, all rule-decision
rates, all response rates — because coverage is 0% because no
`ANTHROPIC_API_KEY` exists in this environment. Full detail, including what
this does and doesn't permit concluding, is in `reports/phase6_evaluation.md`.

## 8. Limitations

- Four of the five views have no data to report; only the operational view is meaningfully populated.
- Views are query-time (not materialized) — correct and always fresh, but a much larger `tickets` table would want materialization plus a refresh schedule for the percentile scans.
- No historical snapshotting: trends over `created_at` are available, but metric *drift* can't be reconstructed retroactively.
- `exact_category_match_rate_pct` weights all confusions equally; Phase 3's per-category precision/recall/F1 remains the better instrument.
- No git inspection was possible in this environment (§1).

## 9. Scope

Phase 6 is analytics and monitoring only. It does not send anything, decide
anything, modify any ticket/customer/order record, call any model, or execute
Power BI. No `.pbix` file was fabricated and Power BI Desktop was not run —
what's delivered is Power BI-**ready** views plus connection and dashboard
documentation.

**Phase 7 was NOT started.**
