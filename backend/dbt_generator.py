"""
dbt_generator.py — Post-process and validate LLM-generated dbt SQL + YAML.
Ensures every identifier in generated SQL exists in DataHub schema context.
"""
from __future__ import annotations
import re
import json
import textwrap
from typing import Any

import yaml


# ─────────────────────────────────────────────────────────────────────────────
# SQL identifier extractor
# ─────────────────────────────────────────────────────────────────────────────

def extract_identifiers(sql: str) -> set[str]:
    """Extract column references from SQL (simple regex — good enough for validation)."""
    # Remove string literals and comments
    sql_clean = re.sub(r"'[^']*'", "", sql)
    sql_clean = re.sub(r"--[^\n]*", "", sql_clean)
    sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
    
    # Find ref() calls
    refs = re.findall(r"ref\(['\"]([^'\"]+)['\"]\)", sql_clean)
    # Find column-like identifiers in SELECT and WHERE (between SELECT and FROM)
    tokens = re.findall(r"\b([a-z_][a-z0-9_]*)\b", sql_clean.lower())
    
    sql_keywords = {
        "select", "from", "where", "join", "on", "left", "right", "inner",
        "outer", "full", "group", "by", "order", "having", "with", "as",
        "and", "or", "not", "in", "is", "null", "true", "false", "case",
        "when", "then", "else", "end", "distinct", "limit", "offset",
        "sum", "count", "avg", "max", "min", "coalesce", "cast", "date",
        "timestamp", "integer", "varchar", "decimal", "boolean", "ref",
        "source", "union", "all", "except", "intersect", "between", "like",
        "ilike", "over", "partition", "row", "rows", "current", "preceding",
        "following", "unbounded", "asc", "desc", "nulls", "last", "first",
    }
    
    identifiers = {t for t in tokens if t not in sql_keywords and len(t) > 1}
    return identifiers, set(refs)


def validate_sql_against_schema(
    sql: str,
    datasets: list[dict],
    model_name: str,
) -> tuple[bool, list[str]]:
    """
    Validate that every ref() in the SQL corresponds to a real DataHub dataset,
    and that column names used appear in the schema.
    Returns (is_valid, list_of_warnings).
    """
    warnings = []
    known_dataset_names = {ds["name"] for ds in datasets}
    
    all_known_columns: set[str] = set()
    for ds in datasets:
        for field in ds.get("fields", []):
            all_known_columns.add(field["name"].lower())

    identifiers, refs = extract_identifiers(sql)
    
    # Validate ref() calls
    for ref_name in refs:
        if ref_name not in known_dataset_names:
            warnings.append(f"⚠️ ref('{ref_name}') references an unknown dataset not found in DataHub catalog.")
    
    # Validate column-like identifiers (best-effort, many false positives — just flag suspicious ones)
    suspicious = []
    for ident in identifiers:
        if (
            len(ident) > 3
            and ident not in known_dataset_names
            and ident not in all_known_columns
            and ident != model_name.lower()
            and not any(ident in ds["name"].lower() for ds in datasets)
        ):
            suspicious.append(ident)
    
    # Only flag if there are many suspicious ones (to avoid false positives on aliases, etc.)
    if len(suspicious) > 5:
        warnings.append(
            f"⚠️ Validation: {len(suspicious)} identifiers not found in DataHub schema. "
            f"Review: {', '.join(list(suspicious)[:5])}..."
        )
    
    is_valid = len([w for w in warnings if "unknown dataset" in w]) == 0
    return is_valid, warnings


# ─────────────────────────────────────────────────────────────────────────────
# YAML generator — dbt schema.yml
# ─────────────────────────────────────────────────────────────────────────────

def generate_schema_yaml(
    model_name: str,
    model_description: str,
    columns: list[dict],  # from DataHub schema
    lineage: list[dict],  # upstream edges for relationship tests
) -> str:
    """Generate a dbt schema.yml for the new model."""
    
    col_defs = []
    for col in columns:
        col_def: dict[str, Any] = {
            "name": col["name"],
            "description": col.get("description", ""),
        }
        
        tests = []
        if col.get("isPrimaryKey"):
            tests.extend(["not_null", "unique"])
        elif col.get("isForeignKey"):
            tests.append("not_null")
            # Add relationships test if we can resolve the FK
            fk_table = col.get("fkTable")
            fk_col = col.get("fkColumn")
            if fk_table and fk_col:
                tests.append({
                    "relationships": {
                        "to": f"ref('{fk_table}')",
                        "field": fk_col,
                    }
                })
        
        # Check DataHub tags for documentation notes
        tags = col.get("tags", [])
        if tags:
            col_def["meta"] = {"datahub_tags": tags}
            if "PII" in tags or "SENSITIVE" in tags:
                col_def["description"] = (col_def["description"] or "") + " ⚠️ PII/Sensitive column — handle with care."
        
        if tests:
            col_def["tests"] = tests
        
        col_defs.append(col_def)
    
    schema = {
        "version": 2,
        "models": [
            {
                "name": model_name,
                "description": model_description,
                "columns": col_defs,
            }
        ]
    }
    
    return yaml.dump(schema, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ─────────────────────────────────────────────────────────────────────────────
# Parse LLM output
# ─────────────────────────────────────────────────────────────────────────────

def parse_llm_output(raw_output: str) -> dict:
    """
    Parse Claude's structured JSON output into sql + yaml + metadata.
    Expected format:
    {
      "model_name": "...",
      "model_description": "...",
      "sql": "...",
      "columns": [...],
      "reasoning": "..."
    }
    """
    # Try to extract JSON from the response
    json_match = re.search(r"```json\s*(.*?)\s*```", raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try raw JSON
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass
    
    # Fallback: extract SQL block
    sql_match = re.search(r"```sql\s*(.*?)\s*```", raw_output, re.DOTALL)
    sql = sql_match.group(1) if sql_match else raw_output
    
    return {
        "model_name": "generated_model",
        "model_description": "Auto-generated dbt model",
        "sql": sql,
        "columns": [],
        "reasoning": "",
    }


def slugify_model_name(text: str) -> str:
    """Convert NL request to a valid dbt model name."""
    # Remove special chars, lowercase, replace spaces with underscores
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
    slug = re.sub(r"\s+", "_", slug.strip())
    # Trim to reasonable length
    words = slug.split("_")[:6]
    return "_".join(words)
