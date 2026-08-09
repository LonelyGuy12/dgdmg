"""
datahub_mcp.py — DataHub MCP client
Routes to real DataHub MCP server or mock based on USE_MOCK_MCP env var.
"""
from __future__ import annotations
import os
import json
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

USE_MOCK = os.getenv("USE_MOCK_MCP", "true").lower() == "true"
DATAHUB_MCP_URL = os.getenv("DATAHUB_MCP_URL", "")
DATAHUB_TOKEN = os.getenv("DATAHUB_TOKEN", "")

# Tool names used for write-back; override if your DataHub MCP server differs.
DATAHUB_WRITE_DATASET_TOOL = os.getenv("DATAHUB_WRITE_DATASET_TOOL", "upsert_dataset_v2")
DATAHUB_WRITE_LINEAGE_TOOL = os.getenv("DATAHUB_WRITE_LINEAGE_TOOL", "upsert_lineage")


def _build_dataset_urn(platform: str, name: str, env: str = "PROD") -> str:
    """Build a DataHub-style dataset URN."""
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},{env})"


class DataHubMCPClient:
    """
    Wraps the DataHub MCP HTTP server.
    Falls back to MockMCPClient when USE_MOCK_MCP=true.
    """

    def __init__(self):
        if USE_MOCK:
            from mock_mcp import MockMCPClient
            self._client = MockMCPClient()
            self._is_mock = True
        else:
            self._is_mock = False
            self._http = httpx.AsyncClient(
                base_url=DATAHUB_MCP_URL,
                headers={
                    "Authorization": f"Bearer {DATAHUB_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

    async def _call_tool(self, tool_name: str, params: dict) -> Any:
        """Call a DataHub MCP tool via HTTP POST."""
        response = await self._http.post(
            "/tools/call",
            json={"name": tool_name, "arguments": params},
        )
        response.raise_for_status()
        data = response.json()
        # MCP response format: {"content": [{"type": "text", "text": "..."}]}
        if data.get("content"):
            text = data["content"][0].get("text", "{}")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return data

    async def search(self, query: str, entity_type: str = "DATASET", limit: int = 10) -> list[dict]:
        if self._is_mock:
            return await self._client.search(query, entity_type, limit)
        result = await self._call_tool("search", {
            "query": query,
            "filters": [{"field": "entityType", "values": [entity_type]}],
            "count": limit,
        })
        return result.get("searchResults", [])

    async def get_entities(self, urns: list[str]) -> list[dict]:
        if self._is_mock:
            return await self._client.get_entities(urns)
        result = await self._call_tool("get_entities", {"urns": urns})
        return result if isinstance(result, list) else [result]

    async def list_schema_fields(self, dataset_name: str) -> list[dict]:
        if self._is_mock:
            return await self._client.list_schema_fields(dataset_name)
        result = await self._call_tool("list_schema_fields", {
            "urn": f"urn:li:dataset:(urn:li:dataPlatform:dbt,{dataset_name},PROD)"
        })
        return result.get("schemaFields", [])

    async def get_lineage(self, dataset_name: str, direction: str = "UPSTREAM") -> dict:
        if self._is_mock:
            return await self._client.get_lineage(dataset_name, direction)
        result = await self._call_tool("get_lineage", {
            "urn": f"urn:li:dataset:(urn:li:dataPlatform:dbt,{dataset_name},PROD)",
            "direction": direction,
            "count": 20,
        })
        return result

    async def search_glossary(self, term: str) -> list[dict]:
        if self._is_mock:
            return await self._client.search(term, entity_type="GLOSSARY_TERM")
        result = await self._call_tool("search", {
            "query": term,
            "filters": [{"field": "entityType", "values": ["GLOSSARY_TERM"]}],
        })
        return result.get("searchResults", [])

    async def get_all_datasets(self) -> list[dict]:
        if self._is_mock:
            return await self._client.get_all_datasets()
        # Real DataHub: search with wildcard
        result = await self.search("*", entity_type="DATASET", limit=50)
        return result

    async def get_pii_columns(self) -> list[dict]:
        if self._is_mock:
            return await self._client.get_pii_columns()
        result = await self.search("tag:PII", entity_type="DATASET", limit=50)
        return result

    # ─────────────────────────────────────────────────────────────────────
    # register_dataset — write a generated model back into DataHub
    # ─────────────────────────────────────────────────────────────────────
    async def register_dataset(self, dataset: dict) -> dict:
        """
        Register (upsert) a dataset in DataHub.

        In mock mode: mutates the in-memory MockMCPClient catalog.
        In real mode: calls the DataHub MCP write tool (DATAHUB_WRITE_DATASET_TOOL).

        Args:
            dataset: dict with at minimum keys:
                name, platform, schema, description, fields, tags

        Returns:
            {"registered": True, "urn": <urn>, "name": <name>}
        """
        if self._is_mock:
            return await self._client.register_dataset(dataset)

        # Real DataHub path — build the MCP upsert payload
        name = dataset["name"]
        platform = dataset.get("platform", "dbt")
        urn = dataset.get("urn") or _build_dataset_urn(platform, name)

        schema_fields = [
            {
                "fieldPath": f["name"],
                "type": {"type": {"com.linkedin.schema.StringType": {}}},
                "nativeDataType": f.get("type", "VARCHAR"),
                "description": f.get("description", ""),
                "tags": {"tags": [{"tag": f"urn:li:tag:{t}"} for t in f.get("tags", [])]},
            }
            for f in dataset.get("fields", [])
        ]

        payload = {
            "urn": urn,
            "aspects": {
                "datasetProperties": {
                    "name": name,
                    "description": dataset.get("description", ""),
                    "customProperties": {"generated_by": "dbt-generator"},
                },
                "schemaMetadata": {
                    "schemaName": name,
                    "platform": f"urn:li:dataPlatform:{platform}",
                    "version": 0,
                    "fields": schema_fields,
                    "hash": "",
                    "platformSchema": {"com.linkedin.schema.OtherSchema": {"rawSchema": ""}},
                },
                "globalTags": {
                    "tags": [
                        {"tag": f"urn:li:tag:{t}"}
                        for t in list(set(dataset.get("tags", []) + ["GENERATED"]))
                    ]
                },
            },
        }
        result = await self._call_tool(DATAHUB_WRITE_DATASET_TOOL, payload)
        return {"registered": True, "urn": urn, "name": name, "raw": result}

    # ─────────────────────────────────────────────────────────────────────
    # add_lineage — write upstream lineage edges into DataHub
    # ─────────────────────────────────────────────────────────────────────
    async def add_lineage(
        self,
        upstream_name: str,
        downstream_name: str,
        transformation_type: str = "DBT_MODEL",
        transformation_query: str = "",
    ) -> dict:
        """
        Add a lineage edge from upstream_name → downstream_name in DataHub.

        In mock mode: mutates the in-memory MockMCPClient lineage graph.
        In real mode: calls the DataHub MCP write tool (DATAHUB_WRITE_LINEAGE_TOOL).

        Returns:
            {"added": True/False, "edge": {upstream, downstream, ...}}
        """
        if self._is_mock:
            return await self._client.add_lineage(
                upstream_name, downstream_name, transformation_type, transformation_query
            )

        # Real DataHub path — build a DataHub lineage aspect payload
        upstream_urn   = _build_dataset_urn("dbt", upstream_name)
        downstream_urn = _build_dataset_urn("dbt", downstream_name)

        payload = {
            "urn": downstream_urn,
            "aspects": {
                "upstreamLineage": {
                    "upstreams": [
                        {
                            "dataset": upstream_urn,
                            "type": transformation_type,
                            "query": transformation_query[:4000],  # DataHub field limit
                        }
                    ]
                }
            },
        }
        result = await self._call_tool(DATAHUB_WRITE_LINEAGE_TOOL, payload)
        return {
            "added": True,
            "duplicate": False,
            "edge": {
                "upstream": upstream_urn,
                "downstream": downstream_urn,
                "transformationType": transformation_type,
            },
            "raw": result,
        }

    async def close(self):
        if not self._is_mock:
            await self._http.aclose()
