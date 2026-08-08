"""
agent.py — DataHub-grounded dbt model generation agent.
Orchestrates: DataHub MCP → Glossary → Groq LLM → Validation → GitHub PR.
Streams progress events as async generator.
"""
from __future__ import annotations
import os
import json
import re
from typing import AsyncGenerator

from groq import Groq
from dotenv import load_dotenv

from datahub_mcp import DataHubMCPClient
from dbt_generator import (
    parse_llm_output,
    validate_sql_against_schema,
    generate_schema_yaml,
    slugify_model_name,
)
from github_client import GitHubClient, build_pr_description

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DBT_MODELS_PATH = os.getenv("DBT_MODELS_PATH", "models/marts")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", "2"))


def _event(step: str, status: str, message: str, data: dict | None = None) -> dict:
    return {"step": step, "status": status, "message": message, "data": data or {}}


SYSTEM_PROMPT = """You are a dbt model generator with access to a grounded DataHub metadata catalog.
You will receive:
1. A natural language request describing the desired data transformation
2. The EXACT schema of relevant DataHub datasets (table names, column names, types)  
3. Lineage information (which tables flow into which)
4. Resolved glossary term definitions

YOUR STRICT RULES:
- You MUST ONLY use table names and column names that appear in the provided schema context
- You MUST use ref() calls for dbt models, NOT raw table names
- You MUST NOT invent columns or tables not in the context
- For business terms (e.g. "active accounts", "lifetime value"), use the provided glossary definition to map to the exact column
- Generate a single model per request

Return a JSON object (in a ```json block) with this exact structure:
{
  "model_name": "snake_case_model_name",
  "model_description": "One sentence describing what this model does",
  "sql": "-- Full dbt SQL model content\\nSELECT ...\\nFROM {{ ref('...') }}",
  "columns": [
    {
      "name": "column_name",
      "description": "...",
      "isPrimaryKey": false,
      "isForeignKey": false,
      "fkTable": null,
      "fkColumn": null,
      "tags": []
    }
  ],
  "reasoning": "Brief explanation of join logic and business term resolution"
}
"""


