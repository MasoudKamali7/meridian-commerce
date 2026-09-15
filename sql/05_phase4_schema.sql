-- ============================================================================
-- Meridian Commerce — Phase 4: Schema Migration
--
-- Smallest appropriate schema change for the deterministic business-rule
-- engine. Two new nullable columns on `tickets`:
--
--   final_priority     — Phase 4's deterministically computed operational
--                         priority. NEVER copied from tickets.priority
--                         (historical ground truth) or from any LLM-guessed
--                         priority (Phase 3 treats that as diagnostic-only,
--                         logged, never persisted).
--
--   rule_decision_at   — when the business-rule engine produced this
--                         ticket's decision. Kept DISTINCT from
--                         `decision_at`, which Phase 3 already uses for the
--                         classification timestamp (see PHASE4_SUMMARY.md
--                         "What We Found" for this naming note — Phase 1's
--                         original data dictionary described `decision_at`
--                         as the automate/escalate timestamp, but Phase 3's
--                         actual code repurposed it for classification time;
--                         rather than overload that column further, Phase 4
--                         gets its own).
--
-- `decision_path` (Automated / Human Review) ALREADY EXISTS on `tickets`
-- from Phase 1/2 and was left NULL by Phase 3 by design — it is exactly
-- the field Phase 4 is meant to populate. No new column needed for it, and
-- none needed for a separate "human review" boolean: decision_path already
-- IS that flag, just as a 2-value enum instead of a bool.
--
-- Rich audit detail (which rules fired, why, recommended action) is
-- deliberately NOT added as new columns — seePHASE4_SUMMARY.md for why —
-- it's captured in the structured log instead, mirroring Phase 3's
-- precedent of logging latency/tokens rather than adding a column per
-- diagnostic signal.
-- ============================================================================

BEGIN;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS final_priority VARCHAR(10);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS rule_decision_at TIMESTAMP;

ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_final_priority
    CHECK (final_priority IS NULL OR final_priority IN ('Low', 'Medium', 'High', 'Urgent'));

ALTER TABLE tickets
    ADD CONSTRAINT chk_tickets_rule_decision_ts
    CHECK (rule_decision_at IS NULL OR rule_decision_at >= created_at);

COMMENT ON COLUMN tickets.final_priority IS
    'Phase 4: deterministically computed operational priority. Never copied from tickets.priority (historical) or any LLM-guessed priority.';
COMMENT ON COLUMN tickets.rule_decision_at IS
    'Phase 4: when the business-rule engine produced this ticket''s decision (distinct from decision_at, which marks Phase 3 classification time).';

CREATE INDEX IF NOT EXISTS idx_tickets_decision_path ON tickets(decision_path);
CREATE INDEX IF NOT EXISTS idx_tickets_final_priority ON tickets(final_priority);

COMMIT;
