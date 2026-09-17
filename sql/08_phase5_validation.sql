-- ============================================================================
-- Meridian Commerce — Phase 5: Validation Suite
-- Every query below should return 0 rows on a healthy dataset.
-- ============================================================================

SELECT 'invalid_response_status' AS check_name, ticket_id FROM tickets
WHERE response_status IS NOT NULL AND response_status NOT IN
      ('NOT_ELIGIBLE', 'DRAFT_GENERATED', 'HUMAN_REVIEW_DRAFT', 'BLOCKED');

SELECT 'invalid_response_type' AS check_name, ticket_id FROM tickets
WHERE response_type IS NOT NULL AND response_type NOT IN
      ('ORDER_STATUS', 'PRODUCT_QUESTION', 'PAYMENT_SUPPORT', 'ACCOUNT_SUPPORT',
       'REFUND_SUPPORT', 'ORDER_ISSUE', 'COMPLAINT', 'GENERAL_SUPPORT');

SELECT 'response_generated_before_created' AS check_name, ticket_id FROM tickets
WHERE response_generated_at IS NOT NULL AND response_generated_at < created_at;

-- DRAFT_GENERATED tickets must be customer-facing candidates with an actual draft
SELECT 'draft_generated_missing_text' AS check_name, ticket_id FROM tickets
WHERE response_status = 'DRAFT_GENERATED' AND response_draft IS NULL;

-- BLOCKED / NOT_ELIGIBLE must never carry a draft (would defeat the safety block)
SELECT 'blocked_or_not_eligible_has_draft' AS check_name, ticket_id, response_status FROM tickets
WHERE response_status IN ('BLOCKED', 'NOT_ELIGIBLE') AND response_draft IS NOT NULL;

-- A ticket cannot have a Phase 5 response decision without a Phase 4 decision first
SELECT 'response_without_phase4_decision' AS check_name, ticket_id FROM tickets
WHERE response_status IS NOT NULL AND decision_path IS NULL;

-- HUMAN_REVIEW_DRAFT should only ever occur when Phase 4 said Human Review
-- (Phase 5 must respect Phase 4, never invent its own escalation)
SELECT 'human_review_draft_without_phase4_human_review' AS check_name, ticket_id FROM tickets
WHERE response_status = 'HUMAN_REVIEW_DRAFT' AND decision_path <> 'Human Review';

-- DRAFT_GENERATED should only ever occur when Phase 4 said Automated
SELECT 'draft_generated_without_phase4_automated' AS check_name, ticket_id FROM tickets
WHERE response_status = 'DRAFT_GENERATED' AND decision_path <> 'Automated';

-- Informational: response status / type distribution so far
SELECT 'response_status_distribution (informational)' AS check_name,
       COALESCE(response_status, '(not yet processed)') AS response_status, COUNT(*)
FROM tickets GROUP BY response_status ORDER BY 2 DESC;

SELECT 'response_type_distribution (informational)' AS check_name,
       COALESCE(response_type, '(unknown/unclassified)') AS response_type, COUNT(*)
FROM tickets GROUP BY response_type ORDER BY 2 DESC;
