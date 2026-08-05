from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dbt_generator import extract_identifiers, validate_sql_against_schema


DATASETS = [
    {
        "name": "stg_orders",
        "fields": [
            {"name": "order_id"},
            {"name": "customer_id"},
            {"name": "net_amount"},
        ],
    },
    {
        "name": "dim_customers",
        "fields": [
            {"name": "customer_id"},
            {"name": "is_active"},
            {"name": "lifetime_value"},
        ],
    },
]


def test_extract_identifiers_keeps_ref_arguments():
    _, refs = extract_identifiers("select * from {{ ref('stg_orders') }}")

    assert refs == {"stg_orders"}


def test_validate_rejects_unknown_ref():
    is_valid, warnings = validate_sql_against_schema(
        "select * from {{ ref('made_up_orders') }}",
        DATASETS,
        "bad_model",
    )

    assert not is_valid
    assert any("made_up_orders" in warning for warning in warnings)


def test_validate_rejects_unknown_qualified_column():
    is_valid, warnings = validate_sql_against_schema(
        """
        select
            o.order_id,
            o.fake_revenue
        from {{ ref('stg_orders') }} as o
        """,
        DATASETS,
        "bad_model",
    )

    assert not is_valid
    assert any("o.fake_revenue" in warning for warning in warnings)


def test_validate_accepts_known_refs_and_qualified_columns():
    is_valid, warnings = validate_sql_against_schema(
        """
        select
            o.order_id,
            c.customer_id,
            c.lifetime_value
        from {{ ref('stg_orders') }} as o
        join {{ ref('dim_customers') }} as c
          on o.customer_id = c.customer_id
        where c.is_active = true
        """,
        DATASETS,
        "customer_orders",
    )

    assert is_valid
    assert not [warning for warning in warnings if warning.startswith("Validation error")]
