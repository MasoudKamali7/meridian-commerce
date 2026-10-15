# Data Dictionary

## Model grain

`Tickets` is imported from `vw_ticket_analytics` and has exactly one row per support ticket (1,500 rows, 1,500 distinct `ticket_id`).

Do not join order line items into this fact table. Orders can have many line items, which would multiply ticket rows and inflate counts.

## Tables in the Power BI model

| Power BI table | Source | Type |
|---|---|---|
| `Tickets` | `vw_ticket_analytics` + calculated column `Created Date` | Fact |
| `Date` | DAX calculated table (`CALENDAR` over `created_at`), marked as date table | Dimension; related to `Tickets[Created Date]` |
| `public vw_classification_metrics` | `vw_classification_metrics` | One-row snapshot, disconnected |
| `public vw_rule_decision_metrics` | `vw_rule_decision_metrics` | One-row snapshot, disconnected |
| `public vw_response_metrics` | `vw_response_metrics` | One-row snapshot, disconnected |
| `public vw_operational_metrics` | `vw_operational_metrics` | One-row snapshot, disconnected; feeds the Operational KPI cards |
| `KPI_Measures` | helper table | Hosts the measures |

## SQL name to Power BI label

| SQL column | Power BI measure | Label on the report |
|---|---|---|
| `classification_coverage_pct` | `Classification Coverage %` | Classification Coverage % |
| `human_review_rate_pct` | `Human Review Rate %` | Tickets Routed to Human Review |
| `automated_rate_pct` | `Automated Rate %` | Tickets Routed Automatically |
| `urgent_human_review_rate_pct` | `High/Urgent Human Review Rate %` | High/Urgent Tickets Routed to Human Review |
| `resolved_tickets` | (view column; measure `Tickets With Resolution Timestamp` in the optional set) | Tickets With a Resolution Timestamp (incl. Reopened) |

"Urgent" in the SQL name `urgent_human_review*` means `final_priority` is **High or Urgent**. A measure that counts Urgent only exists (`Urgent-Only Human Review Count`, currently 1) and is a different number.

## Tickets: important fields

| Field | Meaning | Used on |
|---|---|---|
| `ticket_id` | Unique ticket key | Counts |
| `created_at`, `Created Date` | Creation timestamp; date-only copy used for the `Date` relationship | Date slicer |
| `channel` | Support channel (Email 581, Chat 531, Phone 234, Contact Form 85, Social Media 69) | Slicer |
| `ground_truth_category` | Historical seed category (synthetic label) | Not on any page |
| `ai_predicted_category` | Model prediction; NULL for 1,400 tickets in the latest reported state | Coverage, AI page |
| `classification_confidence` | Model self-reported confidence 0-1; 100 values in the latest reported state | Not on any page |
| `original_priority` | Priority in the seed data | Executive Overview chart |
| `final_priority` | Priority computed by the Phase 4 rule engine | AI page chart, High/Urgent rate |
| `final_priority_score` | Low=0, Medium=1, High=2, Urgent=3 | Not on any page |
| `decision_path` | `Automated` or `Human Review` | Executive Overview |
| `recommended_action` | Reconstructed from `decision_path` + `final_priority` | Not on any page |
| `response_status` | Phase 5 status; NULL for 1,497 tickets (never processed) | Operational chart |
| `resolution_type` | `Human` for all 1,139 resolved tickets; NULL for 361 | Operational chart |
| `first_response_minutes`, `resolution_hours` | Creation to first response / to `resolved_at` | Operational |
| `rule_decision_hours`, `response_generation_hours` | Creation to rule decision / response generation | **Do not use** (see caveats) |

## Summary-view tables

Single-row aggregates. Use them only for source-of-truth KPI cards or validation; use measures from `Tickets` when slicer-aware behaviour is needed. Never SUM or AVERAGE them across rows (there is one row each) and never relate them to `Tickets`.

Rate denominators (from `sql/09_phase6_analytics_views.sql`):

- `classification_coverage_pct`, `response_processed_rate_pct`: all tickets.
- `automated_rate_pct`, `human_review_rate_pct`, `urgent_human_review_rate_pct`: tickets with a rule decision.
- draft, human-review-draft, blocked and not-eligible rates: tickets processed by Phase 5.
- `exact_category_match_rate_pct`: tickets with a prediction. Accuracy-style backtest against synthetic seed labels; not production accuracy.

## Caveats you must keep when presenting

1. **AI sample size and labels.** 100 classified tickets (latest reported state). The exact-category match is 95% against synthetic seed labels, not validated production accuracy.
2. **Human-review rate is mostly a missing-classification effect.** Rule `missing_classification` forces Human Review for any ticket without an AI category; it fired on 1,400 unclassified tickets. The only Automated ticket is among the classified tickets.
3. **High priority is mostly the VIP high-value-order rule.** 45 of the 47 High/Urgent human-review tickets are unclassified tickets raised to High by the rule "VIP customer with order value of 450 or more". The other 2 are AI-classified tickets.
4. **`resolved_tickets` counts `resolved_at`.** It includes 76 tickets whose status is now `Reopened` and misses one `Resolved` ticket with no timestamp. Status `Resolved` + `Closed` is 1,064.
5. **Original vs final priority differ a lot.** Original: Urgent 194, High 392. Final: Urgent 1, High 47. Label every priority chart with which one it shows.
6. **Batch-run durations.** `avg_rule_decision_hours` is 6,862 h and `avg_response_generation_hours` is 13,339 h because decisions and responses were written in Sept-Oct 2026 for tickets created from 2022. They are not latencies.
7. **Timestamps in the PBIX are rounded to about 3 ms** (Power BI datetime precision). Durations are unaffected at 2 decimals.
8. **Synthetic data.** Nothing here is real customer data.

## Latest reported metrics (2026-10-15; analytics validation: 0 issues)

| Metric | Current value |
|---|---:|
| Total tickets | 1,500 |
| Classified tickets | 100 |
| Classification coverage | 6.67% |
| Average confidence | 0.9018 |
| Low confidence rate | 1.00% |
| Exact category match rate | 95.00% on 100 synthetic-label samples (not shown on the dashboard; not production accuracy) |
| Tickets with rule decision | 1,500 |
| Automated rate | 0.07% (1) |
| Human review rate | 99.93% (1,499) |
| High/Urgent human review rate | 3.13% (47) |
| Average priority score | 1.033 |
| Response processed | 3 |
| Response processed rate | 0.20% |
| Draft generation rate | 33.33% |
| Human review response rate | 66.67% |
| Blocked rate | 0.00% |
| Tickets with first response | 1,410 |
| Average first response minutes | 1,015.67 |
| Median first response minutes | 753.60 |
| Tickets with a resolution timestamp | 1,139 |
| Average resolution hours | 50.27 |
| Median resolution hours | 45.09 |

The `.pbix` remains an older imported snapshot (2026-10-13); refresh its queries in Power BI Desktop before presenting it as current.
| Validation issues found | 0 |
