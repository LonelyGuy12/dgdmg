-- Full dbt SQL model content
SELECT 
  c.customer_id, 
  c.first_name, 
  c.last_name, 
  c.email_hash, 
  c.signup_date, 
  c.country, 
  c.is_active, 
  o.order_id, 
  o.order_date, 
  o.status, 
  o.net_amount, 
  CASE 
    WHEN c.signup_date < (CURRENT_DATE - INTERVAL '90 days') AND c.is_active = FALSE THEN 'stale' 
    ELSE 'active' 
  END AS data_status 
FROM {{ ref('stg_customers') }} c 
LEFT JOIN {{ ref('stg_orders') }} o 
ON c.customer_id = o.customer_id