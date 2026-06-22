# Clinical AI Governance Platform

> **Agents propose. A deterministic layer validates. A human approves. Every action is audited.**

A production-grade reference implementation for deploying LLM agents over clinical data with deterministic safety guardrails. Built as a reusable framework for healthcare operators — deploy once, apply across a portfolio of growth-stage companies.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│           Clinical AI Governance Platform                          │
│                                                                    │
│  Agent SDK Orchestration  (src/clinical_agent/)  [Day 4]          │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐       │
│  │  Reader     │─▶│  RAG        │─▶│  Proposal          │       │
│  │  Subagent   │  │  Subagent   │  │  Subagent          │       │
│  │  (FHIR read)│  │  (guidelines│  │  (structured out,  │       │
│  │             │  │   search)   │  │   confidence,      │       │
│  └────────────┘  └────────────┘  │   citations)       │       │
│  SDK Hooks: audit every tool call + cost/latency └──────────────────┘       │
│                                                                    │
│  MCP Server  (src/fhir_mcp/)  FastMCP 3.x  stdio + SSE            │
│  Tools:    list_patients · get_patient · list_observations         │
│             propose_observation · list_pending_writes              │
│             approve_write · reject_write                           │
│  Resources: fhir://patient/{id}/summary  [Day 4]                  │
│  Prompts:   review_pending · patient_overview  [Day 4]            │
│                                                                    │
│  Deterministic Validation  (validator.py)  [Day 2]                │
│  LOINC registry · value ranges · unit checks                      │
│                                                                    │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐ │
│  │ SQLite Store  │  │ ChromaDB [Day3] │  │ Audit Chain     │ │
│  │ WAL mode      │  │ clinical        │  │ SHA-256 JSONL   │ │
│  │ FK enforced   │  │ guidelines      │  │ tamper-evident  │ │
│  └────────────────┘  └────────────────┘  └─────────────────┘ │
│                                                                    │
│  Eval Harness  (evals/)  [Day 6]                                  │
│  25 golden cases · LLM-as-judge · code grading · CI regression   │
└──────────────────────────────────────────────────────────────────────┘
```

## Build status

| Component | Status |
|---|---|
| SQLite persistence (WAL, FK) | ✓ Day 1 |
| Tamper-evident audit (SHA-256 chain) | ✓ Day 1 |
| Auth (principal + approver sets) | ✓ Day 1 |
| LOINC deterministic validation | Day 2 |
| Clinical data (guidelines, notes) | Day 2 |
| RAG — BM25 + ChromaDB hybrid | Day 3 |
| Agent SDK orchestration (3 subagents) | Day 4 |
| Clinical NLP + confidence scoring | Day 5 |
| Eval harness + GitHub Actions CI | Day 6 |
| HTTP server + Railway deploy | Day 7 |

## Metrics

*Updated after eval harness ships on Day 6.*

| Metric | Value |
|---|---|
| Proposal accuracy (approve/reject) | TBD |
| False-negative rate (missed invalid proposals) | TBD |
| Avg confidence on correct proposals | TBD |
| Avg latency per workflow (ms) | TBD |
| Avg cost per workflow (USD) | TBD |

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/seed_db.py   # initialise SQLite from synthetic JSON fixture
pytest -q                   # all tests green
```

## Connect to Claude Code

```bash
claude mcp add clinical-governance -- /path/to/.venv/bin/python -m fhir_mcp.server
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `FHIR_MCP_DB` | `data/fhir.db` | SQLite database path |
| `FHIR_MCP_ACTOR` | `agent:dev` | Agent audit identity |
| `FHIR_MCP_AUDIT_FILE` | stderr | Audit JSONL path |
| `FHIR_MCP_PRINCIPALS` | *(unset = dev mode)* | Allowed agent actor IDs |
| `FHIR_MCP_APPROVERS` | *(unset = dev mode)* | Allowed human approver IDs |

## Verify audit chain integrity

```bash
python scripts/audit_verify.py data/audit.jsonl
# ✓ Chain intact — no tampering detected.
```

## Repository structure

```
src/
  fhir_mcp/          # MCP server
    server.py        # FastMCP tools + auth calls
    store.py         # SQLite store (the only PHI touchpoint)
    models.py        # Pydantic v2 FHIR models
    audit.py         # Tamper-evident hash-chain audit
    auth.py          # Principal + approver verification
    validator.py     # LOINC deterministic validation [Day 2]
    rag.py           # BM25 + ChromaDB hybrid search [Day 3]
    nlp.py           # Entity extraction → ICD-10/LOINC/NPI [Day 5]
    confidence.py    # Calibrated confidence scoring [Day 5]
    http_server.py   # FastAPI SSE transport [Day 7]
  clinical_agent/    # Agent SDK orchestration [Day 4]
    orchestrator.py
    subagents.py
    hooks.py
evals/               # Eval harness [Day 6]
data/                # Synthetic FHIR data + SQLite DB
scripts/
  seed_db.py         # JSON → SQLite migration
  audit_verify.py    # Chain integrity verifier
docs/
  architecture.md    # Full system design
  adr/               # Architecture Decision Records
```

## Scaling to a portfolio company

See [docs/scale.md](docs/scale.md). The governance pattern is domain-agnostic: swap `loinc_rules.json`, set principals, point at a new database, deploy.

## Architecture deep-dive

See [docs/architecture.md](docs/architecture.md).
