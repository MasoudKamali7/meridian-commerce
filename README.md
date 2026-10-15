# Meridian Commerce — AI-Powered Customer Support Automation System

Meridian Commerce is a portfolio project that demonstrates how a customer-support operation can combine **PostgreSQL, Python, deterministic business rules, LLM-based classification, human-in-the-loop controls, response safety checks, and read-only analytics** into a controlled support automation pipeline.

The project is intentionally designed around a key principle:

> AI can assist the support process, but deterministic business rules and human review remain authoritative where risk is higher.

The system does not send emails, issue refunds, modify customer accounts, or make autonomous business decisions.

---

## Project Overview

Meridian Commerce simulates a commerce company that receives customer-support tickets related to orders, products, payments, accounts, refunds, complaints, and general support.

The pipeline processes a support ticket through several controlled stages:

```text
Customer Support Ticket
        │
        ▼
PostgreSQL
        │
        ▼
AI Classification
        │
        ▼
Deterministic Business Rules
        │
        ▼
Human-in-the-Loop Decision
        │
        ▼
AI Response Layer
        │
        ▼
Safety Scanner
        │
        ▼
Stored Draft / Blocked Response
        │
        ▼
Read-Only Analytics
        │
        ▼
Power BI-Ready Data Layer
```

---

## Power BI Dashboard

A three-page Power BI report built on the Phase 6 views (Import mode, PostgreSQL connector). The data is **synthetic**; nothing here is real customer data. Details live in [`meridian_powerbi_dashboard_pack/`](meridian_powerbi_dashboard_pack/).

| Page | What it shows |
|---|---|
| **Executive Overview** | Total tickets; AI classification coverage and sample size; routing split (human review, High/Urgent human review, automated); decision-path and original-priority distributions; Date and Channel slicers; AI coverage warning |
| **AI Classification** | Classified tickets, coverage, categories of the pilot sample, final-priority distribution, and an explicit sample-size limitation notice. No accuracy, match-rate or confidence figure is shown on purpose |
| **Operational Performance** | First response (average / median), average resolution time, tickets with a resolution timestamp, rule decisions, responses generated, response-status and resolution-type charts |

**Latest reported data state (2026-10-15):** 1,500 tickets; 100 classified (6.67% coverage); 1,499 routed to human review (99.93%), 1 automated (0.07%); 47 High/Urgent human-review tickets (3.13%); 3 responses processed; 1,410 tickets with a first response (avg 1,015.67 min, median 753.60 min); 1,139 with a resolution timestamp (avg 50.27 h, median 45.09 h). The user ran `python -m src.pipeline analytics`; it reported `issues_found: 0`. The Power BI `.pbix` remains a 2026-10-13 snapshot and must be refreshed separately.

**How to read it honestly**

- **AI quality is not validated for production.** 100 of 1,500 tickets carry an AI prediction. The 95.0% exact-category match is an accuracy-style backtest against synthetic seed labels, not validated production accuracy, and is deliberately not shown as an accuracy claim.
- **The 99.93% human-review rate is mostly a consequence of missing classifications, not a finding about routing quality.** Rule `missing_classification` forces Human Review for any ticket without an AI category; it fired on 1,400 of the 1,499 human-review tickets.
- **High priority is mostly the VIP high-value-order rule.** 45 of the 47 High/Urgent human-review tickets are unclassified tickets raised to High by that rule; the other 2 are AI-classified tickets.
- **Timing metrics describe synthetic history**, not AI impact. `rule_decision_hours` and `response_generation_hours` are not shown: decisions were written in 2026 for tickets created from 2022, so those durations are batch-run artefacts.

**Verification.** The PBIX tables were reconciled against the SQL views executed on PostgreSQL 16, the rule engine was re-run over the seed CSVs, and the test suite passes. See [`meridian_powerbi_dashboard_pack/docs/validation_report.md`](meridian_powerbi_dashboard_pack/docs/validation_report.md) for method, results and limits.

---
## Project Structure

