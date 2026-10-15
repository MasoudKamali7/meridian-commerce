# Dashboard Validation Report

Date: 2026-10-13 (historical PBIX validation). Scope: reconcile the Power BI file with the project's SQL, rule engine, seed data and tests. The live database later reached 100 classified tickets on 2026-10-15; this report and embedded PBIX data have not been refreshed to that newer state.

## Result

Every value shown on the dashboard reconciles. No number was wrong. The problems found were labels, naming and documentation, not calculations.

## Method

| # | Check | How |
|---|---|---|
| 1 | SQL views reproduce the dashboard's summary tables | Built a scratch PostgreSQL 16 database from `sql/01` to `sql/09`, loaded `data/*.csv`, replayed the live state (see "Independence"), executed the four `vw_*_metrics` views and compared every field with the tables embedded in the PBIX |
| 2 | PBIX `Tickets` equals `vw_ticket_analytics` | Executed the view, compared all 36 shared columns for all 1,500 rows |
| 3 | Rule decisions reproduce | Ran the project's own `src.rules.engine.safe_evaluate` over the seed CSVs (customers and orders joined) and compared `decision_path`, `final_priority`, `recommended_action` per ticket with the PBIX |
| 4 | Seed-only metrics | Operational metrics computed by the SQL views directly from the seed CSVs |
| 5 | Project's own validation | `sql/04_validation.sql`, `sql/10_phase6_validation.sql`, `python -m src.pipeline analytics`, `pytest tests/` |

## Results

| # | Outcome |
|---|---|
| 1 | **45 of 45** summary-view fields identical (classification 12, rule decision 10, response 12, operational 11) |
| 2 | **36 of 36** columns match. Two representation differences only: PBIX timestamps are rounded to about 3 ms (max gap 2.7 ms, 104 `first_response_at` and 84 `resolved_at` values), and booleans print as True/False instead of t/f |
| 3 | **1,500 of 1,500** tickets match on all three fields. Human Review 1,499, Automated 1; High 47, Medium 1,452, Urgent 1; High/Urgent human review 47 (3.13%). No fallback decisions |
| 4 | 1,410 first responses, average 1,015.67 min, median 753.60 min; 1,139 resolved, average 50.27 h, median 45.09 h. Identical to the dashboard and `sample_current_metrics/` |
| 5 | `04_validation.sql`: all checks return zero rows (441 tickets without an order is informational and matches the seed data). `10_phase6_validation.sql`: no issues. `analytics` CLI: `issues_found: 0`, numbers identical to the dashboard. `pytest`: 226 passed (also with no database reachable) |

Also reproduced from the seed data: original priority (Low 472, Medium 442, High 392, Urgent 194), status counts, channel counts and the 90 tickets without a first response.

## Independence: what each check does and does not prove

Independent of the PBIX (computed from the repository only): the operational metrics, original priority, status, channel, the rule-engine decisions for the 1,400 currently unclassified tickets, the SQL view logic and the validation scripts.

**Not independent.** The production database is not in the repository, so these inputs for the live state came from the PBIX export:

- `classification_confidence` and `sentiment_score` for tickets 1-3 (their categories were cross-checked against `logs/classification.jsonl`: Complaint, Order Status Inquiry, Delivery Delay);
- `decision_at`, `rule_decision_at`, `response_status`, `response_type` and `response_generated_at` for the 3 processed tickets, and `rule_decision_at` for all 1,500 (the decision values themselves come from the rule engine, not the PBIX).

So checks 1 and 2 prove the **SQL view logic and the PBIX import are correct for that state**; they do not prove the production database holds that state. Re-run the four `SELECT * FROM vw_*` queries against production to close that gap.

## Not verified

- How the measures render in Power BI Desktop (no Desktop available; the DAX logic was re-implemented, not executed).
- Visual appearance, text clipping, contrast and tooltips.
- Live OpenRouter calls (no key used) and refresh through a gateway.

## Re-run on your machine

```powershell
# 1. views vs dashboard
psql -U meridian_app -d meridian_commerce -c "SELECT * FROM vw_classification_metrics"
psql -U meridian_app -d meridian_commerce -c "SELECT * FROM vw_rule_decision_metrics"
psql -U meridian_app -d meridian_commerce -c "SELECT * FROM vw_response_metrics"
psql -U meridian_app -d meridian_commerce -c "SELECT * FROM vw_operational_metrics"

# 2. project validators
python -m src.pipeline analytics
pytest tests/ -q
```

Expected: the values in `data_dictionary.md` under "Current known metrics", `issues_found: 0`, and `226 passed`.
