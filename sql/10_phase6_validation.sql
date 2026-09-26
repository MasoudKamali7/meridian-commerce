-- ============================================================================
-- Meridian Commerce — Phase 6: Analytics Validation Suite (READ-ONLY)
--
-- Structural and consistency checks on the analytical views. Every "check"
-- query returns 0 rows on a healthy system; the informational queries at the
-- end print current values. Nothing here mutates anything.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. ALL FIVE VIEWS EXIST (expect exactly 5 rows listed)
-- ----------------------------------------------------------------------------
SELECT 'existing_analytics_views' AS check_name, table_name
FROM information_schema.views
WHERE table_schema = 'public' AND table_name LIKE 'vw_%'
ORDER BY table_name;

-- Expect 0 rows: any of the five expected views that is MISSING
SELECT 'missing_view' AS check_name, expected.name
FROM (VALUES ('vw_ticket_analytics'), ('vw_classification_metrics'),
             ('vw_rule_decision_metrics'), ('vw_response_metrics'),
             ('vw_operational_metrics')) AS expected(name)
WHERE expected.name NOT IN (
    SELECT table_name FROM information_schema.views WHERE table_schema = 'public'
);

-- ----------------------------------------------------------------------------
-- 2. TICKET GRAIN — exactly one row per ticket (expect 0 rows)
-- ----------------------------------------------------------------------------
SELECT 'ticket_grain_duplicates' AS check_name, ticket_id, COUNT(*)
FROM vw_ticket_analytics GROUP BY ticket_id HAVING COUNT(*) > 1;

SELECT 'ticket_grain_row_count_mismatch' AS check_name,
       (SELECT COUNT(*) FROM vw_ticket_analytics) AS view_rows,
       (SELECT COUNT(*) FROM tickets) AS ticket_rows
WHERE (SELECT COUNT(*) FROM vw_ticket_analytics) <> (SELECT COUNT(*) FROM tickets);

-- ----------------------------------------------------------------------------
-- 3. INTERNAL CONSISTENCY (expect 0 rows from each)
-- ----------------------------------------------------------------------------
SELECT 'classification_counts_do_not_partition' AS check_name, *
FROM vw_classification_metrics
WHERE classified_tickets + unclassified_tickets <> total_tickets;

SELECT 'rule_decisions_do_not_partition' AS check_name, *
FROM vw_rule_decision_metrics
WHERE automated_decisions + human_review_decisions <> tickets_with_rule_decision;

SELECT 'response_statuses_do_not_partition' AS check_name, *
FROM vw_response_metrics
WHERE drafts_generated + human_review_drafts + blocked_responses + not_eligible_responses
      <> response_processed;

SELECT 'response_processed_partition_broken' AS check_name, *
FROM vw_response_metrics
WHERE response_processed + response_not_processed <> total_tickets;

SELECT 'urgent_exceeds_human_review' AS check_name, *
FROM vw_rule_decision_metrics
WHERE urgent_human_review > human_review_decisions;

SELECT 'matches_exceed_classified' AS check_name, *
FROM vw_classification_metrics
WHERE exact_category_matches > classified_tickets;

-- ----------------------------------------------------------------------------
-- 4. PERCENTAGE RANGE SANITY (expect 0 rows)
-- ----------------------------------------------------------------------------
SELECT 'classification_pct_out_of_range' AS check_name, *
FROM vw_classification_metrics
WHERE classification_coverage_pct NOT BETWEEN 0 AND 100
   OR low_confidence_rate_pct NOT BETWEEN 0 AND 100
   OR exact_category_match_rate_pct NOT BETWEEN 0 AND 100;

SELECT 'rule_pct_out_of_range' AS check_name, *
FROM vw_rule_decision_metrics
WHERE automated_rate_pct NOT BETWEEN 0 AND 100
   OR human_review_rate_pct NOT BETWEEN 0 AND 100
   OR urgent_human_review_rate_pct NOT BETWEEN 0 AND 100;

SELECT 'response_pct_out_of_range' AS check_name, *
FROM vw_response_metrics
WHERE response_processed_rate_pct NOT BETWEEN 0 AND 100
   OR draft_generation_rate_pct NOT BETWEEN 0 AND 100
   OR blocked_rate_pct NOT BETWEEN 0 AND 100;

-- ----------------------------------------------------------------------------
-- 5. DERIVED FIELD SANITY (expect 0 rows)
--    Durations are measured from created_at, so they can never be negative.
--    delivery_delay_days CAN legitimately be negative (early delivery) and is
--    therefore deliberately NOT checked here.
-- ----------------------------------------------------------------------------
SELECT 'negative_first_response_minutes' AS check_name, ticket_id, first_response_minutes
FROM vw_ticket_analytics WHERE first_response_minutes < 0;

SELECT 'negative_resolution_hours' AS check_name, ticket_id, resolution_hours
FROM vw_ticket_analytics WHERE resolution_hours < 0;

SELECT 'negative_rule_decision_hours' AS check_name, ticket_id, rule_decision_hours
FROM vw_ticket_analytics WHERE rule_decision_hours < 0;

SELECT 'negative_response_generation_hours' AS check_name, ticket_id, response_generation_hours
FROM vw_ticket_analytics WHERE response_generation_hours < 0;

-- Vocabulary integrity: the view must not surface values outside the
-- approved Phase 4/5 vocabularies (expect 0 rows)
SELECT 'invalid_decision_path_in_view' AS check_name, ticket_id, decision_path
FROM vw_ticket_analytics
WHERE decision_path IS NOT NULL AND decision_path NOT IN ('Automated', 'Human Review');

SELECT 'invalid_response_status_in_view' AS check_name, ticket_id, response_status
FROM vw_ticket_analytics
WHERE response_status IS NOT NULL AND response_status NOT IN
      ('NOT_ELIGIBLE', 'DRAFT_GENERATED', 'HUMAN_REVIEW_DRAFT', 'BLOCKED');

-- ----------------------------------------------------------------------------
-- 6. CURRENT VALUES (informational — these are the Power BI source metrics)
-- ----------------------------------------------------------------------------
SELECT * FROM vw_classification_metrics;
SELECT * FROM vw_rule_decision_metrics;
SELECT * FROM vw_response_metrics;
SELECT * FROM vw_operational_metrics;
