-- ============================================================================
-- Meridian Commerce — Phase 2: Data Validation Suite
--
-- Every query below is written so that a healthy dataset returns 0 rows
-- (or an explicitly-labelled count of 0) for every "should be empty" check.
-- Most of these conditions are already impossible thanks to the schema's
-- constraints and triggers — this suite exists as an independent QA layer
-- that documents the data-quality bar and can be re-run after any reload,
-- bulk import, or future ETL step, without relying on trusting that the
-- constraints were never bypassed.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. ROW COUNTS
-- ----------------------------------------------------------------------------
SELECT 'customers'   AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL
SELECT 'products',            COUNT(*) FROM products
UNION ALL
SELECT 'orders',               COUNT(*) FROM orders
UNION ALL
SELECT 'order_items',          COUNT(*) FROM order_items
UNION ALL
SELECT 'tickets',               COUNT(*) FROM tickets;

-- ----------------------------------------------------------------------------
-- 2. PRIMARY KEY UNIQUENESS  (expect 0 rows from each)
-- ----------------------------------------------------------------------------
SELECT 'customers_pk_dupes' AS check_name, customer_id, COUNT(*)
FROM customers GROUP BY customer_id HAVING COUNT(*) > 1;

SELECT 'products_pk_dupes' AS check_name, product_id, COUNT(*)
FROM products GROUP BY product_id HAVING COUNT(*) > 1;

SELECT 'orders_pk_dupes' AS check_name, order_id, COUNT(*)
FROM orders GROUP BY order_id HAVING COUNT(*) > 1;

SELECT 'order_items_pk_dupes' AS check_name, order_item_id, COUNT(*)
FROM order_items GROUP BY order_item_id HAVING COUNT(*) > 1;

SELECT 'tickets_pk_dupes' AS check_name, ticket_id, COUNT(*)
FROM tickets GROUP BY ticket_id HAVING COUNT(*) > 1;

-- ----------------------------------------------------------------------------
-- 3. FOREIGN KEY INTEGRITY  (expect 0 rows from each — orphan check)
-- ----------------------------------------------------------------------------
SELECT 'orphan_orders_customer' AS check_name, o.order_id
FROM orders o LEFT JOIN customers c ON o.customer_id = c.customer_id
WHERE c.customer_id IS NULL;

SELECT 'orphan_order_items_order' AS check_name, oi.order_item_id
FROM order_items oi LEFT JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_id IS NULL;

SELECT 'orphan_order_items_product' AS check_name, oi.order_item_id
FROM order_items oi LEFT JOIN products p ON oi.product_id = p.product_id
WHERE p.product_id IS NULL;

SELECT 'orphan_tickets_customer' AS check_name, t.ticket_id
FROM tickets t LEFT JOIN customers c ON t.customer_id = c.customer_id
WHERE c.customer_id IS NULL;

SELECT 'orphan_tickets_order' AS check_name, t.ticket_id
FROM tickets t LEFT JOIN orders o ON t.order_id = o.order_id
WHERE t.order_id IS NOT NULL AND o.order_id IS NULL;

-- ----------------------------------------------------------------------------
-- 4. NULL PATTERNS on required (NOT NULL) columns  (expect 0 rows)
-- ----------------------------------------------------------------------------
SELECT 'null_required_customers' AS check_name, COUNT(*) FROM customers
WHERE first_name IS NULL OR last_name IS NULL OR email IS NULL
   OR signup_date IS NULL OR customer_segment IS NULL OR country IS NULL
HAVING COUNT(*) > 0;

SELECT 'null_required_orders' AS check_name, COUNT(*) FROM orders
WHERE customer_id IS NULL OR order_date IS NULL OR order_status IS NULL
   OR total_amount IS NULL OR payment_method IS NULL OR expected_delivery_date IS NULL
HAVING COUNT(*) > 0;

SELECT 'null_required_tickets' AS check_name, COUNT(*) FROM tickets
WHERE customer_id IS NULL OR channel IS NULL OR message_text IS NULL
   OR category IS NULL OR priority IS NULL OR status IS NULL OR created_at IS NULL
HAVING COUNT(*) > 0;

-- Informational (NOT a failure): how many tickets have no order_id, by design
SELECT 'tickets_without_order_id (informational)' AS check_name, COUNT(*) AS ticket_count
FROM tickets WHERE order_id IS NULL;

-- ----------------------------------------------------------------------------
-- 5. DUPLICATE RECORDS  (expect 0 rows from each)
-- ----------------------------------------------------------------------------
SELECT 'duplicate_customer_emails' AS check_name, email, COUNT(*)
FROM customers GROUP BY email HAVING COUNT(*) > 1;

SELECT 'duplicate_product_skus' AS check_name, sku, COUNT(*)
FROM products GROUP BY sku HAVING COUNT(*) > 1;

SELECT 'duplicate_order_item_product_within_order' AS check_name, order_id, product_id, COUNT(*)
FROM order_items GROUP BY order_id, product_id HAVING COUNT(*) > 1;

