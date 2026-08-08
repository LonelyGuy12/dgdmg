"""
datahub_writeback.py — DataHub metadata write-back after dbt model generation.

After a model is generated and validated, this module:
  1. Registers the new dbt model as a Dataset entity in DataHub (status: PROPOSED).
  2. Adds upstream table-level lineage from the datasets used in the model.
  3. Attaches the GitHub PR URL to the entity's editableProperties.

Supports both the real DataHub REST API and mock mode (USE_MOCK_MCP=true).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

USE_MOCK = os.getenv("USE_MOCK_MCP", "true").lower() == "true"
DATAHUB_MCP_URL = os.getenv("DATAHUB_MCP_URL", "")
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")
# Acryl Cloud exposes the ingestion REST endpoint here:
DATAHUB_REST_URL = os.getenv("DATAHUB_REST_URL", DATAHUB_MCP_URL.replace("/api/mcp", ""))

DBT_PLATFORM = "dbt"
ENV = "PROD"


# ---------------------------------------------------------------------------
# Payload builders (pure, testable, no I/O)
# ---------------------------------------------------------------------------

@dataclass
class WriteBackPayload:
    """Structured description of what will be written back to DataHub."""
    model_urn: str
    model_name: str
    model_description: str
    upstream_urns: list[str] = field(default_factory=list)
    pr_url: str = ""
    columns: list[dict] = field(default_factory=list)


def build_model_urn(model_name: str, platform: str = DBT_PLATFORM, env: str = ENV) -> str:
    """Build a DataHub Dataset URN for a generated dbt model."""
    clean = re.sub(r"[^a-z0-9_]", "", model_name.lower())
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{clean},{env})"


def build_upstream_urns(datasets: list[dict]) -> list[str]:
    """Build upstream DataHub URNs from the DataHub datasets used in the model."""
    urns = []
    for ds in datasets:
        existing_urn = ds.get("urn", "")
        if existing_urn and existing_urn.startswith("urn:li:dataset:"):
            urns.append(existing_urn)
        else:
            platform = ds.get("platform", "dbt")
            name = ds.get("name", "")
            if name:
                urns.append(f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},{ENV})")
    return urns


def build_write_back_payload(
    model_name: str,
    model_description: str,
    datasets_used: list[dict],
    pr_url: str = "",
    columns: list[dict] | None = None,
) -> WriteBackPayload:
    """Assemble a WriteBackPayload from generation outputs."""
    model_urn = build_model_urn(model_name)
    upstream_urns = build_upstream_urns(datasets_used)
    return WriteBackPayload(
        model_urn=model_urn,
        model_name=model_name,
        model_description=model_description,
        upstream_urns=upstream_urns,
        pr_url=pr_url,
        columns=columns or [],
    )


def build_dataset_entity_json(payload: WriteBackPayload) -> dict:
    """
    Build the DataHub REST ingest JSON for the new Dataset entity.
    Compatible with DataHub's /openapi/v3/entity/dataset endpoint.
    """
    schema_fields = []
    for col in payload.columns:
        schema_fields.append({
            "fieldPath": col.get("name", ""),
            "type": {
                "type": {"com.linkedin.schema.StringType": {}}
            },
            "nativeDataType": "VARCHAR",
            "description": col.get("description", ""),
            "isPartOfKey": col.get("isPrimaryKey", False),
            "globalTags": {
                "tags": [
                    {"tag": f"urn:li:tag:{t}"}
                    for t in col.get("tags", [])
                ]
            },
        })

    description = payload.model_description
    if payload.pr_url:
        description += f"\n\n**Generated PR**: {payload.pr_url}"

    entity: dict[str, Any] = {
        "urn": payload.model_urn,
        "datasetProperties": {
            "value": {
                "name": payload.model_name,
                "description": description,
                "customProperties": {
                    "generator": "datahub-dbt-model-generator",
                    "status": "PROPOSED",
                    "pr_url": payload.pr_url,
                },
            }
        },
        "status": {
            "value": {
                "removed": False,
            }
        },
        "datasetKey": {
            "value": {
                "platform": f"urn:li:dataPlatform:{DBT_PLATFORM}",
                "name": payload.model_name,
                "origin": ENV,
            }
        },
    }

    if schema_fields:
        entity["schemaMetadata"] = {
            "value": {
                "schemaName": payload.model_name,
                "platform": f"urn:li:dataPlatform:{DBT_PLATFORM}",
                "version": 0,
                "hash": "",
                "platformSchema": {
                    "com.linkedin.schema.OtherSchema": {
                        "rawSchema": f"-- Generated dbt model: {payload.model_name}"
                    }
                },
                "fields": schema_fields,
            }
        }

    return entity


def build_lineage_json(payload: WriteBackPayload) -> dict | None:
    """
    Build the DataHub REST ingest JSON for upstream lineage.
    Compatible with DataHub's /openapi/v3/entity/dataset endpoint.
    """
    if not payload.upstream_urns:
        return None

    upstreams = [
        {"dataset": upstream_urn, "type": "TRANSFORMED"}
        for upstream_urn in payload.upstream_urns
    ]

    return {
        "urn": payload.model_urn,
        "upstreamLineage": {
            "value": {
                "upstreams": upstreams,
            }
        },
    }


# ---------------------------------------------------------------------------
# Write-back executor
# ---------------------------------------------------------------------------

class DataHubWriteBackClient:
    """
    Writes generated model metadata back to DataHub.
    Falls back to MockWriteBackClient when USE_MOCK_MCP=true.
    """

    def __init__(self):
        if USE_MOCK:
            self._client: Any = MockWriteBackClient()
            self._is_mock = True
        else:
            self._is_mock = False
            if not DATAHUB_REST_URL:
                raise ValueError(
                    "DATAHUB_REST_URL (or DATAHUB_MCP_URL) must be set for DataHub write-back. "
                    "Set USE_MOCK_MCP=true to use mock mode."
                )
            self._http = httpx.AsyncClient(
                base_url=DATAHUB_REST_URL,
                headers={
                    "Authorization": f"Bearer {DATAHUB_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

    async def write_back(self, payload: WriteBackPayload) -> dict:
        """
        Upsert the model entity + lineage into DataHub.
        Returns a summary dict with the entity URN and lineage edge count.
        """
        if self._is_mock:
            return await self._client.write_back(payload)

        results: dict[str, Any] = {
            "model_urn": payload.model_urn,
            "entity_upserted": False,
            "lineage_edges_written": 0,
            "errors": [],
        }

        # 1. Upsert the dataset entity
        entity_json = build_dataset_entity_json(payload)
        try:
            resp = await self._http.post(
                "/openapi/v3/entity/dataset",
                json=[entity_json],
                params={"async": "false"},
            )
            resp.raise_for_status()
            results["entity_upserted"] = True
        except Exception as exc:
            results["errors"].append(f"Entity upsert failed: {exc}")

        # 2. Write upstream lineage
        lineage_json = build_lineage_json(payload)
        if lineage_json:
            try:
                resp = await self._http.post(
                    "/openapi/v3/entity/dataset",
                    json=[lineage_json],
                    params={"async": "false"},
                )
                resp.raise_for_status()
                results["lineage_edges_written"] = len(payload.upstream_urns)
            except Exception as exc:
                results["errors"].append(f"Lineage write failed: {exc}")

        return results

    async def close(self):
        if not self._is_mock:
            await self._http.aclose()


class MockWriteBackClient:
    """
    In-memory mock write-back that simulates DataHub write-back for demo/testing.
    Stores registered entities and lineage so they can be inspected in tests.
    """

    def __init__(self):
        self.registered_entities: list[dict] = []
        self.lineage_edges: list[dict] = []

    async def write_back(self, payload: WriteBackPayload) -> dict:
        entity_record = {
            "urn": payload.model_urn,
            "name": payload.model_name,
            "description": payload.model_description,
            "status": "PROPOSED",
            "pr_url": payload.pr_url,
            "columns": payload.columns,
        }
        self.registered_entities.append(entity_record)

        for upstream_urn in payload.upstream_urns:
            self.lineage_edges.append({
                "upstream": upstream_urn,
                "downstream": payload.model_urn,
                "type": "TRANSFORMED",
            })

        return {
            "model_urn": payload.model_urn,
            "entity_upserted": True,
            "lineage_edges_written": len(payload.upstream_urns),
            "errors": [],
            "mock": True,
        }
