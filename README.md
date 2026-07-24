# E-Commerce Delivery Analytics

A SQL + Python + Excel + Tableau project analyzing the real Olist Brazilian e-commerce dataset (~96,000 delivered orders): does late delivery actually cost the business money, and can at-risk orders be flagged before they happen?

## Project Overview

Unlike a purely descriptive "top products, sales by state" analysis, this project investigates one specific question end to end: does late delivery measurably hurt the business, and if so, where and how much? It traces delivery delay through to review scores and repeat-purchase behavior, quantifies the impact, identifies where lateness is concentrated, and builds a delay-risk model to flag orders proactively.

What's in this project:

1. A relational SQL database built from the real Olist dataset (9 linked tables)
2. An investigation into whether late delivery affects review scores and repeat purchases, with a dollar estimate
3. A breakdown of where lateness is concentrated (seller state, product category)
4. A delay-risk model using a proper time-based train/test split
5. An Excel workbook (live formulas) and a Tableau Public dashboard built from the same data

## Dataset

**Real, publicly available data** — the Brazilian E-Commerce Public Dataset by Olist (Kaggle), covering ~99,441 orders placed between September 2016 and October 2018. This is actual anonymized marketplace data, not generated or synthetic.

**Tables:** customers, orders, order_items, order_payments, order_reviews, products, sellers, geolocation, category_translation — see [`sql/schema.sql`](sql/schema.sql) for the full relational schema.

**Scale:** 99,441 orders (96,470 delivered with complete delivery-date data) · 112,650 order items · 103,886 payments · 99,224 review submissions (551 orders had more than one review — deduplicated to the most recent) · 32,951 products · 3,095 sellers.

## Technologies Used

