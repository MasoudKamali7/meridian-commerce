-- ============================================================================
-- Meridian Commerce — Phase 2: Indexes
--
-- Created AFTER the bulk data load (see README) so the initial COPY isn't
-- slowed down by index maintenance. PostgreSQL does not automatically index
-- foreign-key columns (only the referenced primary key is auto-indexed), so
-- every FK column gets an explicit index below.
-- ============================================================================

BEGIN;

-- Foreign-key indexes
CREATE INDEX IF NOT EXISTS idx_orders_customer_id      ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id    ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id  ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_tickets_customer_id     ON tickets(customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_order_id        ON tickets(order_id);

-- Reporting / query-pattern indexes (support the KPI queries from Phase 1)
CREATE INDEX IF NOT EXISTS idx_orders_order_date        ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status            ON orders(order_status);
CREATE INDEX IF NOT EXISTS idx_products_category        ON products(category);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at       ON tickets(created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_category_status  ON tickets(category, status);

COMMIT;
