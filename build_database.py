"""
Loads the 9 real Olist CSVs (data/) into a SQLite database (olist_analytics.db)
using the schema in sql/schema.sql.
"""
import sqlite3
import os
import pandas as pd

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(BASE, "olist_analytics.db")
SCHEMA_PATH = os.path.join(BASE, "sql", "schema.sql")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
with open(SCHEMA_PATH) as f:
    conn.executescript(f.read())

files = {
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}

for table, fname in files.items():
    df = pd.read_csv(os.path.join(DATA_DIR, fname))
    df.to_sql(table, conn, if_exists="append", index=False)
    print(f"{table}: {len(df):,} rows loaded")

conn.commit()
print("\nRow counts in DB:")
for table in files:
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table}: {n:,}")

conn.close()
print(f"\nDatabase built at {DB_PATH}")
