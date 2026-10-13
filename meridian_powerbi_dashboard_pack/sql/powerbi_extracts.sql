-- ============================================================================
-- Meridian Commerce Power BI Extracts
--
-- Run after sql/09_phase6_analytics_views.sql has been applied.
-- These queries are SELECT-only and do not expose secrets or mutate data.
-- ============================================================================

-- Fact table: ticket grain, exactly one row per ticket.
SELECT
    ticket_id,
    created_at,
    first_response_at,
    resolved_at,
    channel,
    ground_truth_category,
    ai_predicted_category,
    classification_confidence,
    original_priority,
    final_priority,
    final_priority_score,
    status,
    decision_path,
    recommended_action,
    resolution_type,
    sentiment_score,
    decision_at,
    rule_decision_at,
    response_status,
    response_type,
    response_generated_at,
    customer_segment,
    country,
    customer_is_active,
    order_id,
    order_status,
    order_total_amount,
    payment_method,
    order_date,
    expected_delivery_date,
    actual_delivery_date,
    delivery_delay_days,
    first_response_minutes,
    resolution_hours,
    rule_decision_hours,
    response_generation_hours
FROM vw_ticket_analytics;

-- Aggregate metric tables.
SELECT * FROM vw_classification_metrics;
SELECT * FROM vw_rule_decision_metrics;
SELECT * FROM vw_response_metrics;
SELECT * FROM vw_operational_metrics;

-- Optional date dimension seed from the fact table's date range.
SELECT
    dd::date AS date,
    EXTRACT(YEAR FROM dd)::int AS year,
    EXTRACT(QUARTER FROM dd)::int AS quarter,
    EXTRACT(MONTH FROM dd)::int AS month,
    TO_CHAR(dd, 'Mon') AS month_name,
    EXTRACT(DAY FROM dd)::int AS day,
    EXTRACT(DOW FROM dd)::int AS day_of_week,
    TO_CHAR(dd, 'Dy') AS day_name,
    CASE WHEN EXTRACT(DOW FROM dd) IN (0, 6) THEN TRUE ELSE FALSE END AS is_weekend
FROM generate_series(
    (SELECT MIN(created_at)::date FROM vw_ticket_analytics),
    (SELECT MAX(created_at)::date FROM vw_ticket_analytics),
    interval '1 day'
) AS dd
ORDER BY date;

-- Optional export commands for psql users.
-- Replace the local paths before running.
--
-- \copy (SELECT * FROM vw_ticket_analytics) TO 'powerbi/exports/vw_ticket_analytics.csv' CSV HEADER
-- \copy (SELECT * FROM vw_classification_metrics) TO 'powerbi/exports/vw_classification_metrics.csv' CSV HEADER
-- \copy (SELECT * FROM vw_rule_decision_metrics) TO 'powerbi/exports/vw_rule_decision_metrics.csv' CSV HEADER
-- \copy (SELECT * FROM vw_response_metrics) TO 'powerbi/exports/vw_response_metrics.csv' CSV HEADER
-- \copy (SELECT * FROM vw_operational_metrics) TO 'powerbi/exports/vw_operational_metrics.csv' CSV HEADER
