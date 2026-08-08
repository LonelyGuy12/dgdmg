"""
test_writeback.py - Standalone async tests for the DataHub write-back feature.

Run from the backend/ directory:
    python test_writeback.py

No pytest required - uses only the standard library asyncio runner.
"""
from __future__ import annotations

import asyncio
import sys
import os

# Ensure backend/ is on the path when running from any cwd
sys.path.insert(0, os.path.dirname(__file__))

# Force mock mode for all tests regardless of .env
os.environ["USE_MOCK_MCP"] = "true"


# -------------------------------------------------------------------
# Test helpers
# -------------------------------------------------------------------

_PASS = "\033[92mPASS\033[0m"
_FAIL = "\033[91mFAIL\033[0m"
_results: list = []


def _assert(condition: bool, label: str, detail: str = "") -> None:
    _results.append((label, condition, detail))
    icon = _PASS if condition else _FAIL
    print(f"  [{icon}] {label}" + (f"\n         {detail}" if detail and not condition else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


# -------------------------------------------------------------------
# Test 1 - Mock register_dataset
# -------------------------------------------------------------------

async def test_mock_register_dataset() -> None:
    print("\n[TEST 1] Mock register_dataset")
    from mock_mcp import MockMCPClient

    client = MockMCPClient()
    initial_count = len(await client.get_all_datasets())

    new_dataset = {
        "name":        "test_new_model",
        "platform":    "dbt",
        "schema":      "marts",
        "description": "A test model registered by the write-back step",
        "fields": [
            {"name": "id",    "type": "INTEGER", "description": "Primary key", "isPrimaryKey": True,  "isForeignKey": False, "tags": []},
            {"name": "value", "type": "DECIMAL", "description": "A metric",    "isPrimaryKey": False, "isForeignKey": False, "tags": []},
        ],
        "tags":       ["GENERATED", "GOLD"],
        "assertions": [],
    }

    result = await client.register_dataset(new_dataset)

    _assert(result["registered"] is True, "register_dataset returns registered=True")
    _assert("urn:li:dataPlatform:dbt" in result["urn"], "URN contains platform:dbt", f"urn={result['urn']}")
    _assert("test_new_model" in result["urn"], "URN contains model name", f"urn={result['urn']}")

    all_after = await client.get_all_datasets()
    names = [ds["name"] for ds in all_after]
    _assert("test_new_model" in names, "Dataset appears in get_all_datasets()")
    _assert(len(all_after) == initial_count + 1, "Dataset count increased by 1",
            f"before={initial_count}, after={len(all_after)}")

    registered_ds = next(ds for ds in all_after if ds["name"] == "test_new_model")
    _assert("GENERATED" in registered_ds["tags"], "GENERATED tag auto-applied", f"tags={registered_ds['tags']}")

    _assert(len(client._write_log) == 1, "Write log has 1 entry")
    _assert(client._write_log[0]["operation"] == "register_dataset", "Log entry has correct operation")

    print("  -> register_dataset OK")


# -------------------------------------------------------------------
# Test 2 - Mock add_lineage
# -------------------------------------------------------------------

async def test_mock_add_lineage() -> None:
    print("\n[TEST 2] Mock add_lineage")
    from mock_mcp import MockMCPClient

    client = MockMCPClient()

    await client.register_dataset({
        "name": "test_mart_model",
        "platform": "dbt",
        "description": "Target model",
        "fields": [],
        "tags": ["GENERATED"],
    })

    result = await client.add_lineage(
        upstream_name="stg_orders",
        downstream_name="test_mart_model",
        transformation_type="DBT_MODEL",
        transformation_query="SELECT * FROM {{ ref('stg_orders') }}",
    )

    _assert(result["added"] is True, "add_lineage returns added=True")
    _assert(result["duplicate"] is False, "First edge is not a duplicate")
    _assert("upstream" in result["edge"], "Edge dict has upstream key")
    _assert("stg_orders" in result["edge"]["upstream"], "Upstream URN contains stg_orders",
            f"upstream={result['edge']['upstream']}")
    _assert("test_mart_model" in result["edge"]["downstream"], "Downstream URN contains test_mart_model",
            f"downstream={result['edge']['downstream']}")

    lineage = await client.get_lineage("stg_orders", direction="DOWNSTREAM")
    downstream_names = [e["downstream"] for e in lineage.get("edges", [])]
    _assert(
        any("test_mart_model" in name for name in downstream_names),
        "Edge appears in downstream lineage of stg_orders",
        f"downstream_names={downstream_names}",
    )

    result2 = await client.add_lineage("stg_orders", "test_mart_model")
    _assert(result2["duplicate"] is True, "Second identical edge flagged as duplicate")

    print("  -> add_lineage OK")


# -------------------------------------------------------------------
# Test 3 - extract_source_tables helper
# -------------------------------------------------------------------

async def test_extract_source_tables() -> None:
    print("\n[TEST 3] extract_source_tables()")
    from dbt_generator import extract_source_tables

    sql_ref_only = """
    SELECT o.order_id, c.customer_id
    FROM {{ ref('stg_orders') }} o
    LEFT JOIN {{ ref('stg_customers') }} c ON o.customer_id = c.customer_id
    """
    tables = extract_source_tables(sql_ref_only)
    _assert("stg_orders" in tables, "ref stg_orders extracted", f"tables={tables}")
    _assert("stg_customers" in tables, "ref stg_customers extracted", f"tables={tables}")
    _assert(len(tables) == len(set(tables)), "No duplicates in result")

    sql_source_only = """
    SELECT * FROM {{ source('raw', 'raw_orders') }}
    LEFT JOIN {{ source('raw', 'raw_customers') }} USING (customer_id)
    """
    tables2 = extract_source_tables(sql_source_only)
    _assert("raw_orders" in tables2, "source raw_orders extracted", f"tables2={tables2}")
    _assert("raw_customers" in tables2, "source raw_customers extracted", f"tables2={tables2}")

    sql_mixed = """
    WITH staged AS (SELECT * FROM {{ ref('stg_orders') }})
    SELECT * FROM staged
    LEFT JOIN {{ source('raw', 'raw_products') }} p ON staged.product_id = p.product_id
    """
    tables3 = extract_source_tables(sql_mixed)
    _assert("stg_orders" in tables3, "Mixed SQL: ref extracted", f"tables3={tables3}")
    _assert("raw_products" in tables3, "Mixed SQL: source extracted", f"tables3={tables3}")

    empty_tables = extract_source_tables("SELECT 1")
    _assert(isinstance(empty_tables, list), "Empty SQL returns a list")

    print("  -> extract_source_tables OK")


# -------------------------------------------------------------------
# Test 4 - Full mock write-back end-to-end via DataHubMCPClient
# -------------------------------------------------------------------

async def test_full_writeback_mock() -> None:
    print("\n[TEST 4] Full mock write-back (end-to-end via DataHubMCPClient)")
    from datahub_mcp import DataHubMCPClient
    from dbt_generator import extract_source_tables

    mcp = DataHubMCPClient()

    sql = """
    SELECT o.order_id, c.customer_id, p.category, o.net_amount
    FROM {{ ref('stg_orders') }} o
    LEFT JOIN {{ ref('stg_customers') }} c ON o.customer_id = c.customer_id
    LEFT JOIN {{ source('raw', 'raw_products') }} p ON o.product_id = p.product_id
    """

    model_name = "test_e2e_mart"

    reg = await mcp.register_dataset({
        "name":        model_name,
        "platform":    "dbt",
        "schema":      "marts",
        "description": "End-to-end test mart",
        "fields": [
            {"name": "order_id",    "type": "INTEGER", "description": "PK",       "isPrimaryKey": True,  "isForeignKey": False, "tags": []},
            {"name": "customer_id", "type": "INTEGER", "description": "FK",       "isPrimaryKey": False, "isForeignKey": True,  "fkTable": "dim_customers", "fkColumn": "customer_id", "tags": []},
            {"name": "category",    "type": "VARCHAR", "description": "Category", "isPrimaryKey": False, "isForeignKey": False, "tags": []},
            {"name": "net_amount",  "type": "DECIMAL", "description": "Net rev",  "isPrimaryKey": False, "isForeignKey": False, "tags": []},
        ],
        "tags":       ["GENERATED", "GOLD"],
        "assertions": [],
    })

    _assert(reg["registered"] is True, "E2E: dataset registered via DataHubMCPClient")
    _assert(model_name in reg["urn"], "E2E: URN contains model name")

    all_ds = await mcp.get_all_datasets()
    _assert(any(ds["name"] == model_name for ds in all_ds), "E2E: model in catalog")

    sources = extract_source_tables(sql)
    _assert(len(sources) >= 2, f"E2E: at least 2 source tables extracted (got {len(sources)})",
            f"sources={sources}")

    edges_added = []
    for src in sources:
        result = await mcp.add_lineage(
            upstream_name=src,
            downstream_name=model_name,
            transformation_type="DBT_MODEL",
            transformation_query=sql[:4000],
        )
        edges_added.append(result)

    _assert(
        all(r["added"] or r.get("duplicate") for r in edges_added),
        "E2E: all lineage edges accepted",
        f"edges={edges_added}",
    )

    new_model_lineage = await mcp.get_lineage(model_name, direction="UPSTREAM")
    upstream_edges = new_model_lineage.get("edges", [])
    _assert(len(upstream_edges) >= 1, "E2E: new model has upstream lineage edges",
            f"edges={upstream_edges}")

    await mcp.close()
    print("  -> Full write-back OK")


# -------------------------------------------------------------------
# Runner
# -------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  DataHub Write-Back Test Suite")
    print("=" * 60)

    tests = [
        ("test_mock_register_dataset", test_mock_register_dataset),
        ("test_mock_add_lineage",      test_mock_add_lineage),
        ("test_extract_source_tables", test_extract_source_tables),
        ("test_full_writeback_mock",   test_full_writeback_mock),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            await fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  [ERROR] {name}: {e}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
