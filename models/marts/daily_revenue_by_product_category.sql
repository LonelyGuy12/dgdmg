-- Full dbt SQL model content
SELECT
  DATE(fct_orders.order_date) AS order_date,
  raw_products.category AS product_category,
  SUM(fct_orders.net_amount) AS daily_revenue
FROM {{ ref('fct_orders') }}
JOIN {{ source('raw', 'raw_products') }} ON fct_orders.product_id = raw_products.product_id
WHERE fct_orders.is_active_order = TRUE
GROUP BY 1, 2