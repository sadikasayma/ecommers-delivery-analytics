"""
Deep dive on the delivery-delay finding: quantify excess negative reviews
caused by lateness, and find WHERE the lateness is concentrated (which
seller states / product categories) so the recommendation is actionable,
not just "late delivery is bad."
"""
import sqlite3
import os
import pandas as pd

BASE = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "olist_analytics.db")
conn = sqlite3.connect(DB_PATH)

orders = pd.read_sql_query(
    """
    SELECT o.order_id, o.order_delivered_customer_date, o.order_estimated_delivery_date
    FROM orders o
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
    """,
    conn,
)
orders["order_delivered_customer_date"] = pd.to_datetime(orders["order_delivered_customer_date"])
orders["order_estimated_delivery_date"] = pd.to_datetime(orders["order_estimated_delivery_date"])
# order_estimated_delivery_date is date-only (midnight); comparing full timestamps
# directly would wrongly flag same-day-but-later-time deliveries as "late".
# Use whole-day difference instead, matching analyze_delivery_impact.py.
orders["delay_days"] = (orders["order_delivered_customer_date"] - orders["order_estimated_delivery_date"]).dt.days
orders["is_late"] = orders["delay_days"] > 0

# Note: 551 orders in the real data have more than one review submission.
# Keep only the most recent one per order so orders aren't double-counted.
reviews = pd.read_sql_query(
    "SELECT order_id, review_score, review_answer_timestamp FROM order_reviews", conn
)
reviews["review_answer_timestamp"] = pd.to_datetime(reviews["review_answer_timestamp"])
reviews = reviews.sort_values("review_answer_timestamp").drop_duplicates(subset="order_id", keep="last")

df = orders.merge(reviews[["order_id", "review_score"]], on="order_id", how="left")

# ---------------------------------------------------------------------------
# Excess negative reviews caused by lateness
# ---------------------------------------------------------------------------
on_time = df[~df["is_late"]]
late = df[df["is_late"]]

on_time_1star_rate = (on_time["review_score"] == 1).mean()
late_1star_rate = (late["review_score"] == 1).mean()
n_late = len(late)

expected_1star = on_time_1star_rate * n_late
actual_1star = late_1star_rate * n_late
excess_1star = actual_1star - expected_1star

print(f"On-time 1-star rate: {on_time_1star_rate*100:.1f}%")
print(f"Late 1-star rate: {late_1star_rate*100:.1f}%")
print(f"Late orders: {n_late:,}")
print(f"Expected 1-star reviews if late orders behaved like on-time: {expected_1star:.0f}")
print(f"Actual 1-star reviews among late orders: {actual_1star:.0f}")
print(f"Excess 1-star reviews caused by lateness: {excess_1star:.0f}")

# order value tied to late orders (revenue "exposed" to a bad-review risk)
payments = pd.read_sql_query(
    "SELECT order_id, SUM(payment_value) AS order_value FROM order_payments GROUP BY order_id", conn
)
late_with_value = late.merge(payments, on="order_id", how="left")
total_late_order_value = late_with_value["order_value"].sum()
print(f"\nTotal order value among late deliveries: R$ {total_late_order_value:,.2f}")

# ---------------------------------------------------------------------------
# Where is lateness concentrated? By seller state
# ---------------------------------------------------------------------------
items_sellers = pd.read_sql_query(
    """
    SELECT oi.order_id, s.seller_state
    FROM order_items oi
    JOIN sellers s ON s.seller_id = oi.seller_id
    """,
    conn,
).drop_duplicates(subset=["order_id"])  # one seller-state per order for simplicity

df_state = orders.merge(items_sellers, on="order_id", how="left")
state_late_rate = df_state.groupby("seller_state").agg(
    total_orders=("order_id", "count"),
    late_orders=("is_late", "sum"),
)
state_late_rate["late_rate_pct"] = (100 * state_late_rate["late_orders"] / state_late_rate["total_orders"]).round(1)
state_late_rate = state_late_rate[state_late_rate["total_orders"] >= 30].sort_values("late_rate_pct", ascending=False)
print("\nTop 10 seller states by late-delivery rate (min. 30 orders):")
print(state_late_rate.head(10).to_string())

# ---------------------------------------------------------------------------
# Where is lateness concentrated? By product category
# ---------------------------------------------------------------------------
items_cat = pd.read_sql_query(
    """
    SELECT oi.order_id, COALESCE(t.product_category_name_english, p.product_category_name) AS category
    FROM order_items oi
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
    """,
    conn,
).drop_duplicates(subset=["order_id"])

df_cat = orders.merge(items_cat, on="order_id", how="left")
cat_late_rate = df_cat.groupby("category").agg(
    total_orders=("order_id", "count"),
    late_orders=("is_late", "sum"),
)
cat_late_rate["late_rate_pct"] = (100 * cat_late_rate["late_orders"] / cat_late_rate["total_orders"]).round(1)
cat_late_rate = cat_late_rate[cat_late_rate["total_orders"] >= 100].sort_values("late_rate_pct", ascending=False)
print("\nTop 10 product categories by late-delivery rate (min. 100 orders):")
print(cat_late_rate.head(10).to_string())
