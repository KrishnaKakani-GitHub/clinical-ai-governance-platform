# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A learning-oriented MCP server exposing **synthetic** FHIR-shaped data over stdio. It demonstrates one core pattern: agents can read and *propose* writes, but only a human-driven approval tool can commit them, and every tool call emits a structured audit line. All data is synthetic; this is explicitly not production-ready (no auth, JSON file instead of a DB, audit to stderr).

## Commands

```bash
# Setup (editable install with dev deps)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Tests
pytest -q                              # all tests
pytest tests/test_store.py::test_approve_commits_and_persists   # single test

# Run the server directly (sanity check — it blocks waiting for a stdio client)
python -m fhir_mcp.server

# Register with Claude Code (use the venv's python by full path)
claude mcp add fhir-synthetic -- /full/path/to/.venv/bin/python -m fhir_mcp.server
```

`pyproject.toml` sets `pythonpath = ["src"]`, so tests import `fhir_mcp.*` without installing — but the editable install is still needed for the `fastmcp`/`pydantic` deps.

## Architecture

The dependency direction is strict and the layering is the whole point:

```
server.py  →  store.py  →  models.py
   ↓
audit.py   (called from every tool in server.py)
```

- **`store.py` is the only module that touches data.** Every read and the entire write gate live here. This is deliberate — all PHI touchpoints sit in one auditable place. When adding data behavior, it belongs here, not in `server.py`.
- **`server.py` is a thin FastMCP wrapper.** Each `@mcp.tool()` function validates input into a Pydantic model, delegates to `store`, and emits an `audit(...)` call on both success and error paths. It holds no business logic. Tests target `store` directly because that's where the safety-critical logic is.
- **`models.py`** is a simplified *subset* of FHIR (Patient, Observation) plus the gated-write records (`ProposedObservation`, `PendingWrite`). Not spec-complete FHIR by design.
- **`audit.py`** emits one JSON line per call to **stderr** (never stdout — stdout is the JSON-RPC protocol channel for stdio transport).

### The write gate (the central invariant)

`propose → list_pending → approve/reject`. This is what makes the server interesting; preserve it when changing tools.

- `propose_observation` calls `store.stage_write`, which runs **deterministic validation** (patient must exist, value ≥ 0, code non-empty) and queues the write **in memory only**. Unapproved proposals are intentionally never persisted, so a proposal can't leak into the data file.
- Agent-callable tools (`propose_observation`, `list_pending_writes`, read tools) can never commit. Only `approve_write` writes to disk, and only after a status check prevents double-commit. `approve_write`/`reject_write` take an explicit `approver` — and the audit `actor` for those is the human approver, not the agent.
- The deterministic validation gate in `stage_write` is the designated extension point for richer clinical checks (LOINC validity, value ranges) — see "What's deliberately missing" in the README.

### Audit / PHI conventions

- Audit records log **IDs and actions only — never record contents** (no names, no observation values). Maintain this when adding audit calls.
- Every tool wraps its `store` call in try/except and audits the error path with `outcome="error"` before re-raising. Follow this shape for new tools.

## Configuration (env vars)

- `FHIR_MCP_DATA` — path to the JSON data file (default `data/synthetic_patients.json`).
- `FHIR_MCP_ACTOR` — the agent's audit identity (default `agent:dev`). In a real deployment this would come from authenticated identity, not a constant.

## Gotchas

- The server is a **passive provider** — it never calls Claude. Running `python -m fhir_mcp.server` appearing to "hang" is normal; it's waiting on stdio.
- `_DATA_PATH` resolves relative to the repo via `parents[2]` from `server.py`; the test fixture copies the data file to a tmp path so tests never mutate `data/synthetic_patients.json`.
- `.claude/` is gitignored.
