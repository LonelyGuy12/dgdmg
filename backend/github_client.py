"""
github_client.py — GitHub REST API operations for creating dbt model PRs.
"""
from __future__ import annotations
import os
import base64
import re
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
DBT_MODELS_PATH = os.getenv("DBT_MODELS_PATH", "models/marts")
GITHUB_BASE_BRANCH = os.getenv("GITHUB_BASE_BRANCH", "main")

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self):
        if not GITHUB_TOKEN or not GITHUB_REPO:
            raise ValueError(
                "GITHUB_TOKEN and GITHUB_REPO must be set in environment. "
                "Copy .env.example to .env and fill in the values."
            )
        self._http = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        self.repo = GITHUB_REPO

    async def _get_default_branch_sha(self) -> str:
        """Get the latest commit SHA of the base branch."""
        resp = await self._http.get(
            f"/repos/{self.repo}/git/ref/heads/{GITHUB_BASE_BRANCH}"
        )
        resp.raise_for_status()
        return resp.json()["object"]["sha"]

    async def create_branch(self, branch_name: str) -> str:
        """Create a new branch from the base branch."""
        sha = await self._get_default_branch_sha()
        resp = await self._http.post(
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        if resp.status_code == 422:
            # Branch already exists — delete and recreate
            await self._http.delete(
                f"/repos/{self.repo}/git/refs/heads/{branch_name}"
            )
            resp = await self._http.post(
                f"/repos/{self.repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
        resp.raise_for_status()
        return branch_name

    async def commit_files(
        self,
        branch: str,
        files: list[dict],  # [{"path": "...", "content": "..."}]
        commit_message: str,
    ) -> str:
        """Commit multiple files to a branch atomically using the Git tree API."""
        # 1. Get current tree SHA
        head_resp = await self._http.get(
            f"/repos/{self.repo}/git/ref/heads/{branch}"
        )
        head_resp.raise_for_status()
        base_sha = head_resp.json()["object"]["sha"]

        commit_resp = await self._http.get(
            f"/repos/{self.repo}/git/commits/{base_sha}"
        )
        commit_resp.raise_for_status()
        base_tree_sha = commit_resp.json()["tree"]["sha"]

        # 2. Create blobs for each file
        tree_entries = []
        for file in files:
            content_b64 = base64.b64encode(file["content"].encode()).decode()
            blob_resp = await self._http.post(
                f"/repos/{self.repo}/git/blobs",
                json={"content": content_b64, "encoding": "base64"},
            )
            blob_resp.raise_for_status()
            blob_sha = blob_resp.json()["sha"]
            tree_entries.append({
                "path": file["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha,
            })

        # 3. Create new tree
        tree_resp = await self._http.post(
            f"/repos/{self.repo}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )
        tree_resp.raise_for_status()
        new_tree_sha = tree_resp.json()["sha"]

        # 4. Create commit
        new_commit_resp = await self._http.post(
            f"/repos/{self.repo}/git/commits",
            json={
                "message": commit_message,
                "tree": new_tree_sha,
                "parents": [base_sha],
            },
        )
        new_commit_resp.raise_for_status()
        new_commit_sha = new_commit_resp.json()["sha"]

        # 5. Update branch ref
        update_resp = await self._http.patch(
            f"/repos/{self.repo}/git/refs/heads/{branch}",
            json={"sha": new_commit_sha, "force": False},
        )
        update_resp.raise_for_status()
        return new_commit_sha

    async def create_pr(
        self,
        branch: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        """Open a pull request from branch → base branch."""
        payload = {
            "title": title,
            "head": branch,
            "base": GITHUB_BASE_BRANCH,
            "body": body,
            "draft": False,
        }
        resp = await self._http.post(
            f"/repos/{self.repo}/pulls",
            json=payload,
        )
        resp.raise_for_status()
        pr = resp.json()

        # Add labels if requested and they exist
        if labels:
            try:
                await self._http.post(
                    f"/repos/{self.repo}/issues/{pr['number']}/labels",
                    json={"labels": labels},
                )
            except Exception:
                pass  # Labels not critical

        return {
            "number": pr["number"],
            "url": pr["html_url"],
            "title": pr["title"],
        }

    async def close(self):
        await self._http.aclose()


def build_pr_description(
    nl_request: str,
    model_name: str,
    sql_content: str,
    tables_used: list[str],
    lineage_info: list[dict],
    glossary_terms: list[dict],
    pii_warnings: list[dict],
    assertion_warnings: list[dict],
) -> str:
    """Build a rich PR description with DataHub provenance."""
    tables_md = "\n".join(f"- `{t}`" for t in tables_used)
    lineage_md = "\n".join(
        f"- `{e.get('upstream', '?')}` → `{e.get('downstream', '?')}`"
        for e in lineage_info
    ) if lineage_info else "_No upstream lineage detected_"
    
    glossary_md = "\n".join(
        f"- **{t['name']}**: {t['definition'][:120]}..."
        for t in glossary_terms
    ) if glossary_terms else "_No business terms resolved_"

    warnings_section = ""
    if pii_warnings:
        cols = ", ".join(f"`{w['dataset']}.{w['column']}`" for w in pii_warnings)
        warnings_section += f"\n> ⚠️ **PII WARNING**: The following columns used in this model are tagged PII/SENSITIVE in DataHub: {cols}. Ensure downstream consumers have appropriate access controls.\n"
    
    if assertion_warnings:
        for w in assertion_warnings:
            warnings_section += f"\n> ⚠️ **DATA QUALITY WARNING**: Source table `{w['dataset']}` has a **failing {w['type']} assertion** (`{w.get('column', 'table-level')}`). Last run: {w.get('lastRun', 'unknown')}. Verify data freshness before merging.\n"

    return f"""## 🤖 dbt Model: `{model_name}`

**Generated by**: DataHub-Grounded dbt Model Generator  
**Request**: _{nl_request}_  
**Generated at**: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

---

### 📋 What this model does

This dbt model was generated from a natural language request, grounded in real DataHub metadata. All table and column names were validated against the DataHub catalog before generation.
{warnings_section}
---

### 🗄️ DataHub Sources Used

{tables_md}

### 🔗 Lineage Context

{lineage_md}

### 📖 Business Glossary Terms Resolved

{glossary_md}

---

### ✅ dbt Tests Generated

The `schema.yml` includes automatically inferred tests:
- `not_null` + `unique` on primary key columns (from DataHub assertion metadata)
- `relationships` tests where DataHub lineage shows clear FK relationships
- `not_null` on foreign key columns

---

### 🛡️ Anti-Hallucination Guarantee

Every table name, column name, and `ref()` call in this SQL was validated against the DataHub schema catalog before this PR was created. The LLM was explicitly forbidden from inventing identifiers not present in the catalog.

---

_Review the generated SQL and YAML carefully before merging. This is an AI-generated model — a human should verify business logic correctness._
"""
