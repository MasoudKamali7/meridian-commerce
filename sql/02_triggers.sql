-- ============================================================================
-- Meridian Commerce — Phase 2: Triggers
--
-- PostgreSQL CHECK constraints cannot reference other tables, so the
-- cross-table business rule "a ticket's order must belong to the same
-- customer as the ticket" is enforced with a trigger instead.
-- ============================================================================

BEGIN;

-- ------------------------------------------------------------------
-- Enforce: if tickets.order_id is set, that order must belong to the
-- same customer as tickets.customer_id.
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_ticket_order_customer_match()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.order_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM orders
            WHERE order_id = NEW.order_id
              AND customer_id = NEW.customer_id
        ) THEN
            RAISE EXCEPTION
                'Ticket references order % which does not belong to customer %',
                NEW.order_id, NEW.customer_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ticket_order_customer_match ON tickets;
CREATE TRIGGER trg_ticket_order_customer_match
    BEFORE INSERT OR UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION enforce_ticket_order_customer_match();

-- ------------------------------------------------------------------
-- Convenience: auto-maintain tickets.updated_at on every row update,
-- so application code never has to remember to set it manually.
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tickets_set_updated_at ON tickets;
CREATE TRIGGER trg_tickets_set_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

COMMIT;