async def run_agent(nl_request: str) -> AsyncGenerator[dict, None]:
    """
    Main agent loop. Yields progress events as dicts.
    Each event: {"step": str, "status": "running"|"done"|"error", "message": str, "data": {}}
    """
    mcp = DataHubMCPClient()
    github = None

    try:
        # ─────────────────────────────────────────────────
        # STEP 1: Schema Lookup
        # ─────────────────────────────────────────────────
        yield _event("schema", "running", "Searching DataHub catalog for relevant datasets…")

        all_datasets = await mcp.get_all_datasets()
        
        # Search for datasets relevant to the request
        search_results = await mcp.search(nl_request, entity_type="DATASET", limit=6)
        
        # Also search for key nouns in the request
        keywords = _extract_keywords(nl_request)
        for kw in keywords[:3]:
            kw_results = await mcp.search(kw, entity_type="DATASET", limit=3)
            for r in kw_results:
                if not any(s["name"] == r["name"] for s in search_results):
                    search_results.append(r)

        # De-duplicate and get full schema for top results
        seen = set()
        relevant_datasets = []
        for ds in search_results:
            if ds["name"] not in seen:
                seen.add(ds["name"])
                relevant_datasets.append(ds)
        
        relevant_datasets = relevant_datasets[:7]  # Cap at 7 datasets for context window

        yield _event("schema", "done", 
            f"Found {len(relevant_datasets)} relevant datasets in DataHub",
            {
                "datasets": [
                    {
                        "name": ds["name"],
                        "description": ds.get("description", ""),
                        "fieldCount": len(ds.get("fields", [])),
                        "platform": ds.get("platform", ""),
                        "freshness": ds.get("freshness", "healthy"),
                        "tags": ds.get("tags", []),
                    }
                    for ds in relevant_datasets
                ]
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 2: Lineage Fetch
        # ─────────────────────────────────────────────────
        yield _event("lineage", "running", "Tracing lineage for relevant datasets…")

        lineage_map: dict[str, dict] = {}
        for ds in relevant_datasets[:4]:  # Limit lineage calls
            upstream = await mcp.get_lineage(ds["name"], direction="UPSTREAM")
            lineage_map[ds["name"]] = upstream

        all_lineage_edges = []
        for ds_name, lineage in lineage_map.items():
            all_lineage_edges.extend(lineage.get("edges", []))

        # De-duplicate edges
        seen_edges = set()
        unique_edges = []
        for edge in all_lineage_edges:
            key = (edge.get("upstream", ""), edge.get("downstream", ""))
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(edge)

        yield _event("lineage", "done",
            f"Mapped {len(unique_edges)} lineage relationships",
            {
                "edges": [
                    {
                        "upstream": _short_name(e.get("upstream", "")),
                        "downstream": _short_name(e.get("downstream", "")),
                        "type": e.get("transformationType", ""),
                    }
                    for e in unique_edges[:8]
                ]
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 3: Glossary Resolution
        # ─────────────────────────────────────────────────
        yield _event("glossary", "running", "Resolving business terms from request…")

        business_terms = _extract_business_terms(nl_request)
        resolved_terms = []
        
        for term in business_terms:
            results = await mcp.search_glossary(term)
            if results:
                resolved_terms.append(results[0])

        yield _event("glossary", "done",
            f"Resolved {len(resolved_terms)} business terms from DataHub glossary",
            {
                "terms": [
                    {
                        "name": t["name"],
                        "definition": t["definition"][:150] + "..." if len(t.get("definition", "")) > 150 else t.get("definition", ""),
                    }
                    for t in resolved_terms
                ]
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 4: Tags & Assertions Check
        # ─────────────────────────────────────────────────
        yield _event("governance", "running", "Checking PII tags and data quality assertions…")

        pii_warnings = []
        assertion_warnings = []
        
        for ds in relevant_datasets:
            # PII check
            for field in ds.get("fields", []):
                tags = field.get("tags", [])
                if any(t in ("PII", "SENSITIVE") for t in tags):
                    pii_warnings.append({
                        "dataset": ds["name"],
                        "column": field["name"],
                        "tags": tags,
                    })
            
            # Assertion check — flag failing ones
            for assertion in ds.get("assertions", []):
                if assertion.get("status") == "failing":
                    assertion_warnings.append({
                        "dataset": ds["name"],
                        **assertion,
                    })

        yield _event("governance", "done",
            f"Found {len(pii_warnings)} PII columns and {len(assertion_warnings)} failing assertions",
            {
                "piiColumns": pii_warnings[:10],
                "assertionWarnings": assertion_warnings,
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 5: LLM Generation
        # ─────────────────────────────────────────────────
        yield _event("generation", "running", f"Generating dbt SQL + schema.yml with Groq ({GROQ_MODEL})…")

        context = _build_llm_context(
            nl_request, relevant_datasets, unique_edges, resolved_terms
        )

        if not GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )

        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": context},
            ],
        )
        raw_output = response.choices[0].message.content

        parsed = parse_llm_output(raw_output)
        model_name = parsed.get("model_name") or slugify_model_name(nl_request)
        model_name = re.sub(r"[^a-z0-9_]", "", model_name.lower())
        sql_content = parsed.get("sql", "")
        model_description = parsed.get("model_description", "Generated dbt model")
        llm_columns = parsed.get("columns", [])

        yield _event("generation", "done",
            f"Generated model `{model_name}` with {len(llm_columns)} output columns",
            {
                "modelName": model_name,
                "description": model_description,
                "sql": sql_content,
                "reasoning": parsed.get("reasoning", ""),
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 6: Validation
        # ─────────────────────────────────────────────────
        yield _event("validation", "running", "Validating generated SQL against DataHub schema…")

        repair_history = []
        is_valid = False
        validation_warnings = []

        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            if attempt > 0:
                yield _event(
                    "validation",
                    "running",
                    f"Re-validating repaired SQL (attempt {attempt}/{MAX_REPAIR_ATTEMPTS})...",
                )

            is_valid, validation_warnings = validate_sql_against_schema(
                sql_content, relevant_datasets, model_name
            )

            if is_valid:
                break

            if attempt >= MAX_REPAIR_ATTEMPTS:
                break

            repair_history.append({
                "attempt": attempt + 1,
                "warnings": validation_warnings,
            })
            yield _event(
                "validation",
                "warning",
                f"Validation found {len(validation_warnings)} issue(s); asking Groq to repair SQL...",
                {
                    "valid": False,
                    "warnings": validation_warnings,
                    "repairAttempt": attempt + 1,
                },
            )

            repair_response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _build_repair_context(
                            nl_request=nl_request,
                            datasets=relevant_datasets,
                            lineage_edges=unique_edges,
                            glossary_terms=resolved_terms,
                            parsed=parsed,
                            validation_warnings=validation_warnings,
                        ),
                    },
                ],
            )

            repaired = parse_llm_output(repair_response.choices[0].message.content)
            if not repaired.get("sql"):
                validation_warnings.append("Validation error: repair response did not include SQL.")
                break

            parsed = {**parsed, **repaired}
            model_name = parsed.get("model_name") or slugify_model_name(nl_request)
            model_name = re.sub(r"[^a-z0-9_]", "", model_name.lower())
            sql_content = parsed.get("sql", "")
            model_description = parsed.get("model_description", model_description)
            llm_columns = parsed.get("columns", llm_columns)

            yield _event("generation", "done",
                f"Repaired model `{model_name}` after validation feedback",
                {
                    "modelName": model_name,
                    "description": model_description,
                    "sql": sql_content,
                    "reasoning": parsed.get("reasoning", ""),
                    "repairAttempt": attempt + 1,
                }
            )

        if not is_valid:
            yield _event("validation", "error",
                f"Validation failed after {MAX_REPAIR_ATTEMPTS + 1} attempt(s); GitHub PR skipped.",
                {
                    "valid": False,
                    "warnings": validation_warnings,
                    "repairHistory": repair_history,
                    "sql": sql_content,
                }
            )
            return

        # Generate the schema YAML using DataHub column metadata
        # Use LLM columns as base, enriched with DataHub metadata
        schema_columns = _merge_columns(llm_columns, relevant_datasets, unique_edges)
        yaml_content = generate_schema_yaml(
            model_name=model_name,
            model_description=model_description,
            columns=schema_columns,
            lineage=unique_edges,
        )

        yield _event("validation", "done" if is_valid else "warning",
            f"Validation {'passed' if is_valid else 'completed with warnings'}: {len(validation_warnings)} issue(s)",
            {
                "valid": is_valid,
                "warnings": validation_warnings,
                "yaml": yaml_content,
                "repairHistory": repair_history,
            }
        )

        # ─────────────────────────────────────────────────
        # STEP 7: GitHub PR
        # ─────────────────────────────────────────────────
        yield _event("github", "running", "Creating GitHub branch and opening PR…")

        github_token = os.getenv("GITHUB_TOKEN", "")
        github_repo = os.getenv("GITHUB_REPO", "")

        if not github_token or not github_repo:
            yield _event("github", "skipped",
                "GitHub credentials not configured — PR creation skipped.",
                {
                    "skipped": True,
                    "reason": "Set GITHUB_TOKEN and GITHUB_REPO in .env to enable PR creation",
                    "files": {
                        "sql": {
                            "path": f"{DBT_MODELS_PATH}/{model_name}.sql",
                            "content": sql_content,
                        },
                        "yaml": {
                            "path": f"{DBT_MODELS_PATH}/{model_name}.yml",
                            "content": yaml_content,
                        }
                    }
                }
            )
            return

        github = GitHubClient()
        
        import re as _re
        branch_name = f"dbt-gen/{model_name}-{_re.sub(r'[^a-z0-9]', '', nl_request.lower()[:20])}"
        branch_name = branch_name[:60]  # GitHub branch name limit

        await github.create_branch(branch_name)

        sql_path = f"{DBT_MODELS_PATH}/{model_name}.sql"
        yaml_path = f"{DBT_MODELS_PATH}/{model_name}.yml"

        await github.commit_files(
            branch=branch_name,
            files=[
                {"path": sql_path, "content": sql_content},
                {"path": yaml_path, "content": yaml_content},
            ],
            commit_message=f"feat: add {model_name} dbt model [generated by dbt-generator]",
        )

        pr_body = build_pr_description(
            nl_request=nl_request,
            model_name=model_name,
            sql_content=sql_content,
            tables_used=[ds["name"] for ds in relevant_datasets],
            lineage_info=unique_edges,
            glossary_terms=resolved_terms,
            pii_warnings=pii_warnings,
            assertion_warnings=assertion_warnings,
        )

        pr = await github.create_pr(
            branch=branch_name,
            title=f"feat: {model_name} — {nl_request[:60]}",
            body=pr_body,
            labels=["dbt", "generated"],
        )

        yield _event("github", "done",
            f"PR #{pr['number']} created successfully!",
            {
                "pr": {
                    "number": pr["number"],
                    "url": pr["url"],
                    "title": pr["title"],
                },
                "files": {
                    "sql": sql_path,
                    "yaml": yaml_path,
                },
                "piiWarnings": pii_warnings,
                "assertionWarnings": assertion_warnings,
            }
        )

    except Exception as e:
        import traceback
        yield _event("error", "error", f"Agent error: {str(e)}", {
            "traceback": traceback.format_exc()
        })
    finally:
        await mcp.close()
        if github:
            await github.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful nouns for DataHub search."""
    stopwords = {"a", "an", "the", "with", "and", "or", "for", "to", "of",
                 "in", "on", "at", "by", "is", "are", "was", "were", "be",
                 "build", "create", "generate", "make", "model", "joining",
                 "join", "filter", "filtered", "get", "show", "all", "from"}
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text.lower())
    return [w for w in words if w not in stopwords and len(w) > 2]


def _extract_business_terms(text: str) -> list[str]:
    """Extract potential business terms from NL request."""
    patterns = [
        r"active\s+account[s]?",
        r"lifetime\s+value",
        r"customer\s+ltv",
        r"churn\s+risk",
        r"net\s+revenue",
        r"product\s+categor\w+",
        r"order\s+status",
    ]
    terms = []
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            # Extract the matched phrase
            match = re.search(pattern, text_lower)
            if match:
                terms.append(match.group(0))
    # Also extract capitalized multi-word phrases
    caps = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", text)
    terms.extend(caps)
    return list(set(terms))


def _build_llm_context(
    nl_request: str,
    datasets: list[dict],
    lineage_edges: list[dict],
    glossary_terms: list[dict],
) -> str:
    """Build the grounded context for the LLM."""
    schema_sections = []
    for ds in datasets:
        fields_text = "\n".join(
            f"  - {f['name']} ({f['type']})"
            + (" [PK]" if f.get("isPrimaryKey") else "")
            + (f" [FK → {f.get('fkTable')}.{f.get('fkColumn')}]" if f.get("isForeignKey") else "")
            + (f" [TAGS: {', '.join(f.get('tags', []))}]" if f.get("tags") else "")
            + f" — {f.get('description', '')}"
            for f in ds.get("fields", [])
        )
        platform = ds.get("platform", "dbt")
        ref_style = f"ref('{ds['name']}')" if platform == "dbt" else f"source('{ds.get('schema', 'raw')}', '{ds['name']}')"
        schema_sections.append(
            f"### {ds['name']} [{platform}] — use: {{{{ {ref_style} }}}}\n"
            f"Description: {ds.get('description', '')}\n"
            f"Fields:\n{fields_text}"
        )
    
    lineage_text = "\n".join(
        f"  {_short_name(e.get('upstream', ''))} → {_short_name(e.get('downstream', ''))}"
        for e in lineage_edges[:10]
    ) or "  (no lineage found)"
    
    glossary_text = "\n".join(
        f"  **{t['name']}**: {t['definition']}"
        for t in glossary_terms
    ) or "  (no matching glossary terms)"
    
    return f"""## Natural Language Request
{nl_request}

## Available DataHub Datasets (USE ONLY THESE — do not invent others)

{chr(10).join(schema_sections)}

## Lineage Map
{lineage_text}

## Resolved Business Terms (use these definitions)
{glossary_text}

## Instructions
Generate a dbt model that fulfills the request using ONLY the datasets and columns listed above.
Use ref() for dbt models, source() for raw tables.
Return JSON as specified in the system prompt.
"""


def _build_repair_context(
    nl_request: str,
    datasets: list[dict],
    lineage_edges: list[dict],
    glossary_terms: list[dict],
    parsed: dict,
    validation_warnings: list[str],
) -> str:
    """Build a focused prompt that asks the LLM to repair invalid SQL."""
    existing_json = {
        "model_name": parsed.get("model_name"),
        "model_description": parsed.get("model_description"),
        "sql": parsed.get("sql"),
        "columns": parsed.get("columns", []),
        "reasoning": parsed.get("reasoning", ""),
    }
    warnings_text = "\n".join(f"- {warning}" for warning in validation_warnings)

    return f"""{_build_llm_context(nl_request, datasets, lineage_edges, glossary_terms)}

## Validation Feedback
The generated dbt model failed validation. Fix the SQL and column metadata so every ref/source/table
and every qualified column is present in the DataHub schema context.

Validation issues:
{warnings_text}

## Current Generated JSON
```json
{json.dumps(existing_json, indent=2)}
```

Return the full corrected JSON object in the exact format required by the system prompt.
Keep the model grounded in the listed DataHub datasets only.
"""


def _short_name(urn: str) -> str:
    """Extract readable name from a DataHub URN."""
    parts = urn.split(",")
    if len(parts) >= 2:
        return parts[1].split(".")[-1]
    return urn


def _merge_columns(
    llm_columns: list[dict],
    datasets: list[dict],
    lineage_edges: list[dict],
) -> list[dict]:
    """Merge LLM-proposed columns with DataHub metadata for richer YAML."""
    # Build column lookup from DataHub
    dh_cols: dict[str, dict] = {}
    for ds in datasets:
        for field in ds.get("fields", []):
            dh_cols[field["name"]] = field
    
    merged = []
    for col in llm_columns:
        col_name = col.get("name", "")
        dh_meta = dh_cols.get(col_name, {})
        merged.append({
            "name": col_name,
            "description": col.get("description") or dh_meta.get("description", ""),
            "isPrimaryKey": col.get("isPrimaryKey", False) or dh_meta.get("isPrimaryKey", False),
            "isForeignKey": col.get("isForeignKey", False) or dh_meta.get("isForeignKey", False),
            "fkTable": col.get("fkTable") or dh_meta.get("fkTable"),
            "fkColumn": col.get("fkColumn") or dh_meta.get("fkColumn"),
            "tags": list(set(col.get("tags", []) + dh_meta.get("tags", []))),
        })
    
    return merged if merged else list(dh_cols.values())[:10]
