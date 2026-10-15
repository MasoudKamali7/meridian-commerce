# Power BI Layout Specification (as built)

Canvas: 16:9, 1280 x 720. The dashboard has **three pages**. The original plan had five; pages 3 and 4 (detail) were not built. See [Planned, not built](#planned-not-built) at the end.

Source: Import mode from the Phase 6 views. Only `Tickets` is relationship-connected (via `Date`); the four single-row summary views are disconnected. Slicers on Executive Overview are page-local (not synced), so they do not affect pages 2 and 3.

## Page 1: Executive Overview

Purpose: show the whole system state without overstating AI outcomes.

Slicers: Date (`Date[Date]`, saved range = full data range 2022-02-05 to 2026-06-30) and Channel.

| Visual | Field / measure | Notes |
|---|---|---|
| Card: Classified Tickets | `[Classified Tickets]` | 100 in latest reported DB state; refresh PBIX |
| Card: Classification Coverage % | `[Classification Coverage %]` | 6.67% in latest reported DB state; refresh PBIX |
| Card: Total Tickets | `[Total Tickets]` | 1,500 |
| Card: Tickets Routed to Human Review | `[Human Review Rate %]` | 99.93%, denominator = tickets with a rule decision |
| Card: High/Urgent Tickets Routed to Human Review | `[High/Urgent Human Review Rate %]` | 3.13% of decided tickets; this is the SQL `urgent_human_review_rate_pct` |
| Card: Tickets Routed Automatically | `[Automated Rate %]` | 0.07% |
| Chart: Ticket Decision Distribution | `Tickets[decision_path]` x `[Total Tickets]` | Human Review 1,499 / Automated 1; data labels on |
| Chart: Ticket Priority at Creation (Original Priority) | `Tickets[original_priority]` x `[Total Tickets]` | Original priority, **not** final priority (Urgent 194 here vs 1 in final priority) |
| Text: AI coverage warning and routing note | static text | Says the AI sample is too small to claim accuracy and that human-review routing mostly reflects unclassified tickets |

Interactions: the decision-path chart does not cross-filter the three routing-rate cards (their `CALCULATE` filters override it, so the cards would otherwise ignore the click).

## Page 2: AI Classification

Purpose: show AI coverage and the size of the pilot sample, nothing more.

| Visual | Field / measure | Notes |
|---|---|---|
| Header subtitle | text | "AI Classification Coverage (Pilot Sample Only)" |
| Card: Classified Tickets | `[Classified Tickets]` | 100 in latest reported DB state; refresh PBIX |
| Card: Classification Coverage % | `[Classification Coverage %]` | 6.67% in latest reported DB state; refresh PBIX |
| Chart: AI-Predicted Categories (100-Ticket Pilot Sample) | `Tickets[ai_predicted_category]` x `[Total Tickets]` | Blank category filtered out; counts should sum to 100 after refresh |
| Chart: Final Priority Distribution | `Tickets[final_priority]` x `[Total Tickets]` | Rule-engine output, not an AI prediction: Medium 1,452 / High 47 / Urgent 1 |
| Text: Classification data limitation | static text | Required |

Deliberately **not shown**: exact category match rate (95% on 100 synthetic-label samples), average confidence, any "accuracy" wording.

## Page 3: Operational Performance

Purpose: the AI-independent support-operations metrics. These describe synthetic history and say nothing about AI impact.

Seven cards read the single-row snapshot `public vw_operational_metrics` (they do not respond to slicers or chart selections; the page header says so). One card reads live ticket rows.

| Visual | Source | Value |
|---|---|---|
| Card: Total Tickets | `[Total Tickets]` (live rows) | 1,500 |
| Card: Tickets With First Response | `vw_operational_metrics.tickets_with_first_response` | 1,410 |
| Card: Average First Response (Minutes) | `avg_first_response_minutes` | 1,015.67 |
| Card: Median First Response Time (Minutes) | `median_first_response_minutes` | 753.60 |
| Card: Tickets With a Resolution Timestamp (incl. Reopened) | `resolved_tickets` | 1,139 |
| Card: Average Resolution Time (Hours) | `avg_resolution_hours` | 50.27 |
| Card: Tickets With Rule Decision | `tickets_with_rule_decision` | 1,500 |
| Card: Responses Generated | `responses_generated` | 3 |
| Chart: Response Status (processed tickets only) | `Tickets[response_status]` | Blank excluded: HUMAN_REVIEW_DRAFT 2, DRAFT_GENERATED 1 (1,497 tickets were never processed) |
| Chart: Resolution Type (Blank = no resolution recorded) | `Tickets[resolution_type]` | Human 1,139; Blank 361. The seed data contains no Automated or Hybrid resolutions |

Interactions: the two charts do not cross-filter the Total Tickets card.

Not shown, on purpose: `avg_rule_decision_hours` (6,862 h) and `avg_response_generation_hours` (13,339 h). They are batch-run artefacts, not latencies.

## Guardrails

- `exact_category_match_rate_pct` is an accuracy-style backtest against synthetic seed labels, never validated production accuracy. Show it only next to its sample size.
- `response_status` is draft/blocking status only; the system sends nothing.
- Operational timing metrics are synthetic history, not AI improvement.
- No page claims production accuracy, AI time savings or autonomous customer action.
- Prefer a "not available" note over a chart of zeros when an AI layer has no data.

## Planned, not built

These were in the original five-page plan and are **not** in the report. Build them only once there is data worth showing.

- Decision & Human Review (detail): decision path by final priority, recommended-action counts, ground-truth category by decision path, urgent human-review ticket table.
- Response & Safety (detail): response type distribution, response status by decision path, processed-response table, and the note "The system stores drafts or blocks unsafe responses; it does not send emails or perform business actions."
- Operations extras: volume by created date, median first response and resolution by month, first response by channel, resolution by category, order total vs resolution hours.
- Extra slicers: customer segment, country, ground-truth category, final priority.
