# DataHub-Grounded dbt Model Generator

A web app where users describe data transformations in natural language, and an AI agent generates production-ready dbt models grounded in **real DataHub metadata** — then opens a GitHub PR with both files.

> **LLM**: Groq (llama-3.3-70b-versatile) — ultra-fast inference via Groq Cloud  
> **MCP**: DataHub MCP Server (or built-in mock for demo)  
> **PR**: GitHub REST API (create branch → commit → PR)

## 🎯 What It Does

1. **User enters**: "build a model joining orders with customer lifetime value, filtered to active accounts"
2. **Agent queries DataHub** via its MCP server to retrieve:
   - Real schemas (tables, columns, types) for relevant datasets
   - Lineage (upstream/downstream) to determine valid joins and `ref()` calls
   - Business glossary terms to resolve ambiguous language ("active account" → `is_active = TRUE`)
   - PII tags and data quality assertions on every column used
3. **Agent generates** (via Claude Sonnet):
   - A `.sql` dbt model using `ref()` calls, valid column names, and correct join logic
   - A `schema.yml` with column descriptions, `not_null`/`unique`/`relationships` tests inferred from DataHub
4. **Agent opens a GitHub PR** with both files and a rich description including:
   - DataHub sources + lineage used
   - Glossary terms resolved
   - ⚠️ PII/sensitive column warnings
   - ⚠️ Failing assertion warnings

## 🛡️ How MCP Grounding Prevents Hallucinations

The LLM **cannot invent table or column names**. Here's how:

1. Before calling Claude, the agent fetches the **exact schema** of all relevant DataHub datasets via the MCP `search` + `list_schema_fields` tools.
2. The Claude system prompt **injects the complete column list** and explicitly forbids using any identifier not in the provided context.
3. After generation, a **post-generation validator** (`dbt_generator.py`) checks every `ref()` call against the DataHub dataset list, flagging any unknown references before committing to GitHub.

This means the generated SQL is always grounded in the real catalog — not Claude's training-time memory of table structures.

## 🏗️ Architecture

```
User NL Request
       │
       ▼
┌─────────────────────────────────────────┐
│              FastAPI Backend            │
│                                         │
│  Step 1: DataHub MCP → search()         │
│          get_entities()                 │
│          list_schema_fields()           │
│                                         │
│  Step 2: get_lineage() per dataset      │
│                                         │
│  Step 3: search(type=GLOSSARY_TERM)     │
│          Resolve business terms         │
│                                         │
│  Step 4: Check PII tags + assertions    │
│                                         │
│  Step 5: Claude Sonnet (grounded)       │
│          System prompt = exact schema   │
│                                         │
│  Step 6: Validate identifiers           │
│          vs. DataHub catalog            │
│                                         │
│  Step 7: GitHub REST API                │
│          create branch → commit →       │
│          open PR                        │
└─────────────────────────────────────────┘
       │ SSE stream
       ▼
┌─────────────────────────────────────────┐
│           React Frontend                │
│  • Chat input with example prompts      │
│  • Real-time 7-step progress panel      │
│  • SQL/YAML side-by-side preview        │
│  • PR link + governance warnings        │
└─────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Clone & setup backend

```bash
cd backend
cp .env.example .env
# Edit .env with your credentials (see below)

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```env
# Use the built-in mock (no DataHub needed):
USE_MOCK_MCP=true

# OR point at a real DataHub instance:
USE_MOCK_MCP=false
DATAHUB_MCP_URL=https://your-datahub.acryl.io/api/mcp
DATAHUB_TOKEN=your_token

# Required for LLM generation:
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile  # optional, this is the default

# Required for GitHub PR creation:
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-org/dbt-analytics
DBT_MODELS_PATH=models/marts
```

### 3. Start backend

```bash
cd backend
python main.py
# Runs on http://localhost:8000
```

### 4. Start frontend

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173
```

Open http://localhost:5173 and start generating!

## 📁 Project Structure

```
dgdmg/
├── backend/
│   ├── main.py           # FastAPI + SSE streaming
│   ├── agent.py          # 7-step orchestration
│   ├── datahub_mcp.py    # DataHub MCP client (real + mock)
│   ├── mock_mcp.py       # Rich e-commerce mock catalog
│   ├── dbt_generator.py  # SQL/YAML post-processing + validation
│   ├── github_client.py  # GitHub REST API (branch/commit/PR)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── ChatInput.jsx
│           ├── ProgressPanel.jsx
│           ├── ArtifactPreview.jsx
│           └── PRResult.jsx
├── mock-data/
│   ├── datasets.json     # 7 e-commerce tables with full schemas
│   ├── lineage.json      # Lineage graph
│   └── glossary.json     # Business glossary terms
└── README.md
```

## 🎭 Mock DataHub Catalog

For demo purposes, the mock MCP includes a realistic e-commerce data lake:

| Layer | Tables |
|-------|--------|
| **Bronze** | `raw_orders`, `raw_customers`, `raw_products` |
| **Silver** | `stg_orders`, `stg_customers` |
| **Gold** | `fct_orders`, `dim_customers` |

Business terms: `active_account`, `lifetime_value`, `net_revenue`, `churn_risk`, `order_status`

PII columns: `email`, `phone_number`, `first_name`, `last_name` (tagged in DataHub)

Failing assertions: `raw_customers` has a stale freshness assertion (demonstrates warning flow)

## ⚙️ Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `USE_MOCK_MCP` | No (default: `true`) | Use mock DataHub catalog |
| `DATAHUB_MCP_URL` | If not mock | DataHub MCP server URL |
| `DATAHUB_TOKEN` | If not mock | DataHub personal access token |
| `GROQ_API_KEY` | **Yes** | Groq API key (get one free at console.groq.com) |
| `GROQ_MODEL` | No (default: `llama-3.3-70b-versatile`) | Groq model ID |
| `GITHUB_TOKEN` | For PRs | GitHub PAT with repo scope |
| `GITHUB_REPO` | For PRs | `owner/repo` format |
| `DBT_MODELS_PATH` | For PRs | Path within repo (e.g. `models/marts`) |
| `GITHUB_BASE_BRANCH` | No (default: `main`) | Base branch for PRs |

## 🔧 Tech Stack

- **Frontend**: React + Tailwind CSS (Vite)
- **Backend**: Python + FastAPI + Server-Sent Events
- **LLM**: Groq (llama-3.3-70b-versatile) via `groq` Python SDK
- **Data Catalog**: DataHub MCP Server (or mock)
- **GitHub**: REST API (Octokit-style via httpx)
