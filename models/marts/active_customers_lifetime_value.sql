-- Full dbt SQL model content
SELECT customer_id, first_name, last_name, email_hash, signup_date, country, is_active, lifetime_value
FROM {{ ref('dim_customers') }}
WHERE is_active = TRUE