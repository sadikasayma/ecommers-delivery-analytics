"""
Delivery-delay risk model: flags orders at risk of arriving late, using only
information available at the moment of purchase (no leakage from the future).

Method notes (this is the part worth explaining in an interview):
  - Split is TIME-BASED (train on the earliest 80% of orders, test on the most
    recent 20%), not a random shuffle. A random split would leak information
    from the future into training and overstate accuracy.
  - The "seller late-rate" feature is computed using ONLY the training period,
    then applied to both train and test — computing it from the full dataset
    (including test) would itself be a leakage bug.
  - Logistic regression is implemented from scratch with NumPy (gradient
    descent) since scikit-learn isn't available in this environment — this
    also means every step is visible/explainable rather than a library call.
"""
import sqlite3
import os
import numpy as np
import pandas as pd

BASE = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, "olist_analytics.db")
conn = sqlite3.connect(DB_PATH)

# ---------------------------------------------------------------------------
# Build one row per order with features known AT PURCHASE TIME
# ---------------------------------------------------------------------------
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
orders["purchase_month"] = orders["order_purchase_timestamp"].dt.month
orders["purchase_dow"] = orders["order_purchase_timestamp"].dt.dayofweek

items = pd.read_sql_query(
    "SELECT order_id, seller_id, price, freight_value FROM order_items", conn
)
item_agg = items.groupby("order_id").agg(
    price=("price", "sum"),
    freight_value=("freight_value", "sum"),
    item_count=("price", "count"),
)
# use the first seller per order as a simplification for multi-seller orders
first_seller = items.drop_duplicates("order_id")[["order_id", "seller_id"]]

customers = pd.read_sql_query("SELECT customer_id, customer_zip_code_prefix FROM customers", conn)
sellers = pd.read_sql_query("SELECT seller_id, seller_zip_code_prefix, seller_state FROM sellers", conn)
geo = pd.read_sql_query(
    "SELECT geolocation_zip_code_prefix AS zip, AVG(geolocation_lat) AS lat, AVG(geolocation_lng) AS lng "
    "FROM geolocation GROUP BY geolocation_zip_code_prefix",
    conn,
)

df = orders.merge(item_agg, on="order_id", how="inner")
df = df.merge(first_seller, on="order_id", how="left")
df = df.merge(customers, on="customer_id", how="left")
df = df.merge(sellers, on="seller_id", how="left")
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


df["distance_km"] = haversine_km(df["cust_lat"], df["cust_lng"], df["seller_lat"], df["seller_lng"])

# ---------------------------------------------------------------------------
# Time-based split (NOT random) — train on earliest 80%, test on latest 20%
# ---------------------------------------------------------------------------
df = df.sort_values("order_purchase_timestamp").reset_index(drop=True)
split_idx = int(len(df) * 0.8)
split_date = df.loc[split_idx, "order_purchase_timestamp"]
train = df.iloc[:split_idx].copy()
test = df.iloc[split_idx:].copy()
print(f"Train: {len(train):,} orders (up to {train['order_purchase_timestamp'].max().date()})")
print(f"Test:  {len(test):,} orders (from {test['order_purchase_timestamp'].min().date()} "
      f"to {test['order_purchase_timestamp'].max().date()})")

# Seller late-rate feature — computed from TRAIN ONLY to avoid leakage
seller_rate = train.groupby("seller_id")["is_late"].mean()
global_train_rate = train["is_late"].mean()
train["seller_late_rate"] = train["seller_id"].map(seller_rate)
test["seller_late_rate"] = test["seller_id"].map(seller_rate).fillna(global_train_rate)

FEATURES = ["promised_days", "purchase_month", "purchase_dow", "price", "freight_value",
            "item_count", "distance_km", "seller_late_rate"]

for part in (train, test):
    part[FEATURES] = part[FEATURES].fillna(part[FEATURES].median())

# Standardize using TRAIN stats only
means = train[FEATURES].mean()
stds = train[FEATURES].std().replace(0, 1)
X_train = ((train[FEATURES] - means) / stds).values
X_test = ((test[FEATURES] - means) / stds).values
y_train = train["is_late"].values
y_test = test["is_late"].values

X_train_b = np.hstack([np.ones((len(X_train), 1)), X_train])
X_test_b = np.hstack([np.ones((len(X_test), 1)), X_test])

