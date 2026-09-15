"""
Meridian Commerce — Phase 2: Synthetic Data Generation
========================================================
Generates internally-consistent, non-uniformly-distributed synthetic data
for the five core tables (customers, products, orders, order_items, tickets)
and writes them to CSV files in ../data/.

Reproducibility: a fixed seed (SEED) drives every random draw (Python's
`random`, NumPy, and Faker), so re-running this script produces byte-identical
output.

Design choice — AI-pipeline fields are left NULL:
This dataset represents Meridian Commerce's *historical* ticket data, from
before the AI classification/automation system existed. Accordingly,
ai_predicted_category, classification_confidence, decision_path, decision_at,
and sentiment_score are left NULL for every seed ticket, and the two
automation-specific statuses ('Classified', 'Auto-Resolved') are never used.
Those fields get populated once Phase 3 (the LLM classifier) runs against
this data. This keeps Phase 2 honest: no AI/automation performance is implied
or fabricated.
"""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd
from faker import Faker


def to_money(x):
    """Quantize to exactly 2 decimal places using exact Decimal arithmetic,
    matching PostgreSQL's NUMERIC ROUND() behavior so generated line_total
    values never fail the chk_order_items_line_total CHECK constraint due to
    binary floating-point drift."""
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

# ----------------------------------------------------------------------------
# Reproducibility
# ----------------------------------------------------------------------------
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# ----------------------------------------------------------------------------
# Target volumes (approved MVP targets)
# ----------------------------------------------------------------------------
N_CUSTOMERS = 1_000
N_PRODUCTS = 150
N_ORDERS = 4_000
N_TICKETS = 1_500

# Fictional "snapshot date" for this dataset — nothing in the data occurs after this.
ANALYSIS_END = date(2026, 6, 30)
EARLIEST_SIGNUP = date(2021, 1, 1)

CATEGORIES = ['Electronics Accessories', 'Home & Kitchen', 'Sports & Outdoors',
              'Beauty & Personal Care', 'Office & Stationery', 'Toys & Games']
CATEGORY_PREFIX = {'Electronics Accessories': 'ELA', 'Home & Kitchen': 'HMK',
                    'Sports & Outdoors': 'SPO', 'Beauty & Personal Care': 'BPC',
                    'Office & Stationery': 'OFS', 'Toys & Games': 'TOY'}

ORDER_STATUSES_TERMINAL = ['Delivered', 'Delayed', 'Cancelled', 'Returned', 'Refunded']
PAYMENT_METHODS = ['Credit Card', 'Debit Card', 'PayPal', 'Apple Pay',
                    'Google Pay', 'Gift Card', 'Bank Transfer']
PAYMENT_WEIGHTS = [0.45, 0.20, 0.20, 0.07, 0.05, 0.02, 0.01]

TICKET_CATEGORIES = ['Order Status Inquiry', 'Delivery Delay', 'Refund Request',
                      'Product Question', 'Damaged Product', 'Missing Item',
                      'Complaint', 'Payment Problem', 'Account Problem', 'Other']
TICKET_CATEGORY_WEIGHTS = [0.18, 0.15, 0.13, 0.12, 0.10, 0.09, 0.08, 0.07, 0.05, 0.03]

CHANNELS = ['Email', 'Chat', 'Phone', 'Social Media', 'Contact Form']
CHANNEL_WEIGHTS = [0.40, 0.35, 0.15, 0.05, 0.05]

# Priority given a category (default / most-likely priority per Phase 1 rules)
DEFAULT_PRIORITY = {
    'Order Status Inquiry': 'Low', 'Product Question': 'Low',
    'Delivery Delay': 'Medium', 'Refund Request': 'Medium',
    'Damaged Product': 'High', 'Missing Item': 'High', 'Payment Problem': 'High',
    'Complaint': 'Urgent', 'Account Problem': 'Medium', 'Other': 'Low',
}
PRIORITY_LEVELS = ['Low', 'Medium', 'High', 'Urgent']


