"""
Post-process and validate LLM-generated dbt SQL + YAML.
Ensures generated identifiers stay grounded in the DataHub schema context.
"""
from __future__ import annotations

import json
import re
from typing import Any

import yaml


def extract_identifiers(sql: str) -> tuple[set[str], set[str]]:
    """Extract likely SQL identifiers and dbt ref() calls."""
    refs = {
        ref.lower()
        for ref in re.findall(
            r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)",
            sql,
            flags=re.IGNORECASE,
        )
    }

    # Extract refs before stripping strings; otherwise ref('model_name') disappears.
    sql_clean = _strip_sql_comments(sql)
    sql_clean = re.sub(r"'[^']*'", "", sql_clean)
    sql_clean = re.sub(r'"[^"]*"', "", sql_clean)
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
        "date_trunc", "extract", "true", "false",
    }

    identifiers = {token for token in tokens if token not in sql_keywords and len(token) > 1}
    return identifiers, refs


def extract_sources(sql: str) -> set[str]:
    """Extract table names from dbt source(schema, table) calls."""
    return {
        table.lower()
        for _, table in re.findall(
            r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
            sql,
            flags=re.IGNORECASE,
        )
    }


def validate_sql_against_schema(
    sql: str,
    datasets: list[dict],
    model_name: str,
) -> tuple[bool, list[str]]:
    """
    Validate dbt refs/sources, FROM/JOIN relations, and qualified columns.
    Returns (is_valid, list_of_warnings).
    """
    warnings = []
    hard_failures = []
    known_dataset_names = {ds["name"].lower() for ds in datasets}

    all_known_columns: set[str] = set()
    columns_by_dataset: dict[str, set[str]] = {}
    for ds in datasets:
        ds_name = ds["name"].lower()
        columns_by_dataset[ds_name] = set()
        for field in ds.get("fields", []):
            column_name = field["name"].lower()
            all_known_columns.add(column_name)
            columns_by_dataset[ds_name].add(column_name)

    identifiers, refs = extract_identifiers(sql)
    sources = extract_sources(sql)
    cte_names = _extract_cte_names(sql)
    relation_aliases = _extract_relation_aliases(sql)

    for ref_name in sorted(refs):
        if ref_name not in known_dataset_names:
            hard_failures.append(
                f"ref('{ref_name}') references an unknown dataset not found in DataHub catalog."
            )

    for source_name in sorted(sources):
        if source_name not in known_dataset_names:
            hard_failures.append(
                f"source(..., '{source_name}') references an unknown dataset not found in DataHub catalog."
            )

    for alias, table_name in sorted(relation_aliases.items()):
        if alias != table_name:
            continue
        if table_name not in known_dataset_names and table_name not in cte_names:
            hard_failures.append(
                f"Relation '{table_name}' in FROM/JOIN is not present in the DataHub schema context."
            )

    normalized_sql = _normalize_relations(sql).lower()
    qualified_columns = set(
        re.findall(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b", normalized_sql)
    )
    for qualifier, column_name in sorted(qualified_columns):
        dataset_name = relation_aliases.get(qualifier)
        if not dataset_name or dataset_name in cte_names:
            continue
        if column_name not in columns_by_dataset.get(dataset_name, set()):
            hard_failures.append(
                f"Column '{qualifier}.{column_name}' is not present on DataHub dataset '{dataset_name}'."
            )

    ignored_identifiers = set(relation_aliases) | cte_names | known_dataset_names | {model_name.lower()}
    suspicious = [
        ident
        for ident in identifiers
        if (
            len(ident) > 3
            and ident not in ignored_identifiers
            and ident not in all_known_columns
            and not any(ident in ds_name for ds_name in known_dataset_names)
        )
    ]
    if suspicious:
        warnings.append(
            f"Validation warning: {len(suspicious)} identifiers were not found in DataHub schema. "
            f"Review: {', '.join(sorted(suspicious)[:5])}."
        )

    warnings = [f"Validation error: {message}" for message in sorted(set(hard_failures))] + warnings
    return not hard_failures, warnings


def generate_schema_yaml(
    model_name: str,
    model_description: str,
    columns: list[dict],
    lineage: list[dict],
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
            fk_table = col.get("fkTable")
            fk_col = col.get("fkColumn")
            if fk_table and fk_col:
                tests.append({
                    "relationships": {
                        "to": f"ref('{fk_table}')",
                        "field": fk_col,
                    }
                })

        tags = col.get("tags", [])
        if tags:
            col_def["meta"] = {"datahub_tags": tags}
            if "PII" in tags or "SENSITIVE" in tags:
                col_def["description"] = (
                    (col_def["description"] or "") + " PII/Sensitive column - handle with care."
                )

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
        ],
    }

    return yaml.dump(schema, default_flow_style=False, sort_keys=False, allow_unicode=True)


def parse_llm_output(raw_output: str) -> dict:
    """
    Parse the LLM's structured JSON output into SQL, YAML metadata, and reasoning.
    """
    json_match = re.search(r"```json\s*(.*?)\s*```", raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass

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
    """Convert an NL request to a valid dbt model name."""
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
    slug = re.sub(r"\s+", "_", slug.strip())
    words = slug.split("_")[:6]
    return "_".join(words)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)


def _normalize_relations(sql: str) -> str:
    sql = _strip_sql_comments(sql)
    sql = re.sub(
        r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        r"\1",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"\{\{\s*source\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        r"\1",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _extract_cte_names(sql: str) -> set[str]:
    normalized = _normalize_relations(sql).lower()
    return set(re.findall(r"(?:with|,)\s+([a-z_][a-z0-9_]*)\s+as\s*\(", normalized))


def _extract_relation_aliases(sql: str) -> dict[str, str]:
    """Map relation aliases to table names from FROM/JOIN clauses."""
    normalized = _normalize_relations(sql).lower()
    relation_keywords = {
        "on", "where", "join", "left", "right", "inner", "outer", "full",
        "cross", "group", "order", "having", "limit", "union",
    }
    aliases: dict[str, str] = {}
    relation_pattern = re.compile(
        r"\b(?:from|join)\s+([a-z_][a-z0-9_.]*)(?:\s+(?:as\s+)?([a-z_][a-z0-9_]*))?",
        flags=re.IGNORECASE,
    )

    for relation, alias in relation_pattern.findall(normalized):
        table_name = relation.split(".")[-1]
        aliases[table_name] = table_name
        if alias and alias not in relation_keywords:
            aliases[alias] = table_name

    return aliases
