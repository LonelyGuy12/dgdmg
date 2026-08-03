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

    async def close(self):
        if not self._is_mock:
            await self._http.aclose()
