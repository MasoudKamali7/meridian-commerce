-- ============================================================================
-- Meridian Commerce — Phase 5: Schema Migration
--
-- Smallest appropriate schema extension for the response-decision layer.
-- FOUR new nullable columns on `tickets` — not six, even though the brief's
-- example list had six. Two were deliberately dropped:
--
--   response_customer_facing and response_requires_human_review are NOT
--   added, because both are 1:1 DETERMINISTIC FUNCTIONS of response_status
--   alone (see derive_response_flags() in src/response/models.py):
--     DRAFT_GENERATED    -> customer_facing=True,  requires_human_review=False
--     HUMAN_REVIEW_DRAFT -> customer_facing=False, requires_human_review=True
--     BLOCKED            -> customer_facing=False, requires_human_review=True
--     NOT_ELIGIBLE       -> customer_facing=False, requires_human_review=False
--   Persisting them as separate columns would let them drift out of sync
--   with response_status through an incomplete UPDATE — the exact class of
--   bug Phase 4.1 already fixed once (recommended_action). This mirrors
--   Phase 4's own decision not to add a redundant "human review" boolean
--   alongside decision_path.
--
-- The four columns that ARE added:
--
--   response_status       — NOT_ELIGIBLE / DRAFT_GENERATED / HUMAN_REVIEW_DRAFT / BLOCKED
--   response_type         — classification of response PURPOSE (see mapping
--                            in src/response/models.py) — nullable, because
--                            it's derived from ai_predicted_category, which
--                            can be NULL even when a Phase 4 decision exists
--                            (a ticket routed to Human Review specifically
--                            BECAUSE classification is missing still has no
--                            category to derive a type from).
--   response_draft        — the actual generated text (customer-facing OR
--                            internal-only, per response_status). This is
--                            the core work product of Phase 5, unlike the
--                            two dropped boolean flags, so it earns a column.
--   response_generated_at — when Phase 5 produced this decision. Distinct
--                            from decision_at (Phase 3 classification time)
--                            and rule_decision_at (Phase 4 decision time) —
--                            same reasoning as Phase 4's own choice to add a
--                            new timestamp rather than overload an old one.
-- ============================================================================

BEGIN;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS response_status VARCHAR(20);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS response_type VARCHAR(20);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS response_draft TEXT;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS response_generated_at TIMESTAMP;

ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_response_status
    CHECK (response_status IS NULL OR response_status IN
           ('NOT_ELIGIBLE', 'DRAFT_GENERATED', 'HUMAN_REVIEW_DRAFT', 'BLOCKED'));

ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_response_type
    CHECK (response_type IS NULL OR response_type IN
           ('ORDER_STATUS', 'PRODUCT_QUESTION', 'PAYMENT_SUPPORT', 'ACCOUNT_SUPPORT',
            'REFUND_SUPPORT', 'ORDER_ISSUE', 'COMPLAINT', 'GENERAL_SUPPORT'));

ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_response_generated_ts
    CHECK (response_generated_at IS NULL OR response_generated_at >= created_at);

-- A generated draft must only exist for statuses that actually produce one;
-- BLOCKED and NOT_ELIGIBLE must never carry a draft, even internally — a
-- blocked draft is exactly the text that failed the safety scan.
ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_response_draft_status_consistency
    CHECK (
        (response_status = 'DRAFT_GENERATED' AND response_draft IS NOT NULL)
        OR (response_status = 'HUMAN_REVIEW_DRAFT')  -- draft optional here (best-effort)
        OR (response_status IN ('BLOCKED', 'NOT_ELIGIBLE') AND response_draft IS NULL)
        OR (response_status IS NULL AND response_draft IS NULL)
    );

COMMENT ON COLUMN tickets.response_status IS
    'Phase 5: NOT_ELIGIBLE / DRAFT_GENERATED / HUMAN_REVIEW_DRAFT / BLOCKED. customer_facing and requires_human_review are derived from this, not stored separately — see src/response/models.py:derive_response_flags().';
COMMENT ON COLUMN tickets.response_type IS
    'Phase 5: classification of response PURPOSE only — never implies the underlying business action (e.g. REFUND_SUPPORT) was actually performed. Nullable: unknown when ai_predicted_category is NULL.';
COMMENT ON COLUMN tickets.response_draft IS
    'Phase 5: generated response text. Customer-facing only when response_status = DRAFT_GENERATED; internal-only (agent reference) when HUMAN_REVIEW_DRAFT; always NULL for BLOCKED/NOT_ELIGIBLE.';
COMMENT ON COLUMN tickets.response_generated_at IS
    'Phase 5: when the response-decision layer processed this ticket. Distinct from decision_at (Phase 3) and rule_decision_at (Phase 4).';

CREATE INDEX IF NOT EXISTS idx_tickets_response_status ON tickets(response_status);
CREATE INDEX IF NOT EXISTS idx_tickets_response_type ON tickets(response_type);

COMMIT;
