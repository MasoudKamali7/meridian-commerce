-- ============================================================================
-- Meridian Commerce — Phase 6: Analytical Views (READ-ONLY)
--
-- Every object here is a VIEW. Phase 6 performs NO mutation of operational
-- data: no INSERT, UPDATE, DELETE, or ALTER of tickets/customers/orders/
-- order_items/products. Views are derived at query time, so the analytics
-- layer can never drift from — or damage — the operational truth.
--
-- TYPE-SAFETY NOTES (PostgreSQL specifics this file deliberately handles):
--   * ROUND(value, scale) exists for numeric, NOT for double precision.
--     Every value passed to a 2-argument ROUND() below is cast ::numeric.
--   * EXTRACT(EPOCH FROM interval) returns numeric on PG14+, but double
--     precision on older versions. Explicit ::numeric casts make this file
--     version-independent rather than "works on my server".
--   * PERCENTILE_CONT() always returns double precision — cast before ROUND.
--   * Every percentage uses NULLIF(denominator, 0), so an empty population
--     yields NULL ("not measurable yet"), never a divide-by-zero error and
--     never a misleading 0.0.
--
-- DENOMINATOR POLICY (important for honest reading — see also
-- PHASE6_SUMMARY.md):
--   Rates are computed over the population the metric is actually about,
--   not blindly over all tickets:
--     - classification_coverage_pct   : denominator = ALL tickets (coverage
--                                        is genuinely "what share of the
--                                        backlog has been classified")
--     - low_confidence_rate_pct       : denominator = tickets WITH a
--                                        confidence value
--     - exact_category_match_rate_pct : denominator = tickets WITH both a
--                                        ground-truth and a predicted category
--     - automated/human_review rates  : denominator = tickets WITH a Phase 4
--                                        decision
--     - draft/blocked/not-eligible    : denominator = tickets Phase 5 has
--                                        processed
--   When that population is empty the metric is NULL, which the Python
--   layer and the report both render as "NOT AVAILABLE" rather than 0%.
--   This matters right now: the AI fields are entirely NULL in this
--   environment (no ANTHROPIC_API_KEY), and 0% would wrongly read as
--   "the model classified nothing correctly" instead of "nothing ran".
-- ============================================================================

-- ============================================================
-- 1. vw_ticket_analytics — ticket grain (exactly one row per ticket)
--
-- GRAIN SAFETY: tickets -> customers is many-to-one (NOT NULL FK), and
-- tickets -> orders is many-to-one on a nullable FK, so both joins are
-- row-preserving. order_items/products are deliberately NOT joined here —
-- a ticket's order can have many line items, and joining them would
-- multiply ticket rows, silently inflating every downstream count.
-- ============================================================
CREATE OR REPLACE VIEW vw_ticket_analytics AS
SELECT
    -- Ticket
    t.ticket_id,
    t.created_at,
    t.first_response_at,
    t.resolved_at,
    t.channel,
    t.category                    AS ground_truth_category,
    t.ai_predicted_category,
    t.classification_confidence,
    t.priority                    AS original_priority,
    t.final_priority,
    t.status,
    t.decision_path,
    t.resolution_type,
    t.sentiment_score,
    t.decision_at,
    t.rule_decision_at,
    t.response_status,
    t.response_type,
    t.response_generated_at,

    -- Customer
    c.customer_segment,
    c.country,
    c.is_active                   AS customer_is_active,

    -- Order (NULL for tickets with no linked order — by design, see Phase 1)
    t.order_id,
    o.order_status,
    o.total_amount                AS order_total_amount,
    o.payment_method,
    o.order_date,
    o.expected_delivery_date,
    o.actual_delivery_date,

    -- Derived analytical fields
    (o.actual_delivery_date - o.expected_delivery_date)              AS delivery_delay_days,
    ROUND((EXTRACT(EPOCH FROM (t.first_response_at - t.created_at)) / 60.0)::numeric, 2)
                                                                      AS first_response_minutes,
    ROUND((EXTRACT(EPOCH FROM (t.resolved_at - t.created_at)) / 3600.0)::numeric, 2)
                                                                      AS resolution_hours,
    ROUND((EXTRACT(EPOCH FROM (t.rule_decision_at - t.created_at)) / 3600.0)::numeric, 2)
                                                                      AS rule_decision_hours,
    ROUND((EXTRACT(EPOCH FROM (t.response_generated_at - t.created_at)) / 3600.0)::numeric, 2)
                                                                      AS response_generation_hours,

    -- Ordinal priority score, matching src/config.py PRIORITY_ORDER exactly
    -- (Low=0, Medium=1, High=2, Urgent=3) rather than inventing a second scale.
    CASE t.final_priority
        WHEN 'Low' THEN 0 WHEN 'Medium' THEN 1 WHEN 'High' THEN 2 WHEN 'Urgent' THEN 3
    END                                                               AS final_priority_score,

    -- Phase 4.1's recommended_action, reconstructed from the two persisted
    -- columns it is a pure function of (see rules/engine.py:
    -- derive_recommended_action). Not stored, exactly reproducible.
    CASE
        WHEN t.decision_path IS NULL THEN NULL
        WHEN t.decision_path = 'Automated' THEN 'AUTO_RESOLVE'
        WHEN t.final_priority IN ('High', 'Urgent') THEN 'HUMAN_REVIEW_URGENT'
        ELSE 'HUMAN_REVIEW_STANDARD'
    END                                                               AS recommended_action
FROM tickets t
JOIN customers c ON t.customer_id = c.customer_id
LEFT JOIN orders o ON t.order_id = o.order_id;

COMMENT ON VIEW vw_ticket_analytics IS
    'Phase 6: ticket-grain analytical view (one row per ticket). Read-only. Joins customers (N:1) and orders (N:1, nullable); order_items is deliberately excluded to preserve grain.';


-- ============================================================
-- 2. vw_classification_metrics — Phase 3 classification performance
--
-- TERMINOLOGY (critical, do not conflate):
--   tickets.category              = GROUND TRUTH, assigned historically by
--                                    humans in the Phase 2 seed data.
--   tickets.ai_predicted_category = MODEL PREDICTION, written by Phase 3.
-- exact_category_match_rate_pct compares the two and therefore becomes an
-- accuracy-style metric ONCE REAL PREDICTIONS EXIST. Until then it is NULL.
-- Even when populated it is a backtest against synthetic seed labels — it is
-- NOT validated production accuracy, and must never be described as such.
-- ============================================================
CREATE OR REPLACE VIEW vw_classification_metrics AS
SELECT
    COUNT(*)                                                        AS total_tickets,
    COUNT(ai_predicted_category)                                    AS classified_tickets,
    COUNT(*) - COUNT(ai_predicted_category)                         AS unclassified_tickets,
    ROUND((COUNT(ai_predicted_category) * 100.0
           / NULLIF(COUNT(*), 0))::numeric, 2)                      AS classification_coverage_pct,

    COUNT(classification_confidence)                                AS confidence_available,
    COUNT(*) FILTER (WHERE classification_confidence < 0.75)        AS low_confidence_tickets,
    ROUND((COUNT(*) FILTER (WHERE classification_confidence < 0.75) * 100.0
           / NULLIF(COUNT(classification_confidence), 0))::numeric, 2)
                                                                    AS low_confidence_rate_pct,

    ROUND(AVG(classification_confidence)::numeric, 4)               AS average_confidence,
    ROUND(MIN(classification_confidence)::numeric, 4)               AS minimum_confidence,
    ROUND(MAX(classification_confidence)::numeric, 4)               AS maximum_confidence,

    COUNT(*) FILTER (WHERE ai_predicted_category IS NOT NULL
                       AND ai_predicted_category = category)        AS exact_category_matches,
    ROUND((COUNT(*) FILTER (WHERE ai_predicted_category IS NOT NULL
                              AND ai_predicted_category = category) * 100.0
           / NULLIF(COUNT(ai_predicted_category), 0))::numeric, 2)  AS exact_category_match_rate_pct
FROM tickets;

COMMENT ON VIEW vw_classification_metrics IS
    'Phase 6: Phase 3 classification metrics. category=ground truth, ai_predicted_category=model prediction. exact_category_match_rate_pct is an accuracy-STYLE backtest metric against synthetic seed labels, NULL until real predictions exist, and never "validated production accuracy".';


-- ============================================================
-- 3. vw_rule_decision_metrics — Phase 4 decisions
--
-- Phase 4 remains authoritative: nothing here re-derives or second-guesses a
-- rule decision; this view only counts what Phase 4 already wrote. The
-- urgent-human-review definition is Phase 4.1's, reused rather than restated:
-- recommended_action = HUMAN_REVIEW_URGENT, i.e. Human Review AND
-- final_priority in (High, Urgent).
--
-- Rate denominators are the DECIDED population (tickets_with_rule_decision),
-- not all tickets — see the denominator policy at the top of this file.
-- ============================================================
CREATE OR REPLACE VIEW vw_rule_decision_metrics AS
SELECT
    COUNT(*)                                                        AS total_tickets,
    COUNT(decision_path)                                            AS tickets_with_rule_decision,
    COUNT(*) FILTER (WHERE decision_path = 'Automated')             AS automated_decisions,
    COUNT(*) FILTER (WHERE decision_path = 'Human Review')          AS human_review_decisions,

    ROUND((COUNT(*) FILTER (WHERE decision_path = 'Automated') * 100.0
           / NULLIF(COUNT(decision_path), 0))::numeric, 2)          AS automated_rate_pct,
    ROUND((COUNT(*) FILTER (WHERE decision_path = 'Human Review') * 100.0
           / NULLIF(COUNT(decision_path), 0))::numeric, 2)          AS human_review_rate_pct,

    COUNT(*) FILTER (WHERE decision_path = 'Human Review'
                       AND final_priority IN ('High', 'Urgent'))    AS urgent_human_review,
    ROUND((COUNT(*) FILTER (WHERE decision_path = 'Human Review'
                              AND final_priority IN ('High', 'Urgent')) * 100.0
           / NULLIF(COUNT(decision_path), 0))::numeric, 2)          AS urgent_human_review_rate_pct,

    COUNT(final_priority)                                           AS final_priority_set,
    ROUND(AVG(CASE final_priority
                  WHEN 'Low' THEN 0 WHEN 'Medium' THEN 1
                  WHEN 'High' THEN 2 WHEN 'Urgent' THEN 3 END)::numeric, 3)
                                                                    AS average_priority_score
FROM tickets;

COMMENT ON VIEW vw_rule_decision_metrics IS
    'Phase 6: Phase 4 decision metrics. Counts only — Phase 4 remains authoritative for the decisions themselves. Rates are over tickets_with_rule_decision; average_priority_score uses the config.py PRIORITY_ORDER scale (Low=0..Urgent=3).';


-- ============================================================
-- 4. vw_response_metrics — Phase 5 response layer
--
-- Statuses are exactly Phase 5's four; no additional operational states are
-- invented here. response_not_processed counts tickets Phase 5 has not
-- reached at all (response_status IS NULL) — distinct from NOT_ELIGIBLE,
-- which is an actual Phase 5 ruling that Phase 4 hadn't decided the ticket.
-- ============================================================
CREATE OR REPLACE VIEW vw_response_metrics AS
SELECT
    COUNT(*)                                                        AS total_tickets,
    COUNT(response_status)                                          AS response_processed,
    COUNT(*) - COUNT(response_status)                               AS response_not_processed,

    COUNT(*) FILTER (WHERE response_status = 'DRAFT_GENERATED')     AS drafts_generated,
    COUNT(*) FILTER (WHERE response_status = 'HUMAN_REVIEW_DRAFT')  AS human_review_drafts,
    COUNT(*) FILTER (WHERE response_status = 'BLOCKED')             AS blocked_responses,
    COUNT(*) FILTER (WHERE response_status = 'NOT_ELIGIBLE')        AS not_eligible_responses,

    ROUND((COUNT(response_status) * 100.0
           / NULLIF(COUNT(*), 0))::numeric, 2)                      AS response_processed_rate_pct,
    ROUND((COUNT(*) FILTER (WHERE response_status = 'DRAFT_GENERATED') * 100.0
           / NULLIF(COUNT(response_status), 0))::numeric, 2)        AS draft_generation_rate_pct,
    ROUND((COUNT(*) FILTER (WHERE response_status = 'HUMAN_REVIEW_DRAFT') * 100.0
           / NULLIF(COUNT(response_status), 0))::numeric, 2)        AS human_review_response_rate_pct,
    ROUND((COUNT(*) FILTER (WHERE response_status = 'BLOCKED') * 100.0
           / NULLIF(COUNT(response_status), 0))::numeric, 2)        AS blocked_rate_pct,
    ROUND((COUNT(*) FILTER (WHERE response_status = 'NOT_ELIGIBLE') * 100.0
           / NULLIF(COUNT(response_status), 0))::numeric, 2)        AS not_eligible_rate_pct
FROM tickets;

COMMENT ON VIEW vw_response_metrics IS
    'Phase 6: Phase 5 response-layer metrics over the four approved statuses. response_not_processed (never reached) is distinct from NOT_ELIGIBLE (an actual Phase 5 ruling).';


-- ============================================================
-- 5. vw_operational_metrics — support operations KPIs
--
-- These are the only metrics in Phase 6 currently backed by substantial real
-- data, because first_response_at/resolved_at were populated by the Phase 2
-- synthetic generator and do not depend on any AI stage.
-- PERCENTILE_CONT returns double precision, hence the ::numeric casts.
-- ============================================================
CREATE OR REPLACE VIEW vw_operational_metrics AS
SELECT
    COUNT(*)                                                        AS total_tickets,

    COUNT(first_response_at)                                        AS tickets_with_first_response,
    ROUND(AVG(EXTRACT(EPOCH FROM (first_response_at - created_at)) / 60.0)::numeric, 2)
                                                                    AS avg_first_response_minutes,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (first_response_at - created_at)) / 60.0))::numeric, 2)
                                                                    AS median_first_response_minutes,

    COUNT(resolved_at)                                              AS resolved_tickets,
    ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0)::numeric, 2)
                                                                    AS avg_resolution_hours,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0))::numeric, 2)
                                                                    AS median_resolution_hours,

    COUNT(rule_decision_at)                                         AS tickets_with_rule_decision,
    ROUND(AVG(EXTRACT(EPOCH FROM (rule_decision_at - created_at)) / 3600.0)::numeric, 2)
                                                                    AS avg_rule_decision_hours,

    COUNT(response_generated_at)                                    AS responses_generated,
    ROUND(AVG(EXTRACT(EPOCH FROM (response_generated_at - created_at)) / 3600.0)::numeric, 2)
                                                                    AS avg_response_generation_hours
FROM tickets;

COMMENT ON VIEW vw_operational_metrics IS
    'Phase 6: operational KPIs (first response, resolution, decision latency). The only Phase 6 view currently backed by substantial real data, since these fields are AI-independent.';
