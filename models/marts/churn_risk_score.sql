-- Full dbt SQL model content
SELECT 
  dc.customer_id, 
  dc.is_active, 
  dc.last_order_date, 
  CASE 
    WHEN dc.last_order_date < DATEADD(day, -60, CURRENT_DATE) THEN 'High Risk' 
    WHEN dc.last_order_date < DATEADD(day, -90, CURRENT_DATE) THEN 'Medium Risk' 
    ELSE 'Low Risk' 
  END AS churn_risk_score 
FROM 
  {{ ref('dim_customers') }} dc