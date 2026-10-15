# Build Guide: Meridian Commerce Power BI Dashboard (3 pages)

This guide reproduces the dashboard as it exists in the `.pbix`. For visual details see `layout_spec.md`; for field meanings see `data_dictionary.md`.

## 1. Prerequisites

- Power BI Desktop.
- The local PostgreSQL database with the Phase 6 views applied (`sql/09_phase6_analytics_views.sql`).
- A database login that can `SELECT` from the five `vw_*` views. A dedicated read-only role is recommended (see the root `README.md`).

Do not paste database passwords, API keys, `.env` values or secrets into any dashboard artifact. Power BI keeps credentials in Data source settings, not in the queries.

## 2. Import data

Connector: **PostgreSQL database**, server `localhost:5432`, database `meridian_commerce`, **Import** mode.

| Query name in the report | Source view | Role |
|---|---|---|
| `Tickets` | `vw_ticket_analytics` | Fact table, one row per ticket |
| `public vw_classification_metrics` | `vw_classification_metrics` | One-row snapshot, disconnected |
| `public vw_rule_decision_metrics` | `vw_rule_decision_metrics` | One-row snapshot, disconnected |
| `public vw_response_metrics` | `vw_response_metrics` | One-row snapshot, disconnected |
| `public vw_operational_metrics` | `vw_operational_metrics` | One-row snapshot; feeds the Operational KPI cards |

No Power Query transformations are applied; types come from PostgreSQL. See `powerquery/postgresql_views.pq` (Part 1 is the exact M used; Part 2 is a parameterized option).

CSV fallback: run the SELECTs in `sql/powerbi_extracts.sql`, export each to CSV and import those instead.

## 3. Data model

1. On `Tickets`, add the calculated column:
   ```DAX
   Created Date =
   DATE(YEAR(Tickets[created_at]), MONTH(Tickets[created_at]), DAY(Tickets[created_at]))
   ```
2. Create the calculated table:
   ```DAX
   Date =
   CALENDAR(
       DATEVALUE(MIN(Tickets[created_at])),
       DATEVALUE(MAX(Tickets[created_at]))
   )
   ```
3. Model view: relate `Date[Date]` (one) to `Tickets[Created Date]` (many), single direction, active. **This is the only relationship in the model.**
4. Mark `Date` as the date table (Table tools, Mark as date table, column `Date`).
5. Turn off Auto date/time: File, Options and settings, Options, Current File, Data Load, Time intelligence, untick Auto date/time. (Otherwise Power BI adds 10 hidden date tables, and the report does not use any date hierarchy.)
6. Do **not** create relationships between the four summary-view tables, or between them and `Tickets`. Power BI may auto-detect 1:1 relationships on `total_tickets`; delete them.
7. Create a blank table `KPI_Measures` (Enter data, one column, no rows needed), add the measures from `dax/measures.dax` Section A, then hide `Column1`.

Formatting: rates are Percentage with 2 decimals; counts are Whole number with the thousands separator.

## 4. Pages

Build the three pages in `layout_spec.md`: Executive Overview, AI Classification, Operational Performance.

Settings that matter:

- Executive Overview slicers (Date, Channel) are page-local. Do not sync them: pages 2 and 3 are not designed to respond to them.
- Executive Overview: use Edit interactions so the Ticket Decision Distribution chart does **not** filter the three routing-rate cards.
- Operational Performance: use Edit interactions so the two charts do **not** filter the Total Tickets card, and keep the snapshot note in the header.
- Response Status chart: visual filter `response_status` is not blank. Resolution Type chart: leave the blank (it means "no resolution recorded") and say so in the title.
- Card Display units = None, so 1,015.67 does not render as "1.02K" and 1,500 not as "1.5K".
- Turn data labels on for every chart (counts of 1 next to 1,499 are otherwise invisible).

## 5. Guardrails

Use this exact meaning in titles and tooltips:

- `exact_category_match_rate_pct`: accuracy-style backtest against synthetic seed labels, not validated production accuracy. It is not on any current page.
- `response_status`: draft/blocking status only; the project does not send responses.
- Operational timing metrics: synthetic historical support data, not AI improvement.
- Human-review routing: a rule-engine outcome that is dominated by tickets with no AI classification.

## 6. QA checklist (latest reported values: 2026-10-15)

Executive Overview

- Total Tickets 1,500; Classified Tickets 100; Classification Coverage 6.67% after refreshing the PBIX data.
- Tickets Routed to Human Review 99.93%; High/Urgent Tickets Routed to Human Review 3.13%; Tickets Routed Automatically 0.07%.
- Decision chart: Human Review 1,499, Automated 1. Original-priority chart: Low 472, Medium 442, High 392, Urgent 194.
- Each card shows the **title** you expect, not a measure name that says something else. In particular the 99.93% card must be backed by a measure named `Human Review Rate %`, and no measure named "Urgent-Only..." may hold a rate formula.

AI Classification

- Classified Tickets 100; Coverage 6.67%; category bars should total 100 after refreshing the PBIX data; Final Priority values below are from the older imported snapshot and should be refreshed from the live views.
- The limitation text is visible; no accuracy, match-rate or confidence figure appears.

Operational Performance

- Total Tickets 1,500; Tickets With First Response 1,410; Average First Response 1,015.67; Median First Response 753.60.
- Tickets With a Resolution Timestamp 1,139; Average Resolution 50.27; Tickets With Rule Decision 1,500; Responses Generated 3.
- Response Status: HUMAN_REVIEW_DRAFT 2, DRAFT_GENERATED 1 (no blank bar). Resolution Type: Human 1,139, Blank 361.

Reconcile (run in PostgreSQL) before publishing:

```sql
SELECT * FROM vw_classification_metrics;
SELECT * FROM vw_rule_decision_metrics;
SELECT * FROM vw_response_metrics;
SELECT * FROM vw_operational_metrics;
```

and `python -m src.pipeline analytics` (read-only) should report `issues_found: 0`.

## 7. Repo placement

Keep the `.pbix` in this folder (suggested name `Meridian_Commerce_Support_Dashboard.pbix`). It embeds a snapshot of synthetic data and the connection string `localhost:5432` / `meridian_commerce`; it contains no passwords. Review with `git status` before committing.
