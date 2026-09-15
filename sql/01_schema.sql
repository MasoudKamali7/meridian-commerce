-- ============================================================================
-- Meridian Commerce — AI-Powered Customer Support Automation System
-- Phase 2: Core Schema (tables + column-level & row-level constraints)
--
-- Design note on CHECK vs. ENUM:
-- This project uses VARCHAR + CHECK constraints for all controlled
-- vocabularies (categories, statuses, priorities, channels, etc.) instead
-- of native PostgreSQL ENUM types. See README.md ("CHECK vs. ENUM") for
-- the full rationale.
-- ============================================================================

BEGIN;

DROP TABLE IF EXISTS tickets CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- ============================================================
-- customers
-- ============================================================
CREATE TABLE customers (
    customer_id      SERIAL PRIMARY KEY,
    first_name       VARCHAR(50)   NOT NULL,
    last_name        VARCHAR(50)   NOT NULL,
    email            VARCHAR(100)  NOT NULL UNIQUE,
    phone            VARCHAR(20),
    signup_date      DATE          NOT NULL,
    customer_segment VARCHAR(20)   NOT NULL DEFAULT 'New',
    country          VARCHAR(50)   NOT NULL,
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_customers_segment
        CHECK (customer_segment IN ('New', 'Returning', 'VIP'))
);

COMMENT ON TABLE customers IS 'Registered customers of Meridian Commerce.';

-- ============================================================
-- products
-- ============================================================
CREATE TABLE products (
    product_id     SERIAL         PRIMARY KEY,
    product_name   VARCHAR(150)   NOT NULL,
    category       VARCHAR(50)    NOT NULL,
    sku            VARCHAR(30)    NOT NULL UNIQUE,
    price          NUMERIC(10,2)  NOT NULL,
    stock_quantity INT            NOT NULL DEFAULT 0,
    is_active      BOOLEAN        NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_products_category
        CHECK (category IN ('Electronics Accessories', 'Home & Kitchen',
                             'Sports & Outdoors', 'Beauty & Personal Care',
                             'Office & Stationery', 'Toys & Games')),
    CONSTRAINT chk_products_price_nonneg CHECK (price >= 0),
    CONSTRAINT chk_products_stock_nonneg CHECK (stock_quantity >= 0)
);

COMMENT ON TABLE products IS 'Product catalog for Meridian Commerce.';

-- ============================================================
-- orders
-- ============================================================
CREATE TABLE orders (
    order_id                SERIAL        PRIMARY KEY,
    customer_id             INT           NOT NULL REFERENCES customers(customer_id),
    order_date              TIMESTAMP     NOT NULL,
    order_status            VARCHAR(20)   NOT NULL,
    total_amount            NUMERIC(10,2) NOT NULL,
    payment_method          VARCHAR(20)   NOT NULL,
    expected_delivery_date  DATE          NOT NULL,
    actual_delivery_date    DATE,

    CONSTRAINT chk_orders_status
        CHECK (order_status IN ('Placed', 'Processing', 'Shipped', 'Out for Delivery',
                                 'Delivered', 'Delayed', 'Cancelled', 'Returned', 'Refunded')),
    CONSTRAINT chk_orders_payment_method
        CHECK (payment_method IN ('Credit Card', 'Debit Card', 'PayPal', 'Apple Pay',
                                   'Google Pay', 'Gift Card', 'Bank Transfer')),
    CONSTRAINT chk_orders_total_nonneg CHECK (total_amount >= 0),
    CONSTRAINT chk_orders_delivery_dates
        CHECK (actual_delivery_date IS NULL OR actual_delivery_date >= order_date::date)
);

COMMENT ON TABLE orders IS 'Customer orders placed at Meridian Commerce.';