```
meridian-commerce/
├── README.md                          <- you are here
├── PHASE1_business_problem_and_data_design.md
├── PHASE2_SUMMARY.md ... PHASE6_SUMMARY.md   <- per-phase decisions, results, checklists
├── MIGRATION_NOTES.md                 <- one-off OpenRouter migration notes (can be deleted once applied)
├── migrate_to_openrouter.py           <- one-off migration helper (can be deleted once applied)
├── requirements.txt
├── .env.example                       <- copy to .env and fill in (never commit .env)
├── .gitignore
├── sql/
│   ├── 01_schema.sql                  <- tables + all column/row-level constraints
│   ├── 02_triggers.sql                <- cross-table business-rule enforcement
│   ├── 03_indexes.sql                 <- indexes (applied after bulk load)
│   ├── 04_validation.sql              <- data-quality validation suite
│   ├── 05_phase4_schema.sql           <- Phase 4 migration: final_priority, rule_decision_at
│   ├── 06_phase4_validation.sql
│   ├── 07_phase5_schema.sql           <- Phase 5 migration: response_status/type/draft/generated_at
│   ├── 08_phase5_validation.sql
│   ├── 09_phase6_analytics_views.sql  <- the five read-only analytical views (Power BI source)
│   └── 10_phase6_validation.sql
├── scripts/
│   ├── generate_data.py               <- synthetic data generator (seeded, reproducible)
│   └── load_data.py                   <- bulk-loads the CSVs into PostgreSQL via COPY
├── data/                              <- customers, products, orders, order_items, tickets (synthetic CSVs)
├── src/
│   ├── config.py                      <- env-var settings + approved vocabularies (single source of truth)
│   ├── logging_config.py              <- structured (JSON-lines) logging, no PII
│   ├── pipeline.py                    <- CLI: classify / evaluate / rules / rules-evaluate / respond / respond-evaluate / analytics
│   ├── ai/                            <- prompts, llm_client (OpenRouter, free models only), classifier
│   ├── database/                      <- connection helpers and minimal-field fetch/update queries
│   ├── evaluation/                    <- metrics, rules_metrics, response_metrics, analytics (Phase 6 validator)
│   ├── rules/                         <- models, individual rules, engine with documented precedence
│   └── response/                      <- models, eligibility, prompts, generator, safety scanner, engine
├── tests/                             <- 226 tests (LLM and DB are faked; no network or API key needed)
├── reports/                           <- phase3-6 evaluation reports
├── logs/                              <- JSON-lines run logs (git-ignored)
└── meridian_powerbi_dashboard_pack/   <- Power BI: DAX, Power Query, SQL extracts, docs, sample metrics
    └── (add the .pbix here)
```

### Structure note (Phase 3)

The user-suggested `src/` layout is kept almost exactly as given — it's
already a clean, standard separation. Two additions:
- **`src/evaluation/metrics.py`** — needed for the accuracy/precision/recall/
  F1/confusion-matrix requirements, which the suggested tree didn't have an
  explicit home for.
- **`src/logging_config.py`** — split out from `config.py` so "what the
  settings are" and "how logging is wired up" stay independently readable.

---

## Phase 2: PostgreSQL Schema & Synthetic Data

### Why this structure instead of the `schema.sql / constraints.sql / seed.sql` layout
  foreign keys, `NOT NULL`, `UNIQUE`, and `CHECK` constraints are normally
  declared inline with `CREATE TABLE` — that's how you read the table's full
  contract in one place. Splitting them into a second file only pays off once
  you have a migration tool tracking schema history, which is overkill for an
  MVP portfolio project.
- **`03_indexes.sql` stays separate.** This one's a genuinely common
  professional pattern: indexes are applied *after* the bulk data load so the
  initial `COPY` isn't slowed down by index maintenance, and keeping them
  separate documents indexing decisions on their own.
- **`02_triggers.sql` is new** (not in the original suggested layout). One
  approved business rule — "a ticket's order must belong to the same
  customer as the ticket" — spans two tables, which a `CHECK` constraint
  can't express in PostgreSQL. It needed a trigger, so it gets its own file.
