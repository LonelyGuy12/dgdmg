"""
mock_mcp.py — Rich mock DataHub MCP responses
Loads data from mock-data/ JSON files to simulate a real DataHub catalog.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

MOCK_DIR = Path(__file__).parent.parent / "mock-data"


def _load(filename: str) -> Any:
    with open(MOCK_DIR / filename) as f:
        return json.load(f)


class MockMCPClient:
    """Mimics the DataHub MCP tool surface used by the agent."""

    def __init__(self):
        self._datasets: dict[str, dict] = {}
        self._glossary: list[dict] = []
        self._lineage: dict

        raw = _load("datasets.json")
        for ds in raw["datasets"]:
            self._datasets[ds["name"]] = ds
        self._glossary = _load("glossary.json")["glossary_terms"]
        self._lineage = _load("lineage.json")

    # ─────────────────────────────────────────────────────────────────────
    # search — keyword-based entity search
    # ─────────────────────────────────────────────────────────────────────
    async def search(self, query: str, entity_type: str = "DATASET", limit: int = 10) -> list[dict]:
        query_lower = query.lower()

        if entity_type == "GLOSSARY_TERM":
            hits = []
            for term in self._glossary:
                score = 0
                name_lower = term["name"].lower()
                urn_lower = term["urn"].lower()
                for word in query_lower.split():
                    if word in name_lower or word in urn_lower or word in term["definition"].lower():
                        score += 1
                if score > 0:
                    hits.append({"score": score, **term})
            hits.sort(key=lambda x: x["score"], reverse=True)
            return hits[:limit]

        # Dataset search — match by name, description, tags
        hits = []
        for name, ds in self._datasets.items():
            score = 0
            searchable = (
                name.lower()
                + " "
                + ds.get("description", "").lower()
                + " "
                + " ".join(ds.get("tags", [])).lower()
            )
            for word in query_lower.split():
                if word in searchable:
                    score += 2 if word in name.lower() else 1
            if score > 0:
                hits.append({"score": score, **ds})
        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:limit]

    # ─────────────────────────────────────────────────────────────────────
    # get_entities — fetch full metadata by URN or name
    # ─────────────────────────────────────────────────────────────────────
    async def get_entities(self, urns: list[str]) -> list[dict]:
        results = []
        for urn in urns:
            # Try by URN first, then by name extracted from URN
            matched = None
            for name, ds in self._datasets.items():
                if ds["urn"] == urn or name in urn:
                    matched = ds
                    break
            if matched:
                results.append(matched)
        return results

    # ─────────────────────────────────────────────────────────────────────
    # list_schema_fields — return schema for a dataset
    # ─────────────────────────────────────────────────────────────────────
    async def list_schema_fields(self, dataset_name: str) -> list[dict]:
        ds = self._datasets.get(dataset_name)
        if not ds:
            # Try fuzzy match
            for name, data in self._datasets.items():
                if dataset_name.lower() in name.lower():
                    ds = data
                    break
        if not ds:
            return []
        return ds.get("fields", [])

    # ─────────────────────────────────────────────────────────────────────
    # get_lineage — upstream/downstream lineage for a dataset
    # ─────────────────────────────────────────────────────────────────────
    async def get_lineage(
        self, dataset_name: str, direction: str = "UPSTREAM"
    ) -> dict:
        edges = self._lineage["lineage_edges"]
        column_lineage = self._lineage["column_lineage"]

        related = []
        for edge in edges:
            if direction == "UPSTREAM":
                if dataset_name in edge["downstream"]:
                    related.append(edge)
            else:
                if dataset_name in edge["upstream"]:
                    related.append(edge)

        col_related = [
            cl for cl in column_lineage
            if dataset_name in (cl["upstreamDataset"] if direction == "DOWNSTREAM" else cl["downstreamDataset"])
        ]

        return {
            "dataset": dataset_name,
            "direction": direction,
            "edges": related,
            "column_lineage": col_related,
        }

    # ─────────────────────────────────────────────────────────────────────
    # get_glossary_term — resolve a specific term
    # ─────────────────────────────────────────────────────────────────────
    async def get_glossary_term(self, term_name: str) -> dict | None:
        term_lower = term_name.lower().replace(" ", "_")
        for term in self._glossary:
            if (
                term_lower in term["urn"].lower()
                or term_lower in term["name"].lower().replace(" ", "_")
            ):
                return term
        return None

    # ─────────────────────────────────────────────────────────────────────
    # get_all_datasets — list all datasets (for agent context)
    # ─────────────────────────────────────────────────────────────────────
    async def get_all_datasets(self) -> list[dict]:
        return list(self._datasets.values())

    # ─────────────────────────────────────────────────────────────────────
    # get_pii_columns — return all columns flagged PII across all datasets
    # ─────────────────────────────────────────────────────────────────────
    async def get_pii_columns(self) -> list[dict]:
        pii = []
        for name, ds in self._datasets.items():
            for field in ds.get("fields", []):
                if any(t in ("PII", "SENSITIVE") for t in field.get("tags", [])):
                    pii.append({"dataset": name, "column": field["name"], "tags": field["tags"]})
        return pii