# ---------------------------------------------------------------------------
# Logistic regression from scratch (gradient descent)
# ---------------------------------------------------------------------------
np.random.seed(42)
n_features = X_train_b.shape[1]
weights = np.zeros(n_features)
lr = 0.1
n_iters = 3000


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


for i in range(n_iters):
    z = X_train_b @ weights
    preds = sigmoid(z)
    grad = X_train_b.T @ (preds - y_train) / len(y_train)
    weights -= lr * grad

train_pred_prob = sigmoid(X_train_b @ weights)
test_pred_prob = sigmoid(X_test_b @ weights)

print("\nLearned feature weights (standardized scale):")
for name, w in zip(["intercept"] + FEATURES, weights):
    print(f"  {name}: {w:+.3f}")

# ---------------------------------------------------------------------------
# Metrics (implemented manually — no sklearn.metrics available)
# ---------------------------------------------------------------------------
def evaluate(y_true, y_prob, threshold=0.5):
    y_pred = (y_prob >= threshold).astype(int)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    accuracy = (tp + tn) / len(y_true)

    # AUC via rank-sum (Mann-Whitney U) method — exact, no library needed
    order = np.argsort(y_prob)
    ranks = np.empty(len(y_prob))
    ranks[order] = np.arange(1, len(y_prob) + 1)
    n_pos = y_true.sum()
    n_neg = len(y_true) - n_pos
    sum_ranks_pos = ranks[y_true == 1].sum()
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg) if n_pos and n_neg else float("nan")

    return dict(accuracy=accuracy, precision=precision, recall=recall, f1=f1, auc=auc,
                tp=tp, fp=fp, fn=fn, tn=tn)


print(f"\nBaseline (always predict majority class 'on time'): "
      f"{100 * (1 - y_test.mean()):.1f}% accuracy would be achieved trivially")

train_metrics = evaluate(y_train, train_pred_prob)
test_metrics = evaluate(y_test, test_pred_prob)

print("\nTRAIN metrics:", {k: round(v, 3) for k, v in train_metrics.items() if k in
                            ["accuracy", "precision", "recall", "f1", "auc"]})
print("TEST metrics: ", {k: round(v, 3) for k, v in test_metrics.items() if k in
                          ["accuracy", "precision", "recall", "f1", "auc"]})
print("TEST confusion matrix (threshold=0.5):", {k: test_metrics[k] for k in ["tp", "fp", "fn", "tn"]})
print(
    "\nNote: recall at a 0.5 threshold is misleadingly low here because late deliveries are "
    "rare (~3.6% of test orders) — the model rarely crosses 0.5 for any order. AUC (threshold-"
    "independent) is the more honest headline metric. For an operational use case, ranking orders "
    "by risk and reviewing the riskiest slice is more realistic than a fixed 0.5 cutoff:"
)

# Capture rate at top-risk deciles — how much of the actual late-delivery
# problem would ops catch if they only had time to review the riskiest X%?
test_eval = test[["order_id"]].copy()
test_eval["actual_is_late"] = y_test
test_eval["risk_score"] = test_pred_prob
test_eval = test_eval.sort_values("risk_score", ascending=False).reset_index(drop=True)
total_late = test_eval["actual_is_late"].sum()

for pct in [5, 10, 20, 30]:
    n = int(len(test_eval) * pct / 100)
    caught = test_eval.iloc[:n]["actual_is_late"].sum()
    capture_rate = 100 * caught / total_late if total_late else 0
    print(f"  Reviewing top {pct:>2}% highest-risk orders ({n:,} orders) would catch "
          f"{caught:.0f} of {total_late:.0f} actual late deliveries ({capture_rate:.1f}%)")

# Save test-set predictions for the Tableau/Excel exports
out = test[["order_id", "order_purchase_timestamp", "seller_state", "customer_zip_code_prefix",
            "distance_km", "promised_days"]].copy()
out["actual_is_late"] = y_test
out["predicted_late_probability"] = test_pred_prob
out.to_csv(os.path.join(BASE, "data", "delay_risk_predictions.csv"), index=False)
print(f"\nSaved test-set predictions to data/delay_risk_predictions.csv ({len(out):,} rows)")
