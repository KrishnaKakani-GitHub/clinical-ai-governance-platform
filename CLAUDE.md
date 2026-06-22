# Clinical AI Governance Platform — CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What this is

A production-grade MCP server + Agent SDK orchestration layer implementing a
clinical AI governance pattern: **agents propose → deterministic layer validates →
human approves → every action audited with a tamper-evident chain**.

All patient and observation data is synthetic. This is not connected to any real
clinical system.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/seed_db.py   # initialise SQLite DB from JSON fixture

# Tests
pytest -q                              # all tests
pytest tests/test_store.py             # store only
pytest tests/test_audit_chain.py       # audit chain only
pytest tests/test_auth.py              # auth only

# Run the MCP server (blocks on stdio — normal)
python -m fhir_mcp.server

# Register with Claude Code
claude mcp add clinical-governance -- /full/path/.venv/bin/python -m fhir_mcp.server

# Verify audit chain
python scripts/audit_verify.py data/audit.jsonl
```

## Architecture (strict dependency direction)

```
server.py  →  store.py    →  models.py
              validator.py  (called from store.stage_write, Day 2)
   ↓
audit.py   (called from every tool in server.py)
auth.py    (called from every tool in server.py)
```

- **`store.py` is the only module that touches the database.** All PHI touchpoints
  are here. When adding data behaviour, it belongs here.
- **`server.py` is a thin FastMCP wrapper.** Each `@mcp.tool()` validates identity
  (auth), delegates to store, and audits success + error paths. No business logic.
- **`audit.py`** is append-only + tamper-evident. Never write to stdout (protocol
  channel). Use stderr or `FHIR_MCP_AUDIT_FILE`.
- **`auth.py`** reads env vars at call time (not module load time) so tests can
  monkeypatch without reloading the module.

## The write gate (preserve this invariant)

`propose → list_pending → approve/reject`. This is the core safety property.

- `propose_observation` → `store.stage_write()` → deterministic validation →
  queued in memory only (never persisted until approved)
- Only `approve_write` writes to the database, and only after `verify_approver()`
- `_pending` dict is intentionally NOT persisted; stale proposals don't survive restart

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `FHIR_MCP_DB` | `data/fhir.db` | SQLite database path |
| `FHIR_MCP_ACTOR` | `agent:dev` | Agent audit identity |
| `FHIR_MCP_AUDIT_FILE` | stderr | Audit JSONL path |
| `FHIR_MCP_PRINCIPALS` | unset | Allowed agent actor IDs (unset = dev mode) |
| `FHIR_MCP_APPROVERS` | unset | Allowed human approver IDs (unset = dev mode) |

## PHI conventions

- Audit records log IDs and actions only — never record names, values, or note contents
- `store.py` is the PHI boundary. Nothing outside it reads raw records.
- Use synthetic/de-identified data in all examples
- PHI minimisation: prefer references/IDs over raw records in any new code

## Day-by-day build plan

- Day 1 ✓ — SQLite store, tamper-evident audit, auth layer
- Day 2 — LOINC validator + clinical data (guidelines, notes)
- Day 3 — RAG: BM25 + ChromaDB hybrid over clinical guidelines
- Day 4 — Agent SDK orchestration (Reader/RAG/Proposal subagents, hooks)
- Day 5 — Clinical NLP entity extraction + calibrated confidence scoring
- Day 6 — Eval harness: golden dataset, LLM-as-judge, GitHub Actions CI
- Day 7 — HTTP server (FastAPI SSE), Dockerfile, Railway deploy

## Gotchas

- The server blocks on stdio — this is normal passive-provider behaviour
- `fhir.db` must be seeded before the server starts: `python scripts/seed_db.py`
- `_AUDIT_PATH` is resolved at module import time; tests monkeypatch the module
  attribute directly (no reload needed since auth reads env vars at call time)
- `.claude/` is gitignored
