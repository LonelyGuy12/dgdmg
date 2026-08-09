-- Full dbt SQL model content
SELECT
  {{ source('raw', 'raw_products').category }} AS product_category,
  DATE({{ ref('fct_orders').order_date }}) AS order_date,
  SUM({{ ref('fct_orders').net_amount }}) AS daily_revenue
FROM
  {{ ref('fct_orders') }}
  INNER JOIN {{ source('raw', 'raw_products') }} ON {{ ref('fct_orders').product_id }} = {{ source('raw', 'raw_products').product_id }}
WHERE
  {{ ref('fct_orders').is_active_order }} = TRUE
GROUP BY
  {{ source('raw', 'raw_products').category }},
  DATE({{ ref('fct_orders').order_date }})