- **`seed.sql` replaced by `data/*.csv` + `scripts/generate_data.py` +
  `scripts/load_data.py`.** The realistic, non-uniform, cross-table-consistent
  data this project needs (popularity-weighted product sales, delayed-orders
  correlating with delivery-delay tickets, VIP customers ordering more, etc.)
  is impractical to express in raw SQL `INSERT`/`generate_series` statements.
  Python (pandas + NumPy + Faker) generating CSVs, loaded via `COPY`, is the
  standard data-engineering pattern for this and demonstrates the relevant
  skill far better than hand-written SQL seed data would.

---

## Setup Guide — PostgreSQL 18 on Windows (VS Code + PowerShell, no Docker)

1. **Install PostgreSQL 18.** Download the Windows installer from
   [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
   (the EDB installer). During setup:
   - Set a password for the `postgres` superuser — remember it.
   - Keep the default port `5432`.
   - You can leave Stack Builder unchecked (not needed here).

2. **Add PostgreSQL to your PATH.** The installer usually does this, but if
   `psql` isn't recognized later, add
   `C:\Program Files\PostgreSQL\18\bin` to your `PATH` environment variable
   and open a new PowerShell window.

3. **Verify the install.** In PowerShell:
   ```powershell
   psql --version
   ```

4. **Open the project folder in VS Code**, then open an integrated terminal
   (PowerShell, VS Code's default on Windows).

5. **Create the database and app role.** Connect as the superuser and run:
   ```powershell
   psql -U postgres
   ```
   Then, at the `psql` prompt:
   ```sql
   CREATE DATABASE meridian_commerce;
   CREATE USER meridian_app WITH PASSWORD 'choose_a_password';
   GRANT ALL PRIVILEGES ON DATABASE meridian_commerce TO meridian_app;
   \c meridian_commerce
   GRANT ALL ON SCHEMA public TO meridian_app;
   \q
   ```

6. **Apply the schema, triggers, and indexes** (from the project root in
   PowerShell — set the password for this session first so you're not
   prompted on every command):
   ```powershell
   $env:PGPASSWORD = "choose_a_password"
   psql -U meridian_app -d meridian_commerce -f sql\01_schema.sql
   psql -U meridian_app -d meridian_commerce -f sql\02_triggers.sql
   ```

7. **Set up Python** (in the same VS Code terminal):
   ```powershell
   python -m venv venv
   venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

8. **Generate the synthetic data** (writes CSVs to `data/`):
   ```powershell
   cd scripts
   python generate_data.py
   cd ..
   ```

9. **Load the data into PostgreSQL:**
   ```powershell
   cd scripts
   python load_data.py --dbname meridian_commerce --user meridian_app --password choose_a_password --data-dir ../data
   cd ..
   ```

10. **Now apply the indexes** (after the bulk load, per the design decision above):
    ```powershell
    psql -U meridian_app -d meridian_commerce -f sql\03_indexes.sql
    ```

11. **Run the validation suite:**
    ```powershell
    psql -U meridian_app -d meridian_commerce -f sql\04_validation.sql
    ```

**Troubleshooting:** if `psql` reports a password/authentication error, confirm
`$env:PGPASSWORD` is set in your current PowerShell session (it doesn't
persist across windows), or just omit it and enter the password when prompted.

> This project was developed and validated against PostgreSQL 16 in the
> development sandbox used to build it (the newest version available through
> that environment's package manager). Nothing in the schema uses any
> version-specific syntax beyond standard `CHECK` constraints and `plpgsql`
> triggers, which have been stable for many major versions, so it's expected
> to run unchanged on PostgreSQL 18 — but this hasn't been separately
> confirmed on 18 itself.

---

## Re-running

Everything is seeded (`SEED = 42` in `generate_data.py`), and `load_data.py`
truncates and reloads all five tables (`RESTART IDENTITY CASCADE`) before
loading, so the whole pipeline is safe to re-run from scratch at any time.

---

## Phase 3: AI Ticket Classification & Information Extraction

### Architecture

```
 historical ticket (DB)
        │  message_text
        ▼
 src/ai/prompts.py ──────► builds system prompt + forced "classify_ticket" tool call
        │
        ▼
 src/ai/llm_client.py ───► OpenRouterLLMClient.classify()
        │                   - retries with exponential backoff on timeout/rate-limit/5xx
        │                   - raises a typed error (auth/timeout/rate_limit/api/malformed)
        │                     on final failure — never silently returns junk
        ▼
 src/ai/classifier.py ───► ValidatedClassification (Pydantic)
        │                   - category/priority MUST be in the approved Phase 1 vocab
        │                   - sentiment_score in [-1,1], confidence in [0,1]
        │                   - ANY failure → ClassificationResult(success=False, error_type=...)
        ▼
 src/pipeline.py ────────► classify_batch()
        │                   - dry_run=True  → log only, no DB write (still calls the real LLM)
        │                   - dry_run=False → update_ticket_classification() for successes only
        ▼
 src/database/tickets.py ─► UPDATE tickets SET ai_predicted_category=..., 
                              classification_confidence=..., sentiment_score=..., 
                              decision_at=now() WHERE ticket_id=...
                              (category, created_at, customer_id, order_id, status,
                               decision_path, priority are NEVER touched by Phase 3)
```

A second entry point, `evaluate`, reads back `ai_predicted_category` vs. the
original `category` for every classified ticket and computes accuracy,
per-category precision/recall/F1, macro F1, and a confusion matrix
(`src/evaluation/metrics.py`).

### Setup

1. Copy the environment template and fill in real values:
   ```powershell
   copy .env.example .env
   ```
   Edit `.env` and set at minimum `DB_PASSWORD` (from your Phase 2 setup) and
   `OPENROUTER_API_KEY`.
2. Install the additional Phase 3 dependencies (already in `requirements.txt`):
   ```powershell
   pip install -r requirements.txt
   ```

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Phase 2 database connection | `localhost` / `5432` / `meridian_commerce` / `meridian_app` / *(required)* |
| `OPENROUTER_API_KEY` | LLM provider credential (OpenRouter) — **required for any live or dry-run classification call** | *(required, never hard-coded)* |
| `MODEL_NAME` | Which model to call. Free routing only: `openrouter/free` or a model id ending in `:free`; anything else is rejected at startup | `openrouter/free` |
| `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES` | LLM call tuning | `1024` / `30` / `3` |
| `DRY_RUN` | Safety switch — see note below | `true` |
| `BATCH_SIZE` | Default ticket count for `classify` if `--limit` isn't passed | `10` |
| `LOG_LEVEL`, `LOG_DIR` | Logging | `INFO` / `./logs` |
| `INPUT_TOKEN_PRICE_PER_MILLION`, `OUTPUT_TOKEN_PRICE_PER_MILLION` | Optional — only set if you have confirmed current pricing; otherwise cost is reported as "not available," never guessed | *(unset)* |

**Dry-run safety rule:** going live requires **both** `DRY_RUN=false` in
`.env` **and** the `--live` flag on the command line. Either one alone keeps
you in dry-run mode. This is deliberate double-confirmation, not an
oversight — see `PHASE3_SUMMARY.md`.

### Example: dry-run command (safe — calls the real LLM, never writes to the DB)

```powershell
python -m src.pipeline classify --limit 10
```

The JSON output includes `classification_backlog_before` and
`classification_backlog_after`, counted from persisted database fields. In a
dry run those counts should be unchanged; in a live run, `classified_tickets`
only increases for validated successful predictions that were actually
written. This is the safest way to track a long backlog without mistaking a
small pilot sample for full coverage.

### Example: batch-processing command (writes to the database)

```powershell
# after inspecting the dry-run output above and confirming DRY_RUN=false in .env:
python -m src.pipeline classify --limit 100 --live
# then, once you trust it:
python -m src.pipeline classify --limit 1500 --live
```

### Evaluation

```powershell
python -m src.pipeline evaluate
```

Reads every ticket with a non-null `ai_predicted_category`, compares it to
the original `category`, and prints overall accuracy, macro F1, and a
per-category precision/recall/F1 breakdown. See `reports/phase3_evaluation.md`
for the full methodology and — honestly — the current status of real results
in the environment this project was built in (short version: the pipeline
and all its validation/error-handling/dry-run logic were built and verified
end-to-end, but no LLM credential was available when that report was written;
the project has since moved to OpenRouter and a 100-ticket live pilot exists — see
Phase 6 below for current results).

### Running the tests

```powershell
pytest tests/ -v
```

58 tests total: the original 15 Phase 3 tests (fake LLM client, no network
calls) plus 43 new Phase 4 tests (pure rule-engine logic, mocked database
cursor, no LLM involved at all for this phase).

---

## Phase 4: Deterministic Business Rule Engine + Human-in-the-Loop Decisioning

### Architecture

```
Phase 3 outputs (ai_predicted_category, classification_confidence, sentiment_score)
                    +
Order/customer context (order_value, customer_segment)
                    │
                    ▼
        TicketContext (Pydantic — the ONLY thing the rule engine sees)
                    │
                    ▼
        src/rules/engine.py — every rule in rules.py runs, every time
          ├─ Priority rules  → final_priority = MAX floor among triggered rules
          └─ Human-review rules → decision_path = "Human Review" if ANY fired
                    │
                    ▼
              Decision (final_priority, decision_path, recommended_action,
                        triggered_rules, reasons, conflicting_signals)
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
     dry_run=True        dry_run=False
     log only            writes ONLY final_priority, decision_path,
                          rule_decision_at (never category, priority,
                          ai_predicted_category, or any Phase 1–3 field)
```

Full rule definitions, precedence rules, and the reasoning behind every
threshold are in `PHASE4_SUMMARY.md`.

### Database changes

Two new nullable columns on `tickets` (`sql/05_phase4_schema.sql`):
`final_priority` (VARCHAR(10), CHECK'd against the same Low/Medium/High/Urgent
vocabulary) and `rule_decision_at` (TIMESTAMP). `decision_path` already
existed from Phase 1/2 and is exactly what Phase 4 populates — no new
"human review" flag was added, since that field already serves the purpose.

### Setup

No new dependencies — Phase 4 reuses Pydantic (already installed for Phase
3). Apply the migration once:

```powershell
psql -U meridian_app -d meridian_commerce -f sql\05_phase4_schema.sql
```

### Environment variables (new in Phase 4)

| Variable | Purpose | Default |
|---|---|---|
| `HIGH_VALUE_ORDER_THRESHOLD` | Order value ($) above which a VIP customer's ticket gets a priority floor of High | `450.0` — grounded in a real percentile (Phase 2 order data), but still a business-rule assumption about what counts as "high value," not calibrated against outcomes |
| `LOW_CONFIDENCE_THRESHOLD` | classification_confidence below this forces human review | `0.75` — **initial threshold, not empirically calibrated.** No real Phase 3 classification has run yet to calibrate against; revisit once one has |
| `STRONG_NEGATIVE_SENTIMENT_THRESHOLD` | sentiment_score at/below this forces human review AND raises priority to High | `-0.7` — **initial threshold, not empirically calibrated**, same caveat as above |
| `RULES_DRY_RUN` | Safety switch for the `rules` command — same double-confirmation pattern as Phase 3's `DRY_RUN` | `true` |
| `RULES_BATCH_SIZE` | Default ticket count for `rules` if `--limit` isn't passed | `10` |

**Same double-confirmation safety rule as Phase 3, preserved unweakened:**
going live requires **both** `RULES_DRY_RUN=false` in `.env` **and** `--live`
on the command line.

### Example: dry-run command (safe — reads real data, never writes)

```powershell
python -m src.pipeline rules --limit 10
```

### Example: batch-processing command (writes to the database)

```powershell
python -m src.pipeline rules --limit 1500 --live
```

### Evaluation

```powershell
python -m src.pipeline rules-evaluate
```

Reads `decision_path`/`final_priority` back from the database. See
`reports/phase4_evaluation.md` for the actual current results (dominated by
"no AI classification exists yet," honestly reported) and a clearly-labeled
simulated run showing the fuller range of behavior.

---

## Phase 5: AI Support Decision & Response Layer

### Architecture

```
Ticket (Phase 3 outputs + Phase 4 decision + order/product context)
                    │
                    ▼
        ResponseContext (Pydantic — no customer name/email/phone, no order total)
                    │
                    ▼
        eligibility.py — deterministic; reads Phase 4's ruling and
          re-verifies its preconditions (can only ever fail SAFE)
                    │
          ┌─────────┼─────────────────────┐
          ▼         ▼                     ▼
   NOT_ELIGIBLE  human_review      automated_eligible
   (no LLM call)     │                    │
                     ▼                    ▼
              generator.py + safety.py scan
                     │                    │
                     ▼                    ▼
          HUMAN_REVIEW_DRAFT       DRAFT_GENERATED (scan passed)
          customer_facing=False    customer_facing=True
                                   — or BLOCKED (scan failed; text discarded)
```

**Phase 4 remains authoritative.** Phase 5 never overrides a Human Review
ruling and can never promote a ticket to automation.

### Response statuses

| Status | customer_facing | requires_human_review | Meaning |
|---|---|---|---|
| `NOT_ELIGIBLE` | false | false | Phase 4 hasn't decided this ticket yet |
| `DRAFT_GENERATED` | **true** | false | Approved customer-facing draft |
| `HUMAN_REVIEW_DRAFT` | false | true | Internal agent-reference draft only |
| `BLOCKED` | false | true | Automation was authorized, but no safe draft could be produced |

`customer_facing` and `requires_human_review` are **derived** from
`response_status`, not stored — a Pydantic validator makes an inconsistent
decision impossible to construct.

### Response types

`ORDER_STATUS`, `PRODUCT_QUESTION`, `PAYMENT_SUPPORT`, `ACCOUNT_SUPPORT`,
`REFUND_SUPPORT`, `ORDER_ISSUE`, `COMPLAINT`, `GENERAL_SUPPORT`.

A response type classifies the response **purpose only**. `REFUND_SUPPORT`
means "a message about a refund request" — it never means a refund was
issued. Phase 5 cannot take any action in the world.

### Database changes

`sql/07_phase5_schema.sql` adds four nullable columns to `tickets`:
`response_status`, `response_type`, `response_draft`, `response_generated_at`
(all CHECK-constrained), plus a constraint ensuring BLOCKED/NOT_ELIGIBLE
never carry a draft. Apply once:

```powershell
psql -U meridian_app -d meridian_commerce -f sql\07_phase5_schema.sql
```

### Environment variables (new in Phase 5)

| Variable | Purpose | Default |
|---|---|---|
| `RESPONSE_DRY_RUN` | Safety switch for `respond` — same double-confirmation as Phases 3/4 | `true` |
| `RESPONSE_BATCH_SIZE` | Default ticket count if `--limit` isn't passed | `10` |
| `GENERATE_INTERNAL_DRAFTS` | Whether to draft internal agent-reference text for human-review tickets | `true` |

Phase 5 reuses `LOW_CONFIDENCE_THRESHOLD` and
`STRONG_NEGATIVE_SENTIMENT_THRESHOLD` from Phase 4 rather than defining a
second set — one source of truth.

**Without an `OPENROUTER_API_KEY`, Phase 5 degrades honestly:** it still makes
real eligibility and routing decisions, generates no drafts, reports
`generator_available: false`, and says so — it does not crash or pretend.

### Example commands

```powershell
python -m src.pipeline respond --limit 10             # dry run (safe default)
python -m src.pipeline respond --limit 1500 --live     # needs RESPONSE_DRY_RUN=false too
python -m src.pipeline respond-evaluate
```

### Safety

Three independent layers: prompt-level NEVER rules, a deterministic
post-generation scanner (`src/response/safety.py`) that discards any draft
claiming a refund/compensation/payment reversal/account or order change/
completed action or mentioning AI internals, and structural Pydantic
invariants. The scanner is a pattern matcher, not semantic understanding —
it catches plainly-worded violations and can miss paraphrased ones. It's a
floor, not a guarantee. See `PHASE5_SUMMARY.md` §4.

---

# Phase 6 — Analytics & Monitoring

Turns the operational system built in Phases 1–5 into a measurable one.
**Phase 6 is strictly read-only**: it creates views and runs SELECTs, and
never mutates a ticket, customer, or order record.

## Architecture

```
PostgreSQL (operational tables — untouched)
        │  SELECT only
        ▼
Analytical SQL Views      sql/09_phase6_analytics_views.sql
        │
        ▼
Python Validation         src/evaluation/analytics.py
   (independently re-derives every % and both medians)
        │
        ▼
Power BI-ready layer  +  reports/phase6_evaluation.md
```

## Objectives

1. Expose business and AI metrics as clean, importable SQL views.
2. Validate those metrics independently in Python so a broken view is caught, not trusted.
3. Report honestly which metrics are measurable today and which are not.
4. Prepare a Power BI-consumable layer and build a dashboard on top of it (see **Power BI Dashboard** near the top).

## The SQL analytical layer

| View | Grain | Covers |
|---|---|---|
| `vw_ticket_analytics` | **one row per ticket** | Ticket + customer + order fields, plus derived `delivery_delay_days`, `first_response_minutes`, `resolution_hours`, `rule_decision_hours`, `response_generation_hours`, `final_priority_score`, `recommended_action` |
| `vw_classification_metrics` | single row | Phase 3 coverage, confidence stats, exact category match |
| `vw_rule_decision_metrics` | single row | Phase 4 automated/human-review split, urgent human review, avg priority score |
| `vw_response_metrics` | single row | Phase 5 status distribution and rates |
| `vw_operational_metrics` | single row | First response / resolution / decision latency, mean **and** median |

Apply and validate:

```powershell
psql -U meridian_app -d meridian_commerce -f sql\09_phase6_analytics_views.sql
psql -U meridian_app -d meridian_commerce -f sql\10_phase6_validation.sql
```

### Metric definitions (denominators stated explicitly)

| Metric | Numerator / Denominator |
|---|---|
| `classification_coverage_pct` | classified / **all tickets** |
| `low_confidence_rate_pct` | confidence < 0.75 / tickets **with a confidence value** |
| `exact_category_match_rate_pct` | prediction == ground truth / tickets **with a prediction** |
| `automated_rate_pct` | Automated / tickets **with a Phase 4 decision** |
| `human_review_rate_pct` | Human Review / tickets **with a Phase 4 decision** |
| `urgent_human_review_rate_pct` | Human Review AND priority High/Urgent / tickets **with a decision** (Phase 4.1's definition, reused) |
| `average_priority_score` | Low=0, Medium=1, High=2, Urgent=3 — the `config.py` `PRIORITY_ORDER` scale |
| `response_processed_rate_pct` | processed / **all tickets** |
| `draft/blocked/not_eligible/human_review_response_rate_pct` | status count / tickets **Phase 5 processed** |

**NULL means NOT AVAILABLE, never 0.** Every rate uses
`NULLIF(denominator, 0)`. With no AI predictions recorded, `0%` accuracy
would read as "the classifier got everything wrong"; NULL correctly reads as
"nothing has been classified".

`tickets.category` is **ground truth**; `tickets.ai_predicted_category` is
the **model prediction**. Their comparison becomes an accuracy-**style**
backtest once real predictions exist — it is never validated production
accuracy.

## Python evaluation

```powershell
python -m src.pipeline analytics
```

Read-only by construction — the command has no `--live` flag because there is
nothing for it to mutate. It reads the views, **independently recomputes**
every percentage from the raw counts and both medians from the ticket-grain
rows, and reports any disagreement, impossible value (e.g. urgent human
review exceeding human review), broken partition, or out-of-range percentage.

## Latest reported results (2026-10-15)

The original Phase 6 report was written when no AI, rule-engine or response data existed. Since then, 100 tickets were classified live, the rule engine was run live over all 1,500 tickets, and 3 responses were processed. The user-reported `python -m src.pipeline analytics` run on 2026-10-15 reports **0 issues**. Rule, response, and operational values below remain as in the 2026-10-13 snapshot; refresh against the database before treating those values as current.

| Layer | Metric | Value |
|---|---|---|
| Classification | Classified / coverage | 100 of 1,500 / 6.67% |
| Classification | Average confidence | 0.9018 (100 samples; not evidence of production quality) |
| Classification | Low-confidence rate | 1.00% |
| Classification | Exact category match | 95.0% on 100 samples — accuracy-*style* backtest against synthetic labels, **not** production accuracy |
| Rules | Tickets with a decision | 1,500 |
| Rules | Automated / human review | 0.07% (1) / 99.93% (1,499) |
| Rules | High/Urgent human review (`urgent_human_review_rate_pct`) | 3.13% (47) |
| Responses | Processed / draft-generation rate | 3 / 33.33% (1 draft, 2 human-review drafts, 0 blocked) |
| Operations | First response: tickets / avg / median | 1,410 / 1,015.67 min / 753.60 min |
| Operations | Resolved (has `resolved_at`): tickets / avg / median | 1,139 / 50.27 h / 45.09 h |

Interpretation limits: 100 predictions are a small pilot, and the labels are synthetic; no production accuracy or business-impact claim is supported. The 99.93% human-review rate is mostly the `missing_classification` rule firing on unclassified tickets. `resolved_tickets` counts tickets with a `resolved_at` timestamp, which includes tickets whose status is now `Reopened`.

## Testing

```powershell
pytest tests/ -q      # 226 passed
```

The 32 Phase 6 tests cover percentage math, zero denominators, null handling, median interpolation (matching `PERCENTILE_CONT`), coverage/rate calculations and count-to-percentage consistency, including 14 that deliberately corrupt a snapshot to confirm the validator catches problems.

SQL validation (`sql/10_phase6_validation.sql`) confirms: all five views exist and query cleanly, no `ROUND()` type errors, no divide-by-zero, ticket grain is exactly one row per ticket (1500/1500, 0 duplicates), all count partitions hold, all percentages are in range, and there are no negative durations.

## How to connect Power BI to PostgreSQL

1. **Get Data → PostgreSQL database**. Server `localhost:5432`, Database `meridian_commerce`.
2. Authenticate as `meridian_app`. For a real deployment, create a dedicated **read-only** role instead:
   ```sql
   CREATE ROLE powerbi_reader LOGIN PASSWORD '<choose-one>';
   GRANT CONNECT ON DATABASE meridian_commerce TO powerbi_reader;
   GRANT USAGE ON SCHEMA public TO powerbi_reader;
   GRANT SELECT ON vw_ticket_analytics, vw_classification_metrics,
                   vw_rule_decision_metrics, vw_response_metrics,
                   vw_operational_metrics TO powerbi_reader;
   ```
   That role can read the analytical layer and nothing else.
3. Import the five `vw_*` views (**Import** mode at this data size).
4. Model: `vw_ticket_analytics` (query name `Tickets`) is the fact table. The four single-row summary views stay **disconnected**. Add a `Date` table and relate `Date[Date]` to a date-only column derived from `Tickets[created_at]` (many-to-one, single direction).
5. Mark `Date` as the date table and turn **Auto date/time** off (File → Options → Current File → Data Load).
6. Add the measures from `meridian_powerbi_dashboard_pack/dax/measures.dax`. Full steps: `meridian_powerbi_dashboard_pack/docs/dashboard_build_guide.md`.

## Dashboard pages: built vs. planned

| Page | Status |
|---|---|
| Executive Overview | Built |
| AI Classification | Built (coverage and pilot sample only; no quality metric) |
| Operational Performance | Built |
| Rule Engine & Human Review (detail) | Not built — planned |
| Response & Safety (detail) | Not built — planned; response status currently appears as one chart on Operational Performance |

Do not chart AI quality, match rate or confidence on any page until classification coverage is large enough to support it.

## Limitations

- AI classification covers 6.67% of tickets. The 100-sample match figure is only a backtest against synthetic labels; no production-quality or business-impact claim is supportable.
- The dashboard's headline routing numbers are driven by missing classifications (see **Power BI Dashboard**).
- Views are query-time, not materialized: correct and always fresh, but a much larger table would want materialization plus a refresh schedule.
- `vw_ticket_analytics` excludes `order_items`/`products` to protect ticket grain; product-level analysis needs its own order-item-grain view.
- No historical snapshotting, so metric *drift* can't be reconstructed retroactively.
- The `.pbix` imports a snapshot; it refreshes only where it can reach the local PostgreSQL server.