- **SQL** — SQLite (schema design, joins across 9 tables, aggregate analysis)
- **Python** — pandas, NumPy (data pipeline, feature engineering, a logistic regression model built from scratch with NumPy since scikit-learn wasn't available in the build environment)
- **Excel** — a live-formula workbook (SUMIFS/COUNTIFS/AVERAGEIFS), not hardcoded results
- **Tableau Public** — interactive dashboard (see `Building the Tableau Dashboard` below)

## Methodology

### 1. Database
Loaded the 9 real Olist CSVs into a normalized SQLite database (`olist_analytics.db`) with primary/foreign keys and indexes — see [`build_database.py`](build_database.py).

### 2. Delivery delay → review score → repeat purchase
Classified delivered orders as On Time or Late (actual vs. estimated delivery date), then measured the effect on review scores and on whether a customer's first order being late affected their odds of buying again — see [`analyze_delivery_impact.py`](analyze_delivery_impact.py) and [`analyze_delivery_deep_dive.py`](analyze_delivery_deep_dive.py).

### 3. Where lateness concentrates
Broke the late-delivery rate down by seller state and product category to find where the problem is concentrated, not just that it exists.

### 4. Delay-risk model
Built a logistic regression model (from scratch, NumPy) predicting delivery-delay risk using only information known at purchase time (promised delivery window, order value, item count, customer-seller distance, and each seller's historical late rate computed strictly from the training period) — see [`build_delay_forecast.py`](build_delay_forecast.py).

### 5. Excel workbook + Tableau dashboard
Exported the full order-level fact table ([`data/order_fact_table.csv`](data/order_fact_table.csv)) as the shared source for both an Excel workbook with live formulas ([`build_excel_workbook.py`](build_excel_workbook.py)) and a Tableau Public dashboard.

## Key Insights

**Late delivery has a large, measurable effect on review scores.** Average review score falls from 4.29 (on time) to 2.27 (late). 5-star reviews drop from 61.9% to 16.1%; 1-star reviews jump from 6.6% to 52.5%.

**That translates to an estimated 3,001 excess 1-star reviews** directly attributable to lateness — the gap between what the 1-star rate would be if late orders behaved like on-time orders, and what it actually is. R$1,150,866 in order value sits within those late-delivered orders.

**The repeat-purchase effect is real but small — and that's an honest finding, not a weak one.** Customers whose first order arrived late go on to buy again at 2.66% vs. 3.23% for on-time customers. The gap is small mainly because Olist's overall repeat-purchase rate is low across the board (~3%, a known characteristic of this dataset — most customers are one-time buyers regardless of delivery experience). The resulting revenue estimate (~R$5,829) is modest; the review-score effect is the stronger, more defensible finding.

**Lateness is not evenly distributed.** São Paulo (SP) sellers account for the largest absolute number of late orders (5,015) simply because they handle the most volume overall (7.3% late rate) — not because they're the worst offenders. Maranhão (MA) has the highest *rate* (19.1%) but a much smaller sample (388 orders). By category, Audio (11.9%) and Home Comfort (9.5%) run the highest late rates among categories with meaningful volume.

**A delay-risk model can meaningfully prioritize review, even though it isn't highly accurate overall.** Test-set AUC is 0.661 — a real signal, not a strong one. Reporting recall at a default 0.5 threshold would be misleading here since late deliveries are rare (~3.6% of the test period); instead, ranking orders by predicted risk shows that reviewing just the riskiest 20% of orders would catch 35.6% of all actual late deliveries, and the riskiest 30% would catch 51.0%.

## Business Recommendations

- **Treat late-delivery reduction primarily as a reputation/review problem, not a repeat-purchase problem** — the review-score effect is large and clear; the direct repeat-purchase revenue impact is real but modest given this dataset's overall low repeat-purchase rate.
- **Prioritize operational review of Maranhão (MA) sellers specifically** — the highest late rate by far (19.1%), even though the sample is smaller than SP.
- **Use the risk model to prioritize proactive intervention (e.g., upgraded shipping, earlier handoff to carrier) on the riskiest 20–30% of orders** rather than uniformly across all orders — this captures roughly a third to half of all late deliveries without reviewing every order.
- **Investigate Audio and Home Comfort category logistics specifically** — both show late rates well above the platform average among high-volume categories.

## Limitations

- Multi-seller and multi-item orders are simplified to their first listed seller/product for category and distance features — a small minority of orders involve more than one seller.
- The repeat-purchase analysis only tracks purchases within this dataset's window (Sep 2016–Oct 2018); a customer who returned after the data ends wouldn't be captured.
- The delay-risk model uses a small, hand-built feature set and a from-scratch logistic regression (no scikit-learn in the build environment) — a production model would likely include more features and a more sophisticated algorithm (e.g., gradient boosting).
- 551 orders had duplicate review submissions in the raw data; only the most recent review per order was kept.

## Future Improvements

- Deploy the Tableau dashboard publicly instead of requiring a local Tableau Public file
- Expand the risk model with more features (carrier, package weight/dimensions, holiday/seasonal flags) and compare against a gradient-boosted model
- Extend the repeat-purchase analysis with a longer post-purchase observation window
- Add a geospatial view of delay hotspots using the geolocation data already in the schema

## Project Structure

```
ecommerce-delivery-analytics/
│
├── data/                            # CSVs (raw Olist files not committed — see below; fact table + predictions included)
├── sql/
│   └── schema.sql
├── build_database.py                # loads the 9 real CSVs into SQLite
├── analyze_delivery_impact.py       # Q1: delay -> review score, delay -> repeat purchase
├── analyze_delivery_deep_dive.py    # excess negative reviews, where lateness concentrates
├── build_delay_forecast.py          # from-scratch logistic regression, time-based split
├── build_order_fact_table.py        # builds the shared order-level fact table
├── build_excel_workbook.py          # builds the live-formula Excel workbook
├── Ecommerce_Delivery_Analytics.xlsx
├── requirements.txt
└── README.md
```

## Reproducing / Running the Project

```bash
pip install -r requirements.txt

# 1. Download the real dataset from Kaggle and place the 9 CSVs in data/:
#    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

# 2. Build the SQLite database
python3 build_database.py

# 3. Run the analyses
python3 analyze_delivery_impact.py
python3 analyze_delivery_deep_dive.py
python3 build_delay_forecast.py

# 4. Build the shared fact table, then the Excel workbook
python3 build_order_fact_table.py
python3 build_excel_workbook.py
```

## Building the Tableau Dashboard

`data/order_fact_table.csv` is the source file — connect Tableau Public to it directly (Data > Connect to Data > Text File). See the accompanying step-by-step guide for the specific charts to build.

## Skills Demonstrated

- SQL (schema design, joins across 9 real-world tables, aggregate analysis)
- Python data analysis (pandas, NumPy) on a real, messy, non-synthetic dataset
- Statistical/causal-style reasoning (comparing groups, quantifying an "excess" effect vs. a baseline)
- Machine learning fundamentals built from scratch (logistic regression, gradient descent, manual metric implementation, leakage-aware time-based train/test splitting)
- Excel (live formulas: SUMIFS, COUNTIFS, AVERAGEIFS — not hardcoded values)
- Tableau Public (interactive dashboard)
- Business-focused insight writing and quantified, honestly-scoped recommendations
