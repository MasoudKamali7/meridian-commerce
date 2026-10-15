# Phase 6 Evaluation Report — Analytics & Monitoring

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Date:** 2026-09-17

Every figure below was read from the live database at the time of writing.
Metrics whose population is empty are reported as **NOT AVAILABLE**, never as
`0` — the distinction between "measured zero" and "nothing ran to measure"
is the point of this report.

> **Latest status (2026-10-15; reported from the user's CLI run).** Classification is now 100 of 1,500 (6.67% coverage); average confidence 0.9018; low-confidence rate 1.00%; exact category match 95.00% on 100 samples. The match is an accuracy-style backtest against synthetic seed labels, not production accuracy. Analytics validation reported `issues_found: 0`. Rule and response metrics remain as last verified in the 2026-10-13 snapshot: automated 0.07%, human review 99.93%, High/Urgent human review 3.13%; 3 responses processed (draft generation 33.33%, blocked 0.00%). Operational metrics are unchanged. The detailed values in Sections 3 and 7 are historical 2026-09-17/temporary-fixture results; see the README and dashboard pack's 2026-10-15 current-state snapshot for the latest classification metrics. The Power BI `.pbix` still needs a refresh to show the latest live classification rows.

---

## 1. What Was Measured

Five read-only analytical views (`sql/09_phase6_analytics_views.sql`):

| View | Grain | Purpose |
|---|---|---|
| `vw_ticket_analytics` | one row per ticket | Ticket + customer + order context with derived durations — the Power BI fact table |
| `vw_classification_metrics` | single row | Phase 3 classification coverage, confidence, category agreement |
| `vw_rule_decision_metrics` | single row | Phase 4 automation/human-review split, urgency, priority score |
| `vw_response_metrics` | single row | Phase 5 response-status distribution |
| `vw_operational_metrics` | single row | First response, resolution, and decision latency KPIs |

Plus a Python validation layer (`src/evaluation/analytics.py`) that reads
those views and **independently re-derives** every percentage from the raw
counts and both medians from the ticket-grain rows, so a broken view is
caught rather than trusted.

## 2. Why Each Metric Matters

- **Classification coverage** — the gate on everything downstream. Phase 4 can't rule on an unclassified ticket, and Phase 5 can't respond to an undecided one. Coverage is the leading indicator for the whole pipeline.
- **Confidence distribution / low-confidence rate** — Phase 4's automation gate is a confidence threshold, so this directly predicts how much work can ever be automated. It is *also* the input to eventually calibrating that threshold, which Phase 4.1 flagged as an open item.
- **Exact category match rate** — the only available proxy for classifier quality, with heavy caveats (§4).
- **Automated vs. human-review rate** — the core business case: how much support volume the system can safely handle without a person.
- **Urgent human review rate** — staffing signal; tells you how much of the human queue is time-critical rather than routine.
- **Response status distribution** — separates "automation was available and worked" (DRAFT_GENERATED) from "automation was available and we stopped it" (BLOCKED). The blocked rate is the safety layer's visible cost.
- **First response / resolution time (mean AND median)** — the customer-facing SLA metrics. Both are reported because support-time distributions are right-skewed; a mean well above the median signals a long tail of slow tickets that the mean alone would hide.

## 3. Latest Reported Values (CLI analytics output, 2026-10-15)

### Operational metrics — populated synthetic seed data

These metrics cover the full generated dataset. `first_response_at` and
`resolved_at` came from the Phase 2 synthetic data generator and do not depend
on any AI stage.

| Metric | Value |
|---|---|
| Total tickets | 1,500 |
| Tickets with a first response | 1,410 (94.0%) |
| Avg first response | **1,015.67 min** (~16.9 h) |
| Median first response | **753.60 min** (~12.6 h) |
| Resolved tickets | 1,139 (75.9%) |
| Avg resolution | **50.27 h** |
| Median resolution | **45.09 h** |

The mean sitting ~35% above the median on first response confirms the
expected right skew: most tickets get a reply well inside the average, and a
minority of slow ones pull the mean up. This is exactly why both are
reported.

### Classification metrics — coverage real, quality NOT AVAILABLE

| Metric | Value |
|---|---|
| Total tickets | 1,500 |
| Classified tickets | **100** |
| Classification coverage | **6.67%** |
| Confidence available | 100 |
| Average confidence | **0.9018** |
| Low-confidence rate | **1.00%** |
| Exact category matches | 95 of 100 |
| Exact category match rate | **95.00%** (synthetic-label backtest; not production accuracy) |

### Rule decision metrics

| Metric | Value |
|---|---|
| Tickets with a Phase 4 decision | **1,500** |
| Automated / human review / urgent rates | **0.07% / 99.93% / 3.13%** |
| Average priority score | **1.033** |

### Response metrics

| Metric | Value |
|---|---|
| Response processed | **3** (processed rate 0.20% of 1,500) |
| Draft / blocked rates | **33.33% / 0.00%** |

## 4. What Is Unavailable, and Why

**Historical note (2026-09-17):** no `ANTHROPIC_API_KEY` existed in that
environment then. The project has since migrated to OpenRouter, and live
classification has run. The downstream stages still have their own existing
state and are not implied to have run on all 1,500 tickets:

```
OpenRouter live calls → Phase 3 has classified 100 tickets
                      → Phase 4 has decisions for 1,500 tickets
                      → Phase 5 has processed 3 tickets
                      → Phase 6 reports metrics for the current database state
```

The 100-ticket classification pilot does not represent full-population
coverage. Phase 4 has decisions for all tickets, while Phase 5 has processed
only three. Phase 6 reports these partial states explicitly.

**On `exact_category_match_rate_pct` specifically** — three caveats that
still apply to the latest result:

1. `tickets.category` is **ground truth** (human-assigned in the Phase 2 seed data); `tickets.ai_predicted_category` is the **model prediction**. The comparison is only meaningful because these are kept strictly separate — Phase 3 was explicitly built never to overwrite the former with the latter.
2. Once predictions exist, this becomes an **accuracy-style backtest**, not validated production accuracy. The "ground truth" is synthetic seed data generated in Phase 2, not human-audited real tickets.
3. Exact match treats all errors equally. Confusing "Delivery Delay" with "Order Status Inquiry" is far less costly than confusing it with "Payment Problem", and a single accuracy number hides that. Phase 3's per-category precision/recall/F1 (`src/evaluation/metrics.py`) remains the better instrument; this view's match rate is a headline number, not a substitute.

## 5. What Can Be Concluded Safely

- **The analytical layer itself works and is internally consistent.** The latest CLI run reported 0 validation issues; the original SQL suite and independent Python re-derivation were also verified on real data and populated test data (§7).
- **Ticket grain is preserved**: 1,500 tickets → 1,500 view rows → 1,500 distinct ticket_ids, 0 duplicates. Counts built on this view are trustworthy.
- **Generated operational baselines exist** for first-response and resolution time, mean and median. They describe the synthetic dataset and can serve as internal project baselines, not observed customer operations.
- **The pipeline's partial rollout is visible in metrics.** Classification covers 100 tickets, rule decisions cover all tickets, and response processing covers three tickets.

## 6. What Cannot Yet Be Concluded

- No validated **production classifier quality** — the 95% exact-match figure is a small backtest against synthetic seed labels; precision/recall and confidence calibration have not been validated against human-audited outcomes.
- The observed automated rate is 0.07% (1 ticket); this small pilot does not establish a stable automation rate or business impact.
- Nothing about **response quality, groundedness, or hallucination frequency**, and nothing about how often the safety scanner would block real model output.
- **No cost or ROI figures.** Real API calls have been made, but token prices are not configured, so the CLI reports token counts and no invented dollar amount.
- Whether the **thresholds** (0.75 confidence, -0.7 sentiment) are well-chosen — still the open calibration item from Phase 4.1.

## 7. Validation Performed

| Check | Result |
|---|---|
| All five views exist and query without error | **PASS** |
| No `ROUND()` double-precision type errors | **PASS** (all casts explicit) |
| No divide-by-zero | **PASS** (`NULLIF` throughout) |
| Ticket grain = one row per ticket | **PASS** (1500/1500/0 duplicates) |
| Count partitions (classified+unclassified, automated+human, 4 response statuses) | **PASS** |
| Percentages within 0–100 | **PASS** |
| No negative durations | **PASS** |
| Python recomputation agrees with SQL (percentages + both medians) | **PASS**, 0 issues |
| **Populated-path verification** | **PASS** — see below |

The populated paths deserve a note. With every AI field NULL, the views'
main analytical branches (average confidence, match rate, priority score,
response rates) would never have executed — shipping SQL whose primary logic
has never run. So those branches were exercised against temporary test data
inside a **transaction that was rolled back**, and hand-checked:

- coverage 120/1500 = 8.00% ✓
- avg confidence (100×0.92 + 20×0.40)/120 = 0.8333 ✓
- match rate 100/120 = 83.33% ✓
- automated 60/100 = 60.00% ✓
- average priority score (60×0 + 40×3)/100 = 1.200 ✓

Operational state confirmed **unchanged** before and after
(`classified=0, phase4=0, phase5=0`). No data was committed; Phase 6 has
mutated nothing.

## 8. What to Monitor When Real Predictions Arrive

In priority order:

1. **Coverage first** — until it climbs, nothing else is interpretable.
2. **Confidence distribution vs. the 0.75 threshold** — if most predictions cluster just above it, the automation rate is fragile to small threshold changes.
3. **Per-category match rate**, not just the headline — watch for systematic confusion between a low-risk and a sensitive category, which is the failure mode with real business cost.
4. **Blocked rate** (Phase 5) — a rising blocked rate means the model is drifting toward claims the safety scanner rejects. This is a genuine early-warning signal.
5. **Automated rate vs. resolution time** — the business case only holds if automation doesn't degrade resolution time for the tickets it handles.
6. **Confidence-vs-correctness correlation** — the input needed to finally calibrate the thresholds rather than leaving them as documented assumptions.

## 9. Recommended Power BI Dashboard Structure

Sources: import the five views directly (see README "How to connect Power BI").
`vw_ticket_analytics` is the fact table; the four aggregate views are
single-row KPI sources.

| Page | Contents | Current state |
|---|---|---|
| **1 — Executive Overview** | Total tickets, automated rate, human review rate, classification coverage, response processing rate, avg first response, avg resolution | Operational KPIs live; refresh PBIX to show latest AI coverage and sample size |
| **2 — AI Classification** | Coverage gauge, confidence histogram, low-confidence rate, predicted-vs-actual matrix, per-category results | A 100-ticket pilot is present in the live DB; the imported PBIX snapshot is stale and needs refresh. Keep the synthetic-label and sample-size caveats visible. |
| **3 — Rule Engine & Human Review** | Automated vs. human review, final priority distribution, urgent human review, human review by category and by customer segment | Detail page not built; summary metrics exist |
| **4 — AI Response Layer** | Response processing rate, the four statuses, response generation time | Detail page not built; summary metrics exist for 3 processed tickets |
| **5 — Operations** | First response and resolution (mean vs. median side by side), delivery delay, volume by channel / category / over time | **Fully populated with real data** |

For page 2, display the 100-ticket pilot count and coverage with a visible
synthetic-label caveat. The current imported PBIX must be refreshed before
its charts reflect this live database state.

## 10. Known Limitations

- Current coverage is still a small pilot (100 of 1,500); the PBIX import snapshot has not been refreshed to include it.
- Views are computed at query time (no materialization). Correct and always-fresh, but on a much larger `tickets` table the percentile scans would want a materialized view and a refresh schedule.
- `vw_ticket_analytics` deliberately excludes `order_items`/`products` to protect grain — product-level analysis needs a separate view at order-item grain, not a modification of this one.
- `exact_category_match_rate_pct` is a single blunt number (§4.3).
- Phase 6 reads the current state only; there is no historical snapshotting, so trends over time can be drawn from `created_at` but metric *drift* (e.g. accuracy falling month over month) can't be reconstructed retroactively.
- `median_*` uses `PERCENTILE_CONT` (interpolated). The Python cross-check matches this deliberately; a discrete median would differ slightly on even-sized populations.