def days_between(d1, d2):
    return (d2 - d1).days


# ----------------------------------------------------------------------------
# 1. CUSTOMERS
# ----------------------------------------------------------------------------
def generate_customers(n=N_CUSTOMERS):
    segments = np.random.choice(['New', 'Returning', 'VIP'], size=n, p=[0.30, 0.55, 0.15])
    countries = np.random.choice(
        ['United States', 'Canada', 'United Kingdom', 'Germany', 'Australia', 'France'],
        size=n, p=[0.55, 0.15, 0.12, 0.08, 0.06, 0.04]
    )
    is_active = np.random.choice([True, False], size=n, p=[0.95, 0.05])

    rows = []
    total_span = days_between(EARLIEST_SIGNUP, ANALYSIS_END)
    for i in range(1, n + 1):
        first = fake.first_name()
        last = fake.last_name()
        # unique, deterministic email (avoids faker.unique overhead / collisions)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        # mild growth trend: more signups in recent years than early years
        offset_frac = np.random.beta(2, 1.3)
        signup = EARLIEST_SIGNUP + timedelta(days=int(offset_frac * total_span))
        rows.append({
            'customer_id': i,
            'first_name': first,
            'last_name': last,
            'email': email,
            'phone': fake.phone_number()[:20],
            'signup_date': signup,
            'customer_segment': segments[i - 1],
            'country': countries[i - 1],
            'is_active': bool(is_active[i - 1]),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 2. PRODUCTS
# ----------------------------------------------------------------------------
PRODUCT_NAME_POOLS = {
    'Electronics Accessories': [
        'Wireless Bluetooth Earbuds', 'USB-C Charging Cable', 'Phone Camera Lens Kit',
        'Portable Power Bank', 'Wireless Charging Pad', 'Laptop Sleeve Case',
        'Bluetooth Speaker Mini', 'Noise-Cancelling Headphones', 'Phone Ring Holder',
        'HDMI Adapter Cable', 'USB Hub 4-Port', 'Screen Protector Pack',
        'Car Phone Mount', 'Webcam Cover Slide', 'Mechanical Keyboard',
        'Wireless Mouse', 'Cable Organizer Set', 'Smartwatch Band',
        'Tablet Stand', 'Earbud Case Cover', 'Surge Protector Strip',
        'Bluetooth Adapter Dongle', 'Phone Grip Stand', 'LED Desk Lamp USB',
        'Travel Adapter Kit',
    ],
    'Home & Kitchen': [
        'Stainless Steel Water Bottle', 'Non-Stick Frying Pan', 'Ceramic Coffee Mug Set',
        'Bamboo Cutting Board', 'Silicone Baking Mat', 'Electric Kettle',
        'Knife Sharpener Tool', 'Glass Food Containers', 'Dish Drying Rack',
        'Kitchen Scale Digital', 'Reusable Produce Bags', 'Oven Mitts Set',
        'Vegetable Spiralizer', 'French Press Coffee Maker', 'Spice Rack Organizer',
        'Cast Iron Skillet', 'Silicone Spatula Set', 'Salad Spinner',
        'Wine Glass Set', 'Bath Towel Set', 'Throw Pillow Cover',
        'Scented Candle Set', 'Storage Ottoman Bin', 'Wall Clock Modern',
        'Bedside Lamp',
    ],
    'Sports & Outdoors': [
        'Yoga Mat Non-Slip', 'Resistance Band Set', 'Adjustable Dumbbell',
        'Camping Tent 2-Person', 'Insulated Water Bottle', 'Hiking Backpack',
        'Foam Roller', 'Jump Rope Speed', 'Running Armband Phone Holder',
        'Sleeping Bag Compact', 'Trekking Poles Pair', 'Bike Helmet',
        'Fitness Tracker Band', 'Cooler Bag Insulated', 'Camping Lantern LED',
        'Swim Goggles', 'Ankle Weights Pair', 'Portable Hammock',
        'Golf Ball Set', 'Basketball Official Size', 'Soccer Ball Match',
        'Tennis Racket', 'Fishing Rod Combo', 'Compression Socks',
        'Sports Duffel Bag',
    ],
    'Beauty & Personal Care': [
        'Facial Cleanser Gel', 'Vitamin C Serum', 'Moisturizing Lotion',
        'Electric Toothbrush', 'Hair Dryer Ionic', 'Makeup Brush Set',
        'Sunscreen SPF 50', 'Lip Balm Pack', 'Nail Care Kit',
        'Body Wash Natural', 'Shampoo & Conditioner Set', 'Facial Roller Jade',
        'Beard Trimmer Kit', 'Hand Cream Travel Pack', 'Face Mask Sheet Pack',
        'Hair Straightener', 'Perfume Travel Set', 'Cotton Rounds Pack',
        'Nail Polish Set', 'Exfoliating Body Scrub', 'Eyebrow Kit',
        'Deodorant Natural', 'Bath Bomb Set', 'Makeup Mirror LED',
        'Travel Toiletry Bag',
    ],
    'Office & Stationery': [
        'Gel Pen Set', 'Notebook Ruled A5', 'Desk Organizer Tray',
        'Sticky Notes Pack', 'Stapler Compact', 'Highlighter Set',
        'Mechanical Pencil Set', 'File Folder Pack', 'Whiteboard Markers',
        'Desk Calendar Planner', 'Paper Clip Set', 'Envelope Pack',
        'Label Maker Tape', 'Binder Clips Set', 'Scissors Office',
        'Correction Tape Pack', 'Desk Mat Large', 'Bookend Set',
        'Push Pin Pack', 'Rubber Stamp Set', 'Index Card Pack',
        'Laminating Sheets', 'Pencil Case', 'Wall Planner Yearly',
        'Business Card Holder',
    ],
    'Toys & Games': [
        'Building Block Set', 'Puzzle 1000-Piece', 'Board Game Family',
        'Remote Control Car', 'Plush Teddy Bear', 'Card Game Deck',
        'Building Blocks Mega Set', 'Play-Doh Variety Pack', 'Wooden Train Set',
        'Action Figure Set', 'Kids Art Supplies Kit', 'Toy Kitchen Set',
        'Dinosaur Figure Set', 'Water Gun Blaster', 'Rubik\'s Cube Puzzle',
        'Toy Drone Mini', 'Craft Kit Kids', 'Building Block Vehicles',
        'Plush Animal Set', 'Kite Flying Set', 'Bubble Machine',
        'Magnetic Tile Set', 'Toy Race Track', 'Yo-Yo Classic',
        'Stuffed Animal Large',
    ],
}


def generate_products(n=N_PRODUCTS):
    per_category = n // len(CATEGORIES)  # 150 / 6 = 25
    rows = []
    pid = 1
    for cat in CATEGORIES:
        pool = PRODUCT_NAME_POOLS[cat]
        names = pool[:per_category] if len(pool) >= per_category else (
            pool * (per_category // len(pool) + 1))[:per_category]
        price_low, price_high = {
            'Electronics Accessories': (8, 120), 'Home & Kitchen': (10, 150),
            'Sports & Outdoors': (10, 200), 'Beauty & Personal Care': (5, 60),
            'Office & Stationery': (3, 50), 'Toys & Games': (8, 90),
        }[cat]
        for j, name in enumerate(names, start=1):
            price = round(np.random.uniform(price_low, price_high), 2)
            stock = int(np.random.choice(
                [0, np.random.randint(1, 500)], p=[0.05, 0.95]))
            is_active = np.random.choice([True, False], p=[0.92, 0.08])
            rows.append({
                'product_id': pid,
                'product_name': name,
                'category': cat,
                'sku': f"{CATEGORY_PREFIX[cat]}-{j:04d}",
                'price': price,
                'stock_quantity': stock,
                'is_active': bool(is_active),
            })
            pid += 1
    df = pd.DataFrame(rows)
    # Popularity weight per product (log-normal -> some products sell far more
    # than others) used later when sampling order_items.
    df['_popularity'] = np.random.lognormal(mean=0.0, sigma=1.1, size=len(df))
    return df


# ----------------------------------------------------------------------------
# 3. ORDERS
# ----------------------------------------------------------------------------
def generate_orders(customers_df, n=N_ORDERS):
    seg_multiplier = {'VIP': 5.0, 'Returning': 2.0, 'New': 1.0}

    # ~12% of customers never order at all
    n_no_order = int(len(customers_df) * 0.12)
    no_order_ids = set(
        np.random.choice(customers_df['customer_id'], size=n_no_order, replace=False)
    )
    eligible = customers_df[~customers_df['customer_id'].isin(no_order_ids)].reset_index(drop=True)

    weights = eligible['customer_segment'].map(seg_multiplier).to_numpy() * (
        np.random.exponential(scale=1.0, size=len(eligible)) + 0.1
    )
    probs = weights / weights.sum()
    chosen_customer_ids = np.random.choice(eligible['customer_id'], size=n, p=probs)

    signup_lookup = customers_df.set_index('customer_id')['signup_date'].to_dict()

    rows = []
    for i in range(1, n + 1):
        cust_id = int(chosen_customer_ids[i - 1])
        signup = signup_lookup[cust_id]
        span = max(days_between(signup, ANALYSIS_END), 1)
        # recency-weighted: orders skew towards more recent dates (company growth)
        offset_frac = np.random.beta(2.2, 1.0)
        order_dt = datetime.combine(signup, datetime.min.time()) + timedelta(
            days=int(offset_frac * span), hours=int(np.random.uniform(8, 21)),
            minutes=int(np.random.uniform(0, 59)))
        days_to_end = days_between(order_dt.date(), ANALYSIS_END)

        # status depends on how recent the order is
        if days_to_end < 2:
            status = np.random.choice(['Placed', 'Processing'], p=[0.6, 0.4])
        elif days_to_end < 5:
            status = np.random.choice(['Processing', 'Shipped'], p=[0.4, 0.6])
        elif days_to_end < 10:
            status = np.random.choice(['Shipped', 'Out for Delivery', 'Delivered'],
                                       p=[0.3, 0.3, 0.4])
        else:
            status = np.random.choice(ORDER_STATUSES_TERMINAL,
                                       p=[0.85, 0.05, 0.05, 0.03, 0.02])

        expected_delivery = order_dt.date() + timedelta(days=int(np.random.randint(3, 11)))

        actual_delivery = None
        if status in ('Delivered', 'Returned', 'Refunded'):
            actual_delivery = expected_delivery + timedelta(days=int(np.random.randint(-2, 2)))
            if actual_delivery < order_dt.date():
                actual_delivery = order_dt.date()
        elif status == 'Delayed':
            candidate = expected_delivery + timedelta(days=int(np.random.randint(3, 11)))
            actual_delivery = candidate if candidate <= ANALYSIS_END else None

        if actual_delivery is not None and actual_delivery > ANALYSIS_END:
            actual_delivery = ANALYSIS_END

        payment = np.random.choice(PAYMENT_METHODS, p=PAYMENT_WEIGHTS)

        rows.append({
            'order_id': i,
            'customer_id': cust_id,
            'order_date': order_dt,
            'order_status': status,
            'total_amount': 0.0,  # backfilled after order_items are generated
            'payment_method': payment,
            'expected_delivery_date': expected_delivery,
            'actual_delivery_date': actual_delivery,
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 4. ORDER_ITEMS  (also backfills orders.total_amount)
# ----------------------------------------------------------------------------
def generate_order_items(orders_df, products_df):
    item_count_choices = [1, 2, 3, 4, 5, 6]
    item_count_weights = [0.32, 0.28, 0.18, 0.12, 0.07, 0.03]
    qty_choices = [1, 2, 3, 4, 5]
    qty_weights = [0.65, 0.20, 0.09, 0.04, 0.02]

    active_products = products_df[products_df['is_active']].reset_index(drop=True)
    if active_products.empty:
        active_products = products_df

    pop = active_products['_popularity'].to_numpy()
    pop_probs = pop / pop.sum()

    rows = []
    order_item_id = 1
    order_totals = {}

    for _, order in orders_df.iterrows():
        n_items = int(np.random.choice(item_count_choices, p=item_count_weights))
        n_items = min(n_items, len(active_products))
        chosen_idx = np.random.choice(
            len(active_products), size=n_items, replace=False, p=pop_probs)
        order_total = Decimal('0.00')
        for idx in chosen_idx:
            prod = active_products.iloc[idx]
            qty = int(np.random.choice(qty_choices, p=qty_weights))
            # unit_price = price at time of purchase; small drift from current price.
            # Quantized with Decimal (not float round()) so it exactly matches how
            # PostgreSQL's NUMERIC(10,2) will store and re-derive the value.
            unit_price = to_money(float(prod['price']) * np.random.uniform(0.90, 1.05))
            line_total = to_money(Decimal(qty) * unit_price)  # exact decimal math, no FP drift
            order_total += line_total
            rows.append({
                'order_item_id': order_item_id,
                'order_id': int(order['order_id']),
                'product_id': int(prod['product_id']),
                'quantity': qty,
                'unit_price': float(unit_price),
                'line_total': float(line_total),
            })
            order_item_id += 1
        order_totals[order['order_id']] = float(to_money(order_total))

    order_items_df = pd.DataFrame(rows)
    orders_df = orders_df.copy()
    orders_df['total_amount'] = orders_df['order_id'].map(order_totals)
    return order_items_df, orders_df


# ----------------------------------------------------------------------------
# 5. TICKETS
# ----------------------------------------------------------------------------
MESSAGE_TEMPLATES = {
    'Order Status Inquiry': [
        "Hi, can you tell me the current status of my order? It hasn't updated in a while.",
        "Just checking in on when my package will arrive.",
        "I'd like an update on my order tracking, please.",
    ],
    'Delivery Delay': [
        "My order was supposed to arrive days ago and it still hasn't shown up.",
        "The tracking says my package is delayed. What's going on?",
        "I'm still waiting on my delivery and the expected date has already passed.",
    ],
    'Refund Request': [
        "I'd like to request a refund for my recent order.",
        "This item didn't meet my expectations, can I get my money back?",
        "Please process a refund for the order I placed.",
    ],
    'Product Question': [
        "Does this product come in other sizes or colors?",
        "Can you tell me more about the materials used in this item?",
        "Is this product compatible with other accessories I own?",
    ],
    'Damaged Product': [
        "The item I received arrived broken/damaged.",
        "My order showed up with visible damage to the packaging and product.",
        "One of the items in my order is defective.",
    ],
    'Missing Item': [
        "I'm missing an item from my order.",
        "My package arrived but one of the products wasn't inside.",
        "I only received part of my order — something is missing.",
    ],
    'Complaint': [
        "I'm very unhappy with my recent experience and want to file a complaint.",
        "This is the second issue I've had and I'm frustrated with the service.",
        "I want to raise a formal complaint about how my order was handled.",
    ],
    'Payment Problem': [
        "I was charged twice for the same order.",
        "My payment failed but the amount was still deducted from my account.",
        "There's an issue with the charge on my card for this order.",
    ],
    'Account Problem': [
        "I can't log into my account anymore.",
        "I need help resetting my password.",
        "My account information seems to be incorrect and I can't update it.",
    ],
    'Other': [
        "I have a general question that doesn't fit the other categories.",
        "Reaching out about something unrelated to a specific order.",
        "Just have a quick question for your support team.",
    ],
}


def generate_tickets(customers_df, orders_df, n=N_TICKETS):
    signup_lookup = customers_df.set_index('customer_id')['signup_date'].to_dict()
    orders_by_customer = orders_df.groupby('customer_id')['order_id'].apply(list).to_dict()
    order_lookup = orders_df.set_index('order_id')

    delayed_orders = orders_df[orders_df['order_status'] == 'Delayed']['order_id'].tolist()
    in_transit_orders = orders_df[orders_df['order_status'].isin(
        ['Placed', 'Processing', 'Shipped', 'Out for Delivery'])]['order_id'].tolist()
    delivered_orders = orders_df[orders_df['order_status'].isin(
        ['Delivered', 'Returned', 'Refunded'])]['order_id'].tolist()
    any_orders = orders_df['order_id'].tolist()
    all_customer_ids = customers_df['customer_id'].tolist()

    def pick_order_for_category(cat):
        """Return an order_id (biased by category) or None."""
        pool, none_prob = {
            'Delivery Delay': (delayed_orders or in_transit_orders, 0.05),
            'Order Status Inquiry': (in_transit_orders or any_orders, 0.10),
            'Damaged Product': (delivered_orders or any_orders, 0.05),
            'Missing Item': (delivered_orders or any_orders, 0.05),
            'Refund Request': (delivered_orders or any_orders, 0.10),
            'Payment Problem': (any_orders, 0.45),
            'Complaint': (any_orders, 0.50),
            'Product Question': (any_orders, 0.70),
            'Account Problem': ([], 1.0),
            'Other': (any_orders, 0.90),
        }[cat]
        if not pool or np.random.random() < none_prob:
            return None
        return int(np.random.choice(pool))

    rows = []
    for i in range(1, n + 1):
        category = str(np.random.choice(TICKET_CATEGORIES, p=TICKET_CATEGORY_WEIGHTS))
        order_id = pick_order_for_category(category)

        if order_id is not None:
            order_row = order_lookup.loc[order_id]
            customer_id = int(order_row['customer_id'])
            order_date = order_row['order_date']
            if isinstance(order_date, pd.Timestamp):
                order_date = order_date.to_pydatetime()
            latest_possible = min(order_date + timedelta(days=60),
                                   datetime.combine(ANALYSIS_END, datetime.max.time()))
            span_seconds = max(int((latest_possible - order_date).total_seconds()), 3600)
            created_at = order_date + timedelta(seconds=int(np.random.uniform(3600, span_seconds)))
        else:
            customer_id = int(np.random.choice(all_customer_ids))
            signup = signup_lookup[customer_id]
            span = max(days_between(signup, ANALYSIS_END), 1)
            offset_frac = np.random.beta(2.0, 1.2)
            created_at = datetime.combine(signup, datetime.min.time()) + timedelta(
                days=int(offset_frac * span), hours=int(np.random.uniform(8, 21)))

        if created_at.date() > ANALYSIS_END:
            created_at = datetime.combine(ANALYSIS_END, datetime.min.time())

        channel = str(np.random.choice(CHANNELS, p=CHANNEL_WEIGHTS))

        # priority: mostly the category's default, with some realistic noise
        default_pr = DEFAULT_PRIORITY[category]
        if np.random.random() < 0.80:
            priority = default_pr
        else:
            priority = str(np.random.choice(PRIORITY_LEVELS))

        days_open = days_between(created_at.date(), ANALYSIS_END)

        # status depends on ticket age (older tickets are mostly closed out)
        if days_open < 2:
            status = np.random.choice(['New', 'In Progress'], p=[0.6, 0.4])
        elif days_open < 7:
            status = np.random.choice(['In Progress', 'Pending Customer', 'Escalated', 'Resolved'],
                                       p=[0.35, 0.25, 0.15, 0.25])
        elif days_open < 21:
            status = np.random.choice(['Resolved', 'Closed', 'In Progress', 'Escalated'],
                                       p=[0.35, 0.35, 0.15, 0.15])
        else:
            status = np.random.choice(['Closed', 'Resolved', 'Reopened', 'Escalated'],
                                       p=[0.70, 0.18, 0.07, 0.05])

        # first_response_at
        first_response_at = None
        resp_delay_hours = {'Urgent': (0.25, 6), 'High': (0.5, 18),
                             'Medium': (1, 36), 'Low': (2, 60)}[priority]
        candidate = created_at + timedelta(hours=float(np.random.uniform(*resp_delay_hours)))
        if candidate <= datetime.combine(ANALYSIS_END, datetime.max.time()):
            first_response_at = candidate

        # resolved_at only for tickets in a resolved-ish state
        resolved_at = None
        if status in ('Resolved', 'Closed', 'Reopened') and first_response_at is not None:
            res_hours = {'Urgent': (1, 24), 'High': (2, 48),
                         'Medium': (4, 96), 'Low': (4, 72)}[priority]
            candidate_r = first_response_at + timedelta(hours=float(np.random.uniform(*res_hours)))
            if candidate_r <= datetime.combine(ANALYSIS_END, datetime.max.time()):
                resolved_at = candidate_r
            else:
                # can't resolve after the snapshot date; demote to an open state
                status = 'Escalated' if np.random.random() < 0.5 else 'In Progress'

        updated_at = resolved_at or first_response_at or created_at

        # resolution_type: historically, only ever 'Human' (no automation existed yet)
        resolution_type = 'Human' if resolved_at is not None else None

        message_text = str(np.random.choice(MESSAGE_TEMPLATES[category]))

        rows.append({
            'ticket_id': i,
            'customer_id': customer_id,
            'order_id': order_id,
            'channel': channel,
            'message_text': message_text,
            'category': category,
            'ai_predicted_category': None,       # populated in Phase 3
            'classification_confidence': None,   # populated in Phase 3
            'priority': priority,
            'status': status,
            'decision_path': None,               # populated in Phase 3
            'resolution_type': resolution_type,
            'sentiment_score': None,             # populated in Phase 3
            'created_at': created_at,
            'decision_at': None,                 # populated in Phase 3
            'first_response_at': first_response_at,
            'resolved_at': resolved_at,
            'updated_at': updated_at,
        })

    df = pd.DataFrame(rows)
    # Nullable integer dtype so order_id exports as clean ints / blank, never "3480.0"
    df['order_id'] = df['order_id'].astype('Int64')
    return df


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    print("Generating customers...")
    customers_df = generate_customers()

    print("Generating products...")
    products_df = generate_products()

    print("Generating orders...")
    orders_df = generate_orders(customers_df)

    print("Generating order_items (and backfilling order totals)...")
    order_items_df, orders_df = generate_order_items(orders_df, products_df)

    print("Generating tickets...")
    tickets_df = generate_tickets(customers_df, orders_df)

    # Drop internal helper column before export
    products_export = products_df.drop(columns=['_popularity'])

    out_dir = "../data"
    customers_df.to_csv(f"{out_dir}/customers.csv", index=False)
    products_export.to_csv(f"{out_dir}/products.csv", index=False)
    orders_df.to_csv(f"{out_dir}/orders.csv", index=False)
    order_items_df.to_csv(f"{out_dir}/order_items.csv", index=False)
    tickets_df.to_csv(f"{out_dir}/tickets.csv", index=False)

    print("\nRow counts:")
    print(f"  customers:   {len(customers_df):,}")
    print(f"  products:    {len(products_export):,}")
    print(f"  orders:      {len(orders_df):,}")
    print(f"  order_items: {len(order_items_df):,}")
    print(f"  tickets:     {len(tickets_df):,}")
    print("\nDone. CSVs written to", out_dir)


if __name__ == "__main__":
    main()
