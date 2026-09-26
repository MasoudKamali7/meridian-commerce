# Phase 6 Evaluation Report — Analytics & Monitoring

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Date:** 2026-09-17

Every figure below was read from the live database at the time of writing.
Metrics whose population is empty are reported as **NOT AVAILABLE**, never as
`0` — the distinction between "measured zero" and "nothing ran to measure"
is the point of this report.

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

## 3. Current Values (read from the live database)

### Operational metrics — **REAL, substantial data**

These are the only Phase 6 metrics currently backed by real volume, because
`first_response_at` / `resolved_at` came from the Phase 2 generator and don't
depend on any AI stage.

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
| Classified tickets | **0** |
| Classification coverage | **0.00%** |
| Confidence available | 0 |
| Average / min / max confidence | **NOT AVAILABLE** |
| Low-confidence rate | **NOT AVAILABLE** |
| Exact category matches | 0 |
| Exact category match rate | **NOT AVAILABLE** |

### Rule decision metrics — NOT AVAILABLE

| Metric | Value |
|---|---|
| Tickets with a Phase 4 decision | **0** |
| Automated / human review / urgent rates | **NOT AVAILABLE** |
| Average priority score | **NOT AVAILABLE** |

### Response metrics — NOT AVAILABLE

| Metric | Value |
|---|---|
| Response processed | **0** (processed rate 0.00% of 1,500) |
| Draft / blocked / not-eligible rates | **NOT AVAILABLE** |

## 4. What Is Unavailable, and Why

**No `ANTHROPIC_API_KEY` exists in this environment.** That single fact
cascades the length of the pipeline:

```
no API key → Phase 3 never classified a real ticket
           → Phase 4 has no classification to rule on (0 decisions)
           → Phase 5 has no decision to respond to (0 processed)
           → Phase 6 can measure the operational layer, and nothing else
```

This is not a Phase 6 defect and not a bug anywhere. Each layer is correctly
declining to act on inputs that don't exist, and Phase 6 is correctly
reporting that rather than filling the gap.

**On `exact_category_match_rate_pct` specifically** — three caveats, all of
which survive the arrival of an API key:

1. `tickets.category` is **ground truth** (human-assigned in the Phase 2 seed data); `tickets.ai_predicted_category` is the **model prediction**. The comparison is only meaningful because these are kept strictly separate — Phase 3 was explicitly built never to overwrite the former with the latter.
2. Once predictions exist, this becomes an **accuracy-style backtest**, not validated production accuracy. The "ground truth" is synthetic seed data generated in Phase 2, not human-audited real tickets.
3. Exact match treats all errors equally. Confusing "Delivery Delay" with "Order Status Inquiry" is far less costly than confusing it with "Payment Problem", and a single accuracy number hides that. Phase 3's per-category precision/recall/F1 (`src/evaluation/metrics.py`) remains the better instrument; this view's match rate is a headline number, not a substitute.

## 5. What Can Be Concluded Safely

- **The analytical layer itself works and is internally consistent.** 0 validation issues from both the SQL suite and the independent Python re-derivation — verified on real data *and* on populated test data (§7).
- **Ticket grain is preserved**: 1,500 tickets → 1,500 view rows → 1,500 distinct ticket_ids, 0 duplicates. Counts built on this view are trustworthy.
- **Real operational baselines now exist** for first-response and resolution time, mean and median. These are genuine pre-automation baselines — exactly what you'd want to measure any future automation against.
- **The pipeline fails safe end-to-end.** Every stage with missing input declines rather than guesses, and that behavior is now visible in metrics rather than only in code.

## 6. What Cannot Yet Be Concluded

- Nothing about **classifier quality** — accuracy, precision, recall, confusion patterns, or confidence calibration.
- Nothing about **automation rate in practice**. The theoretical rate depends entirely on the classifier's confidence distribution, which is unmeasured.
- Nothing about **response quality, groundedness, or hallucination frequency**, and nothing about how often the safety scanner would block real model output.
- **No cost or ROI figures.** No real API calls have ever been made.
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
| **1 — Executive Overview** | Total tickets, automated rate, human review rate, classification coverage, response processing rate, avg first response, avg resolution | Operational KPIs live; AI KPIs must render as "Not available" |
| **2 — AI Classification** | Coverage gauge, confidence histogram, low-confidence rate, predicted-vs-actual matrix, per-category results | **Entirely unavailable today** — must display an explicit "No AI predictions recorded" state, never empty visuals that read as zero |
| **3 — Rule Engine & Human Review** | Automated vs. human review, final priority distribution, urgent human review, human review by category and by customer segment | Unavailable today |
| **4 — AI Response Layer** | Response processing rate, the four statuses, response generation time | Unavailable today |
| **5 — Operations** | First response and resolution (mean vs. median side by side), delivery delay, volume by channel / category / over time | **Fully populated with real data** |

A blunt recommendation for pages 2–4: use an explicit "Data not available —
AI pipeline has not been run" card rather than a chart of zeros. A bar chart
of zeros is indistinguishable from a chart of failures, which is precisely
the misreading this project has worked to avoid.

## 10. Known Limitations

- The dominant one, unchanged since Phase 3: **no API key**, so four of five views have no data to report.
- Views are computed at query time (no materialization). Correct and always-fresh, but on a much larger `tickets` table the percentile scans would want a materialized view and a refresh schedule.
- `vw_ticket_analytics` deliberately excludes `order_items`/`products` to protect grain — product-level analysis needs a separate view at order-item grain, not a modification of this one.
- `exact_category_match_rate_pct` is a single blunt number (§4.3).
- Phase 6 reads the current state only; there is no historical snapshotting, so trends over time can be drawn from `created_at` but metric *drift* (e.g. accuracy falling month over month) can't be reconstructed retroactively.
- `median_*` uses `PERCENTILE_CONT` (interpolated). The Python cross-check matches this deliberately; a discrete median would differ slightly on even-sized populations.
