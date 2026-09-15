"""
Meridian Commerce — Phase 2: Data Loading
===========================================
Loads the CSVs produced by generate_data.py into PostgreSQL using COPY
(the standard high-throughput bulk-load path in Postgres — far faster than
row-by-row INSERTs for tens of thousands of rows).

Tables are loaded in FK-dependency order: customers, products, orders,
order_items, tickets.

Usage:
    python load_data.py --host localhost --port 5432 --dbname meridian_commerce \
        --user meridian_app --password ****** --data-dir ../data
"""

import argparse
import sys

import psycopg2

TABLE_LOAD_ORDER = [
    ("customers", "customers.csv",
     "customer_id, first_name, last_name, email, phone, signup_date, "
     "customer_segment, country, is_active"),
    ("products", "products.csv",
     "product_id, product_name, category, sku, price, stock_quantity, is_active"),
    ("orders", "orders.csv",
     "order_id, customer_id, order_date, order_status, total_amount, "
     "payment_method, expected_delivery_date, actual_delivery_date"),
    ("order_items", "order_items.csv",
     "order_item_id, order_id, product_id, quantity, unit_price, line_total"),
    ("tickets", "tickets.csv",
     "ticket_id, customer_id, order_id, channel, message_text, category, "
     "ai_predicted_category, classification_confidence, priority, status, "
     "decision_path, resolution_type, sentiment_score, created_at, decision_at, "
     "first_response_at, resolved_at, updated_at"),
]

# Sequences must be re-synced after loading explicit ID values via COPY,
# otherwise the next application-side INSERT would collide on the PK.
SEQUENCE_RESYNC = {
    "customers": ("customers_customer_id_seq", "customer_id"),
    "products": ("products_product_id_seq", "product_id"),
    "orders": ("orders_order_id_seq", "order_id"),
    "order_items": ("order_items_order_item_id_seq", "order_item_id"),
    "tickets": ("tickets_ticket_id_seq", "ticket_id"),
}


def main():
    parser = argparse.ArgumentParser(description="Load Meridian Commerce seed CSVs into PostgreSQL")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--dbname", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--data-dir", default="../data")
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Truncate in reverse-dependency order so re-runs are idempotent
        cur.execute("TRUNCATE tickets, order_items, orders, products, customers RESTART IDENTITY CASCADE;")

        for table, filename, columns in TABLE_LOAD_ORDER:
            path = f"{args.data_dir}/{filename}"
            with open(path, "r", encoding="utf-8") as f:
                copy_sql = f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')"
                cur.copy_expert(copy_sql, f)
            print(f"Loaded {table} from {filename}")

        for table, (seq_name, id_col) in SEQUENCE_RESYNC.items():
            cur.execute(
                f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({id_col}) FROM {table}), 1))"
            )

        conn.commit()
        print("\nAll tables loaded and committed successfully.")

        cur.execute("""
            SELECT 'customers', COUNT(*) FROM customers
            UNION ALL SELECT 'products', COUNT(*) FROM products
            UNION ALL SELECT 'orders', COUNT(*) FROM orders
            UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
            UNION ALL SELECT 'tickets', COUNT(*) FROM tickets;
        """)
        print("\nRow counts in database:")
        for name, count in cur.fetchall():
            print(f"  {name}: {count:,}")

    except Exception as e:
        conn.rollback()
        print(f"Load failed, transaction rolled back: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
