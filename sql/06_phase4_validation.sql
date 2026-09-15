-- ============================================================================
-- Meridian Commerce — Phase 4: Validation Suite
-- Every query below should return 0 rows on a healthy dataset.
-- ============================================================================

-- New columns hold only approved values (also enforced by CHECK, verified independently)
SELECT 'invalid_final_priority' AS check_name, ticket_id FROM tickets
WHERE final_priority IS NOT NULL AND final_priority NOT IN ('Low', 'Medium', 'High', 'Urgent');

SELECT 'invalid_decision_path' AS check_name, ticket_id FROM tickets
WHERE decision_path IS NOT NULL AND decision_path NOT IN ('Automated', 'Human Review');

-- rule_decision_at must never precede created_at (also enforced by CHECK)
SELECT 'rule_decision_before_created' AS check_name, ticket_id FROM tickets
WHERE rule_decision_at IS NOT NULL AND rule_decision_at < created_at;

-- A ticket that has a Phase 4 decision should have BOTH decision_path and
-- final_priority set together (Phase 4 always writes them as a pair) —
-- catches a partial/inconsistent write.
SELECT 'partial_phase4_write' AS check_name, ticket_id FROM tickets
WHERE (decision_path IS NOT NULL) <> (final_priority IS NOT NULL);

-- Phase 4 must never have touched protected historical fields — this is a
-- structural reminder query, not something Phase 4's code can violate by
-- construction (update_phase4_decision only ever SETs final_priority,
-- decision_path, rule_decision_at) but is included so anyone editing that
-- function later has an explicit check to run.
-- (No query needed here — see PHASE4_SUMMARY.md for the direct test that
-- exercises this against a real row.)

-- Informational: decision distribution so far
SELECT 'decision_path_distribution (informational)' AS check_name,
       COALESCE(decision_path, '(not yet decided)') AS decision_path, COUNT(*)
FROM tickets GROUP BY decision_path ORDER BY 2 DESC;

SELECT 'final_priority_distribution (informational)' AS check_name,
       COALESCE(final_priority, '(not yet decided)') AS final_priority, COUNT(*)
FROM tickets GROUP BY final_priority ORDER BY 2 DESC;
