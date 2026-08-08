"""
Tests for datahub_writeback.py — pure payload builders + mock write-back.
No network calls needed; all I/O is handled by MockWriteBackClient.
"""
from pathlib import Path
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datahub_writeback import (
    build_model_urn,
    build_upstream_urns,
    build_write_back_payload,
    build_dataset_entity_json,
    build_lineage_json,
    MockWriteBackClient,
    WriteBackPayload,
)


# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

DATASETS = [
    {
        "name": "stg_orders",
        "platform": "dbt",
        "urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,stg_orders,PROD)",
        "fields": [
            {"name": "order_id", "isPrimaryKey": True, "tags": []},
            {"name": "customer_id", "isForeignKey": True, "tags": []},
            {"name": "net_amount", "tags": ["PII"]},
        ],
    },
    {
        "name": "dim_customers",
        "platform": "dbt",
        "urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,dim_customers,PROD)",
        "fields": [
            {"name": "customer_id", "isPrimaryKey": True, "tags": []},
            {"name": "lifetime_value", "tags": []},
        ],
    },
    {
        # Dataset with no pre-existing URN — URN must be derived from name
        "name": "raw_events",
        "platform": "bigquery",
        "fields": [],
    },
]


# ---------------------------------------------------------------------------
# URN builder tests
# ---------------------------------------------------------------------------

def test_build_model_urn_format():
    urn = build_model_urn("customer_orders")
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:dbt,customer_orders,PROD)"


def test_build_model_urn_sanitises_name():
    urn = build_model_urn("My-Model Name!")
    assert "urn:li:dataPlatform:dbt" in urn
    assert " " not in urn
    assert "-" not in urn
    assert "!" not in urn


def test_build_upstream_urns_prefers_existing_urn():
    urns = build_upstream_urns(DATASETS[:2])
    assert "urn:li:dataset:(urn:li:dataPlatform:dbt,stg_orders,PROD)" in urns
    assert "urn:li:dataset:(urn:li:dataPlatform:dbt,dim_customers,PROD)" in urns


def test_build_upstream_urns_derives_urn_when_missing():
    urns = build_upstream_urns([DATASETS[2]])
    assert len(urns) == 1
    assert "raw_events" in urns[0]
    assert urns[0].startswith("urn:li:dataset:")


# ---------------------------------------------------------------------------
# Payload builder tests
# ---------------------------------------------------------------------------

def test_build_write_back_payload_full():
    payload = build_write_back_payload(
        model_name="customer_orders",
        model_description="Joins orders with customers",
        datasets_used=DATASETS[:2],
        pr_url="https://github.com/org/repo/pull/42",
    )
    assert payload.model_urn == "urn:li:dataset:(urn:li:dataPlatform:dbt,customer_orders,PROD)"
    assert len(payload.upstream_urns) == 2
    assert payload.pr_url == "https://github.com/org/repo/pull/42"


def test_build_write_back_payload_no_datasets():
    payload = build_write_back_payload(
        model_name="empty_model",
        model_description="No upstream tables",
        datasets_used=[],
        pr_url="",
    )
    assert payload.upstream_urns == []


# ---------------------------------------------------------------------------
# Entity JSON builder tests
# ---------------------------------------------------------------------------

def test_build_dataset_entity_json_contains_urn():
    payload = build_write_back_payload(
        model_name="customer_orders",
        model_description="Test model",
        datasets_used=DATASETS[:2],
        pr_url="https://github.com/org/repo/pull/1",
    )
    entity = build_dataset_entity_json(payload)
    assert entity["urn"] == payload.model_urn
    assert entity["datasetProperties"]["value"]["customProperties"]["status"] == "PROPOSED"
    assert "https://github.com/org/repo/pull/1" in entity["datasetProperties"]["value"]["description"]


def test_build_dataset_entity_json_with_columns():
    columns = [
        {"name": "order_id", "description": "PK", "isPrimaryKey": True, "tags": []},
        {"name": "net_amount", "description": "Revenue", "isPrimaryKey": False, "tags": ["PII"]},
    ]
    payload = build_write_back_payload(
        model_name="revenue_model",
        model_description="Revenue rollup",
        datasets_used=[],
        columns=columns,
    )
    entity = build_dataset_entity_json(payload)
    schema_fields = entity["schemaMetadata"]["value"]["fields"]
    assert len(schema_fields) == 2
    field_names = [f["fieldPath"] for f in schema_fields]
    assert "order_id" in field_names
    assert "net_amount" in field_names


def test_build_dataset_entity_json_no_columns_omits_schema():
    payload = build_write_back_payload(
        model_name="no_col_model",
        model_description="No columns",
        datasets_used=[],
    )
    entity = build_dataset_entity_json(payload)
    assert "schemaMetadata" not in entity


# ---------------------------------------------------------------------------
# Lineage JSON builder tests
# ---------------------------------------------------------------------------

def test_build_lineage_json_returns_upstream_entries():
    payload = build_write_back_payload(
        model_name="customer_orders",
        model_description="Test",
        datasets_used=DATASETS[:2],
    )
    lineage = build_lineage_json(payload)
    assert lineage is not None
    upstreams = lineage["upstreamLineage"]["value"]["upstreams"]
    assert len(upstreams) == 2
    upstream_datasets = [u["dataset"] for u in upstreams]
    assert "urn:li:dataset:(urn:li:dataPlatform:dbt,stg_orders,PROD)" in upstream_datasets


def test_build_lineage_json_returns_none_when_no_upstream():
    payload = WriteBackPayload(
        model_urn="urn:li:dataset:(urn:li:dataPlatform:dbt,orphan_model,PROD)",
        model_name="orphan_model",
        model_description="No upstream",
        upstream_urns=[],
    )
    assert build_lineage_json(payload) is None


# ---------------------------------------------------------------------------
# Mock write-back round-trip tests
# ---------------------------------------------------------------------------

def test_mock_writeback_registers_entity():
    mock = MockWriteBackClient()
    payload = build_write_back_payload(
        model_name="customer_orders",
        model_description="Joins orders with customers",
        datasets_used=DATASETS[:2],
        pr_url="https://github.com/org/repo/pull/99",
    )
    result = asyncio.run(mock.write_back(payload))

    assert result["entity_upserted"] is True
    assert result["mock"] is True
    assert result["model_urn"] == payload.model_urn
    assert len(mock.registered_entities) == 1
    assert mock.registered_entities[0]["status"] == "PROPOSED"
    assert mock.registered_entities[0]["pr_url"] == "https://github.com/org/repo/pull/99"


def test_mock_writeback_writes_lineage_edges():
    mock = MockWriteBackClient()
    payload = build_write_back_payload(
        model_name="customer_orders",
        model_description="Test",
        datasets_used=DATASETS[:2],
    )
    result = asyncio.run(mock.write_back(payload))

    assert result["lineage_edges_written"] == 2
    assert len(mock.lineage_edges) == 2
    downstream_urns = {e["downstream"] for e in mock.lineage_edges}
    assert payload.model_urn in downstream_urns


def test_mock_writeback_no_upstream_writes_zero_edges():
    mock = MockWriteBackClient()
    payload = build_write_back_payload(
        model_name="standalone",
        model_description="No upstreams",
        datasets_used=[],
    )
    result = asyncio.run(mock.write_back(payload))

    assert result["lineage_edges_written"] == 0
    assert mock.lineage_edges == []
