"""
Builds one wide, order-level fact table — the shared source for the Tableau
export and the Excel workbook, so both tools show numbers that trace back to
the same underlying data.
"""
import sqlite3
import os
import numpy as np
import pandas as pd

BASE = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "olist_analytics.db")
conn = sqlite3.connect(DB_PATH)

orders = pd.read_sql_query(
    """
    SELECT o.order_id, o.customer_id, o.order_purchase_timestamp,
           o.order_delivered_customer_date, o.order_estimated_delivery_date
    FROM orders o
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
    """,
    conn,
)
for c in ["order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"]:
    orders[c] = pd.to_datetime(orders[c])

orders["delay_days"] = (orders["order_delivered_customer_date"] - orders["order_estimated_delivery_date"]).dt.days
orders["is_late"] = (orders["delay_days"] > 0).astype(int)
orders["promised_days"] = (orders["order_estimated_delivery_date"] - orders["order_purchase_timestamp"]).dt.days
orders["order_purchase_date"] = orders["order_purchase_timestamp"].dt.date
orders["order_purchase_month"] = orders["order_purchase_timestamp"].dt.to_period("M").astype(str)

items = pd.read_sql_query("SELECT order_id, seller_id, product_id, price, freight_value FROM order_items", conn)
item_agg = items.groupby("order_id").agg(
    price=("price", "sum"), freight_value=("freight_value", "sum"), item_count=("price", "count")
)
first_item = items.drop_duplicates("order_id")[["order_id", "seller_id", "product_id"]]

customers = pd.read_sql_query("SELECT customer_id, customer_zip_code_prefix, customer_city, customer_state FROM customers", conn)
sellers = pd.read_sql_query("SELECT seller_id, seller_zip_code_prefix, seller_city, seller_state FROM sellers", conn)
products = pd.read_sql_query("SELECT product_id, product_category_name FROM products", conn)
cat_translation = pd.read_sql_query("SELECT * FROM category_translation", conn)
products = products.merge(cat_translation, on="product_category_name", how="left")
products["category"] = products["product_category_name_english"].fillna(products["product_category_name"]).fillna("unknown")

geo = pd.read_sql_query(
    "SELECT geolocation_zip_code_prefix AS zip, AVG(geolocation_lat) AS lat, AVG(geolocation_lng) AS lng "
    "FROM geolocation GROUP BY geolocation_zip_code_prefix",
    conn,
)

payments = pd.read_sql_query(
    "SELECT order_id, SUM(payment_value) AS payment_value, MAX(payment_installments) AS payment_installments, "
    "GROUP_CONCAT(DISTINCT payment_type) AS payment_types FROM order_payments GROUP BY order_id",
    conn,
)

reviews = pd.read_sql_query(
    "SELECT order_id, review_score, review_answer_timestamp FROM order_reviews", conn
)
reviews["review_answer_timestamp"] = pd.to_datetime(reviews["review_answer_timestamp"])
reviews = reviews.sort_values("review_answer_timestamp").drop_duplicates(subset="order_id", keep="last")

df = orders.merge(item_agg, on="order_id", how="inner")
df = df.merge(first_item[["order_id", "seller_id", "product_id"]], on="order_id", how="left")
df = df.merge(customers, on="customer_id", how="left")
df = df.merge(sellers, on="seller_id", how="left")
df = df.merge(products[["product_id", "category"]], on="product_id", how="left")
df = df.merge(payments[["order_id", "payment_value", "payment_installments", "payment_types"]], on="order_id", how="left")
df = df.merge(reviews[["order_id", "review_score"]], on="order_id", how="left")

df = df.merge(geo.rename(columns={"lat": "cust_lat", "lng": "cust_lng"}),
              left_on="customer_zip_code_prefix", right_on="zip", how="left")
df = df.merge(geo.rename(columns={"lat": "seller_lat", "lng": "seller_lng"}),
              left_on="seller_zip_code_prefix", right_on="zip", how="left")


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1, lng1, lat2, lng2 = map(np.radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


df["distance_km"] = haversine_km(df["cust_lat"], df["cust_lng"], df["seller_lat"], df["seller_lng"]).round(1)
df["order_value"] = (df["price"] + df["freight_value"]).round(2)

final_cols = [
    "order_id", "order_purchase_date", "order_purchase_month",
    "customer_city", "customer_state", "seller_city", "seller_state",
    "category", "price", "freight_value", "order_value", "item_count",
    "payment_types", "payment_installments",
    "promised_days", "delay_days", "is_late", "review_score", "distance_km",
]
fact = df[final_cols].copy()
fact.to_csv(os.path.join(BASE, "data", "order_fact_table.csv"), index=False)
print(f"Fact table built: {len(fact):,} rows, {len(final_cols)} columns")
print(fact.head(3).to_string())
