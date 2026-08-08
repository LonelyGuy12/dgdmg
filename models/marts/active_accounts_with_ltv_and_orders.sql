-- Full dbt SQL model content
SELECT 
  o.order_id,
  o.customer_id,
  o.order_date,
  o.net_amount,
  c.lifetime_value
FROM {{ ref('stg_orders') }} o
INNER JOIN {{ ref('dim_customers') }} c
ON o.customer_id = c.customer_id
WHERE c.is_active = TRUE