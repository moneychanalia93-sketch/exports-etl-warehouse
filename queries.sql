-- Analytic queries on the star schema. Money is stored as whole cents,
-- so every query divides by 100.0 to show dollars.
-- Each query starts with a title line (name, then a colon). The command
-- `python -m etl queries` runs them all and prints a table for each.

-- name: 1. Revenue by destination country
SELECT c.country_name AS country,
       COUNT(*) AS orders,
       ROUND(SUM(o.amount_cents) / 100.0, 2) AS revenue_usd,
       ROUND(AVG(o.amount_cents) / 100.0, 2) AS avg_order_usd
FROM fact_orders o
JOIN dim_country c ON c.country_key = o.country_key
GROUP BY c.country_name
ORDER BY revenue_usd DESC;

-- name: 2. Revenue by month and country (USD, four biggest countries)
SELECT d.year_month AS month,
       ROUND(SUM(CASE WHEN c.country_code = 'US' THEN o.amount_cents ELSE 0 END) / 100.0, 2) AS US,
       ROUND(SUM(CASE WHEN c.country_code = 'GB' THEN o.amount_cents ELSE 0 END) / 100.0, 2) AS GB,
       ROUND(SUM(CASE WHEN c.country_code = 'DE' THEN o.amount_cents ELSE 0 END) / 100.0, 2) AS DE,
       ROUND(SUM(CASE WHEN c.country_code = 'IN' THEN o.amount_cents ELSE 0 END) / 100.0, 2) AS "IN",
       ROUND(SUM(CASE WHEN c.country_code NOT IN ('US', 'GB', 'DE', 'IN')
                      THEN o.amount_cents ELSE 0 END) / 100.0, 2) AS other
FROM fact_orders o
JOIN dim_date d ON d.date_key = o.order_date_key
JOIN dim_country c ON c.country_key = o.country_key
GROUP BY d.year_month
ORDER BY d.year_month;

-- name: 3. Top 10 sellers by revenue
SELECT s.seller_name AS seller,
       sc.country_code AS home,
       COUNT(*) AS orders,
       ROUND(SUM(o.amount_cents) / 100.0, 2) AS revenue_usd
FROM fact_orders o
JOIN dim_seller s ON s.seller_key = o.seller_key
JOIN dim_country sc ON sc.country_key = s.country_key
GROUP BY s.seller_key
ORDER BY revenue_usd DESC
LIMIT 10;

-- name: 4. Share of revenue by category
SELECT cat.category_name AS category,
       ROUND(SUM(o.amount_cents) / 100.0, 2) AS revenue_usd,
       ROUND(100.0 * SUM(o.amount_cents) / SUM(SUM(o.amount_cents)) OVER (), 1) AS share_pct
FROM fact_orders o
JOIN dim_category cat ON cat.category_key = o.category_key
GROUP BY cat.category_name
ORDER BY revenue_usd DESC;

-- name: 5. Monthly revenue and change from the month before
WITH monthly AS (
    SELECT d.year_month AS month, SUM(o.amount_cents) AS cents
    FROM fact_orders o
    JOIN dim_date d ON d.date_key = o.order_date_key
    GROUP BY d.year_month
)
SELECT month,
       ROUND(cents / 100.0, 2) AS revenue_usd,
       ROUND(100.0 * (cents - LAG(cents) OVER (ORDER BY month))
             / LAG(cents) OVER (ORDER BY month), 1) AS change_pct
FROM monthly
ORDER BY month;

-- name: 6. Late shipment rate by carrier (delivered shipments only)
SELECT carrier,
       COUNT(*) AS delivered,
       SUM(is_late) AS late,
       ROUND(100.0 * SUM(is_late) / COUNT(*), 1) AS late_pct
FROM fact_shipments
WHERE delivered_date_key IS NOT NULL
GROUP BY carrier
ORDER BY late_pct DESC;

-- name: 7. Late rate and average days in transit by destination country
SELECT c.country_name AS country,
       COUNT(*) AS delivered,
       ROUND(100.0 * SUM(s.is_late) / COUNT(*), 1) AS late_pct,
       ROUND(AVG(s.days_in_transit), 1) AS avg_days
FROM fact_shipments s
JOIN dim_country c ON c.country_key = s.country_key
WHERE s.delivered_date_key IS NOT NULL
GROUP BY c.country_name
ORDER BY late_pct DESC;

-- name: 8. Orders that have a shipment record, by month
SELECT d.year_month AS month,
       COUNT(*) AS orders,
       COUNT(s.shipment_key) AS with_shipment,
       ROUND(100.0 * COUNT(s.shipment_key) / COUNT(*), 1) AS shipment_pct
FROM fact_orders o
JOIN dim_date d ON d.date_key = o.order_date_key
LEFT JOIN fact_shipments s ON s.order_id = o.order_id
GROUP BY d.year_month
ORDER BY d.year_month;