-- ----------------------------------------------------------------------------
-- 6. ORDER TOTALS vs. ORDER_ITEMS  (expect 0 mismatches)
-- ----------------------------------------------------------------------------
SELECT 'order_total_mismatch' AS check_name, o.order_id, o.total_amount, oi_sum.computed_total
FROM orders o
JOIN (
    SELECT order_id, ROUND(SUM(line_total), 2) AS computed_total
    FROM order_items GROUP BY order_id
) oi_sum ON o.order_id = oi_sum.order_id
WHERE o.total_amount <> oi_sum.computed_total;

-- Every order should have at least one order_item (expect 0 rows)
SELECT 'orders_with_no_items' AS check_name, o.order_id
FROM orders o LEFT JOIN order_items oi ON o.order_id = oi.order_id
WHERE oi.order_item_id IS NULL;

-- line_total consistency (expect 0 — also enforced by CHECK constraint)
SELECT 'line_total_mismatch' AS check_name, order_item_id
FROM order_items
WHERE line_total <> ROUND(quantity * unit_price, 2);

-- ----------------------------------------------------------------------------
-- 7. TICKET / CUSTOMER / ORDER CONSISTENCY  (expect 0 rows — also enforced
--    by the trg_ticket_order_customer_match trigger at write time)
-- ----------------------------------------------------------------------------
SELECT 'ticket_order_customer_mismatch' AS check_name, t.ticket_id, t.customer_id AS ticket_customer,
       o.customer_id AS order_customer
FROM tickets t
JOIN orders o ON t.order_id = o.order_id
WHERE t.customer_id <> o.customer_id;

-- ----------------------------------------------------------------------------
-- 8. TIMESTAMP CONSISTENCY  (expect 0 rows from each — also enforced by CHECK)
-- ----------------------------------------------------------------------------
SELECT 'resolved_before_created' AS check_name, ticket_id FROM tickets
WHERE resolved_at IS NOT NULL AND resolved_at < created_at;

SELECT 'decision_before_created' AS check_name, ticket_id FROM tickets
WHERE decision_at IS NOT NULL AND decision_at < created_at;

SELECT 'first_response_before_created' AS check_name, ticket_id FROM tickets
WHERE first_response_at IS NOT NULL AND first_response_at < created_at;

-- Business-logic check (not a hard DB constraint): resolution should not
-- precede first response
SELECT 'resolved_before_first_response' AS check_name, ticket_id FROM tickets
WHERE resolved_at IS NOT NULL AND first_response_at IS NOT NULL
  AND resolved_at < first_response_at;

SELECT 'delivery_before_order_date' AS check_name, order_id FROM orders
WHERE actual_delivery_date IS NOT NULL AND actual_delivery_date < order_date::date;

-- ----------------------------------------------------------------------------
-- 9. CONTROLLED VOCABULARY CHECKS  (expect 0 rows — also enforced by CHECK)
-- ----------------------------------------------------------------------------
SELECT 'invalid_customer_segment' AS check_name, customer_id FROM customers
WHERE customer_segment NOT IN ('New', 'Returning', 'VIP');

SELECT 'invalid_product_category' AS check_name, product_id FROM products
WHERE category NOT IN ('Electronics Accessories', 'Home & Kitchen', 'Sports & Outdoors',
                        'Beauty & Personal Care', 'Office & Stationery', 'Toys & Games');

SELECT 'invalid_order_status' AS check_name, order_id FROM orders
WHERE order_status NOT IN ('Placed', 'Processing', 'Shipped', 'Out for Delivery', 'Delivered',
                            'Delayed', 'Cancelled', 'Returned', 'Refunded');

SELECT 'invalid_ticket_category' AS check_name, ticket_id FROM tickets
WHERE category NOT IN ('Refund Request', 'Missing Item', 'Damaged Product', 'Delivery Delay',
                        'Order Status Inquiry', 'Product Question', 'Payment Problem',
                        'Account Problem', 'Complaint', 'Other');

SELECT 'invalid_ticket_priority' AS check_name, ticket_id FROM tickets
WHERE priority NOT IN ('Low', 'Medium', 'High', 'Urgent');

SELECT 'invalid_ticket_status' AS check_name, ticket_id FROM tickets
WHERE status NOT IN ('New', 'Classified', 'Auto-Resolved', 'Escalated', 'In Progress',
                      'Pending Customer', 'Resolved', 'Closed', 'Reopened');

-- ----------------------------------------------------------------------------
-- 10. DISTRIBUTION SANITY CHECKS  (informational — confirms non-uniform data)
-- ----------------------------------------------------------------------------
SELECT 'orders_per_customer_distribution' AS check_name,
       order_count, COUNT(*) AS num_customers
FROM (
    SELECT c.customer_id, COUNT(o.order_id) AS order_count
    FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id
    GROUP BY c.customer_id
) t
GROUP BY order_count ORDER BY order_count;

SELECT 'ticket_category_distribution' AS check_name, category, COUNT(*) AS ticket_count
FROM tickets GROUP BY category ORDER BY ticket_count DESC;

SELECT 'top_selling_products' AS check_name, p.product_name, SUM(oi.quantity) AS units_sold
FROM order_items oi JOIN products p ON oi.product_id = p.product_id
GROUP BY p.product_name ORDER BY units_sold DESC LIMIT 5;