-- ============================================================
-- order_items
-- ============================================================
CREATE TABLE order_items (
    order_item_id  SERIAL         PRIMARY KEY,
    order_id       INT            NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id     INT            NOT NULL REFERENCES products(product_id),
    quantity       INT            NOT NULL,
    unit_price     NUMERIC(10,2)  NOT NULL,
    line_total     NUMERIC(10,2)  NOT NULL,

    CONSTRAINT chk_order_items_qty_pos CHECK (quantity > 0),
    CONSTRAINT chk_order_items_price_nonneg CHECK (unit_price >= 0),
    CONSTRAINT chk_order_items_line_total
        CHECK (line_total = ROUND(quantity * unit_price, 2))
);

COMMENT ON TABLE order_items IS 'Line items belonging to each order (resolves orders<->products many-to-many).';

-- ============================================================
-- tickets
-- ============================================================
CREATE TABLE tickets (
    ticket_id                  SERIAL        PRIMARY KEY,
    customer_id                INT           NOT NULL REFERENCES customers(customer_id),
    order_id                   INT           REFERENCES orders(order_id),
    channel                    VARCHAR(20)   NOT NULL,
    message_text               TEXT          NOT NULL,
    category                   VARCHAR(30)   NOT NULL,
    ai_predicted_category      VARCHAR(30),
    classification_confidence  NUMERIC(4,3),
    priority                   VARCHAR(10)   NOT NULL,
    status                     VARCHAR(20)   NOT NULL,
    decision_path              VARCHAR(15),
    resolution_type            VARCHAR(15),
    sentiment_score            NUMERIC(3,2),
    created_at                 TIMESTAMP     NOT NULL DEFAULT now(),
    decision_at                TIMESTAMP,
    first_response_at          TIMESTAMP,
    resolved_at                TIMESTAMP,
    updated_at                 TIMESTAMP     NOT NULL DEFAULT now(),

    CONSTRAINT chk_tickets_channel
        CHECK (channel IN ('Email', 'Chat', 'Phone', 'Social Media', 'Contact Form')),
    CONSTRAINT chk_tickets_category
        CHECK (category IN ('Refund Request', 'Missing Item', 'Damaged Product', 'Delivery Delay',
                             'Order Status Inquiry', 'Product Question', 'Payment Problem',
                             'Account Problem', 'Complaint', 'Other')),
    CONSTRAINT chk_tickets_ai_predicted_category
        CHECK (ai_predicted_category IS NULL OR ai_predicted_category IN
               ('Refund Request', 'Missing Item', 'Damaged Product', 'Delivery Delay',
                'Order Status Inquiry', 'Product Question', 'Payment Problem',
                'Account Problem', 'Complaint', 'Other')),
    CONSTRAINT chk_tickets_priority
        CHECK (priority IN ('Low', 'Medium', 'High', 'Urgent')),
    CONSTRAINT chk_tickets_status
        CHECK (status IN ('New', 'Classified', 'Auto-Resolved', 'Escalated', 'In Progress',
                           'Pending Customer', 'Resolved', 'Closed', 'Reopened')),
    CONSTRAINT chk_tickets_decision_path
        CHECK (decision_path IS NULL OR decision_path IN ('Automated', 'Human Review')),
    CONSTRAINT chk_tickets_resolution_type
        CHECK (resolution_type IS NULL OR resolution_type IN ('Automated', 'Human', 'Hybrid')),
    CONSTRAINT chk_tickets_confidence_range
        CHECK (classification_confidence IS NULL OR
               (classification_confidence >= 0 AND classification_confidence <= 1)),
    CONSTRAINT chk_tickets_sentiment_range
        CHECK (sentiment_score IS NULL OR (sentiment_score >= -1 AND sentiment_score <= 1)),
    CONSTRAINT chk_tickets_ts_decision
        CHECK (decision_at IS NULL OR decision_at >= created_at),
    CONSTRAINT chk_tickets_ts_first_response
        CHECK (first_response_at IS NULL OR first_response_at >= created_at),
    CONSTRAINT chk_tickets_ts_resolved
        CHECK (resolved_at IS NULL OR resolved_at >= created_at)
);

COMMENT ON TABLE tickets IS 'Customer support tickets; AI-pipeline fields (ai_predicted_category, classification_confidence, decision_path, decision_at, sentiment_score) are populated starting in Phase 3, not in this seed data.';

COMMIT;
