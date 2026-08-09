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
    with open(MOCK_DIR / filename, encoding="utf-8") as f:
        return json.load(f)



def _save(filename: str, data: Any) -> None:
    """Write *data* back to mock-data/<filename> as pretty-printed JSON.

    Uses the same MOCK_DIR anchor (relative to this file, not cwd) so the
    correct path is always found regardless of where the server is started.
    Non-fatal: logs a warning on failure instead of raising.
    """
    import logging
    path = MOCK_DIR / filename
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")  # trailing newline for clean diffs
    except Exception as exc:
        logging.warning("mock_mcp: could not persist %s to disk: %s", filename, exc)


def _build_urn(platform: str, name: str, env: str = "PROD") -> str:
    """Build a DataHub-style dataset URN from platform and name."""
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},{env})"


class MockMCPClient:
    """Mimics the DataHub MCP tool surface used by the agent."""

    def __init__(self):
        self._datasets: dict[str, dict] = {}
        self._glossary: list[dict] = []
        self._lineage: dict
        # Records every write operation so tests/callers can inspect side-effects.
        self._write_log: list[dict] = []

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

    # ─────────────────────────────────────────────────────────────────────
    # register_dataset — write a new dataset into the mock catalog
    # ─────────────────────────────────────────────────────────────────────
    async def register_dataset(self, dataset: dict) -> dict:
        """
        Upsert a dataset into the in-memory mock catalog.

        Expected keys in `dataset`:
            name          (str)  — model name, e.g. "my_new_model"
            platform      (str)  — e.g. "dbt"  [default: "dbt"]
            schema        (str)  — e.g. "marts" [default: "marts"]
            description   (str)  — human-readable description
            fields        (list) — list of field dicts {name, type, description, ...}
            tags          (list) — e.g. ["GENERATED", "GOLD"]
            assertions    (list) — optional dbt test assertions [default: []]

        Returns:
            {"registered": True, "urn": <urn>, "name": <name>}
        """
        name = dataset["name"]
        platform = dataset.get("platform", "dbt")
        urn = dataset.get("urn") or _build_urn(platform, name)

        record = {
            "urn":         urn,
            "name":        name,
            "platform":    platform,
            "schema":      dataset.get("schema", "marts"),
            "description": dataset.get("description", ""),
            "freshness":   dataset.get("freshness", "healthy"),
            "fields":      dataset.get("fields", []),
            "tags":        list(set(dataset.get("tags", []) + ["GENERATED"])),
            "assertions":  dataset.get("assertions", []),
        }
        self._datasets[name] = record

        # Persist the updated catalog to disk so registrations survive restarts.
        _save("datasets.json", {"datasets": list(self._datasets.values())})

        result = {"registered": True, "urn": urn, "name": name}
        self._write_log.append({"operation": "register_dataset", **result})
        return result

    # ─────────────────────────────────────────────────────────────────────
    # add_lineage — write a new lineage edge into the mock lineage graph
    # ─────────────────────────────────────────────────────────────────────
    async def add_lineage(
        self,
        upstream_name: str,
        downstream_name: str,
        transformation_type: str = "DBT_MODEL",
        transformation_query: str = "",
    ) -> dict:
        """
        Append a new lineage edge to the in-memory lineage graph.

        Resolves URNs from the in-memory catalog when available; falls back to
        constructing a dbt-platform URN so the edge is always valid.

        Returns:
            {"added": True, "edge": {upstream, downstream, transformationType, ...}}
        """
        def _resolve_urn(name: str) -> str:
            ds = self._datasets.get(name)
            if ds:
                return ds["urn"]
            return _build_urn("dbt", name)

        upstream_urn   = _resolve_urn(upstream_name)
        downstream_urn = _resolve_urn(downstream_name)

        edge = {
            "upstream":               upstream_urn,
            "downstream":             downstream_urn,
            "transformationType":     transformation_type,
            "transformationQuery":    transformation_query,
        }

        # Avoid duplicate edges
        existing = self._lineage.setdefault("lineage_edges", [])
        duplicate = any(
            e["upstream"] == upstream_urn and e["downstream"] == downstream_urn
            for e in existing
        )
        if not duplicate:
            existing.append(edge)
            # Persist the updated lineage graph to disk (skip if duplicate —
            # nothing changed so no need to rewrite the file).
            _save("lineage.json", {
                "lineage_edges": self._lineage.get("lineage_edges", []),
                "column_lineage": self._lineage.get("column_lineage", []),
            })

        result = {"added": not duplicate, "duplicate": duplicate, "edge": edge}
        self._write_log.append({"operation": "add_lineage", **result})
        return result
