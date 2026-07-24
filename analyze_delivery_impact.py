"""
Core analysis: does late delivery actually cost the business money?

Three steps:
  1. Classify delivered orders as On Time or Late (actual vs. estimated delivery date)
  2. Compare average review score between the two groups
  3. Compare repeat-purchase rate between customers whose FIRST order was late vs.
     on time, then translate the gap into an estimated revenue impact
"""
import sqlite3
import os
import pandas as pd

BASE = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "olist_analytics.db")
conn = sqlite3.connect(DB_PATH)

# ---------------------------------------------------------------------------
# Step 1: delivery delay per order
# ---------------------------------------------------------------------------
orders = pd.read_sql_query(
    """
    SELECT o.order_id, o.customer_id, c.customer_unique_id,
           o.order_purchase_timestamp, o.order_delivered_customer_date,
           o.order_estimated_delivery_date
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
    """,
    conn,
)
orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"])
orders["order_delivered_customer_date"] = pd.to_datetime(orders["order_delivered_customer_date"])
orders["order_estimated_delivery_date"] = pd.to_datetime(orders["order_estimated_delivery_date"])
orders["delay_days"] = (orders["order_delivered_customer_date"] - orders["order_estimated_delivery_date"]).dt.days
orders["is_late"] = orders["delay_days"] > 0

print(f"Delivered orders analyzed: {len(orders):,}")
print(f"Late orders: {orders['is_late'].sum():,} ({100*orders['is_late'].mean():.1f}%)")

# ---------------------------------------------------------------------------
# Step 2: review score, late vs on-time
# ---------------------------------------------------------------------------
# Note: 551 orders in the real data have more than one review submission.
# Keep only the most recent one per order so orders aren't double-counted.
reviews = pd.read_sql_query(
    "SELECT order_id, review_score, review_answer_timestamp FROM order_reviews", conn
)
reviews["review_answer_timestamp"] = pd.to_datetime(reviews["review_answer_timestamp"])
reviews = reviews.sort_values("review_answer_timestamp").drop_duplicates(subset="order_id", keep="last")

orders_r = orders.merge(reviews[["order_id", "review_score"]], on="order_id", how="left")

review_by_group = orders_r.groupby("is_late")["review_score"].agg(["mean", "count"]).round(2)
review_by_group.index = ["On Time", "Late"]
print("\nAverage review score:")
print(review_by_group.to_string())

pct_5star = orders_r.groupby("is_late")["review_score"].apply(lambda s: (s == 5).mean() * 100).round(1)
pct_1star = orders_r.groupby("is_late")["review_score"].apply(lambda s: (s == 1).mean() * 100).round(1)
print(f"\n% 5-star: On Time {pct_5star[False]}%, Late {pct_5star[True]}%")
print(f"% 1-star: On Time {pct_1star[False]}%, Late {pct_1star[True]}%")

# ---------------------------------------------------------------------------
# Step 3: repeat purchase rate, first order late vs on-time
# ---------------------------------------------------------------------------
all_orders = pd.read_sql_query(
    """
    SELECT o.order_id, c.customer_unique_id, o.order_purchase_timestamp
    FROM orders o JOIN customers c ON c.customer_id = o.customer_id
    """,
    conn,
)
all_orders["order_purchase_timestamp"] = pd.to_datetime(all_orders["order_purchase_timestamp"])
order_count_per_customer = all_orders.groupby("customer_unique_id")["order_id"].count()

# each customer's first DELIVERED order (that we can classify late/on-time)
orders_sorted = orders.sort_values("order_purchase_timestamp")
first_order = orders_sorted.groupby("customer_unique_id").first().reset_index()
first_order["total_orders"] = first_order["customer_unique_id"].map(order_count_per_customer)
first_order["is_repeat_customer"] = first_order["total_orders"] > 1

repeat_by_group = first_order.groupby("is_late")["is_repeat_customer"].agg(["mean", "count"])
repeat_by_group.columns = ["repeat_rate", "customers"]
repeat_by_group.index = ["On Time", "Late"]
repeat_by_group["repeat_rate"] = (repeat_by_group["repeat_rate"] * 100).round(2)
print("\nRepeat-purchase rate (first order late vs. on time):")
print(repeat_by_group.to_string())

# ---------------------------------------------------------------------------
# Revenue impact estimate
# ---------------------------------------------------------------------------
payments = pd.read_sql_query(
    "SELECT order_id, SUM(payment_value) AS order_value FROM order_payments GROUP BY order_id", conn
)
avg_order_value = payments["order_value"].mean()

on_time_rate = repeat_by_group.loc["On Time", "repeat_rate"] / 100
late_rate = repeat_by_group.loc["Late", "repeat_rate"] / 100
late_customers = repeat_by_group.loc["Late", "customers"]
rate_gap = on_time_rate - late_rate
estimated_lost_repeat_orders = rate_gap * late_customers
estimated_lost_revenue = estimated_lost_repeat_orders * avg_order_value

print(f"\nAverage order value: R$ {avg_order_value:,.2f}")
print(f"Repeat-rate gap (on-time minus late): {rate_gap*100:.2f} percentage points")
print(f"Customers whose first order was late: {late_customers:,}")
print(f"Estimated lost repeat orders: {estimated_lost_repeat_orders:,.0f}")
print(f"Estimated lost revenue: R$ {estimated_lost_revenue:,.2f}")
