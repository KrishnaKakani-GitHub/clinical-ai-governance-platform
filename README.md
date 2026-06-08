# FHIR MCP Server (your first MCP server)

A small, runnable MCP server for learning the pattern: **synthetic** FHIR-shaped
data, read tools, and a **gated write** (agent proposes → human approves →
commit), with **structured audit logging** on every call.

> All data here is synthetic. This is a development/learning server. It is NOT
> production-ready (no auth, JSON file instead of a database, audit logs to
> stderr instead of a tamper-evident sink). See "What's deliberately missing."

## What it does

Tools Claude can call:
- `list_patients` — list synthetic patient IDs
- `get_patient` — read one patient's demographics
- `list_observations` — list a patient's observations
- `propose_observation` — **stage** a new observation (does NOT commit)
- `list_pending_writes` — show writes awaiting approval
- `approve_write` — **human-in-the-loop gate**: commit a staged write
- `reject_write` — reject a staged write

The agent can read and propose. It **cannot** commit a write — only
`approve_write`/`reject_write`, meant to be driven by a human, can.

## Mental model

Your server is a passive provider. Claude Code launches it as a subprocess,
asks "what tools do you have?", and calls them. The server never calls Claude.
Communication is over **stdio** (stdin/stdout) — which is why audit logs go to
**stderr**, so they never collide with protocol traffic.

## Setup

```bash
cd fhir-mcp
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run the tests

```bash
pytest -q
```

## Run the server directly (sanity check)

```bash
python -m fhir_mcp.server
```
It will wait for a client on stdio (Ctrl-C to exit). Normal — it's passive.

## Connect to Claude Code

From your project directory:

```bash
claude mcp add fhir-synthetic -- /full/path/to/fhir-mcp/.venv/bin/python -m fhir_mcp.server
```

Notes:
- Use the **venv's** python (full path) so dependencies resolve.
- `--` separates Claude's flags from the command that launches your server.
- Default scope is local (just you). Add `--scope project` to share via
  `.mcp.json`, or `--scope user` for all your projects.
- Set the agent identity / data path via env if needed:
  `claude mcp add fhir-synthetic --env FHIR_MCP_ACTOR=agent:dev -- <python> -m fhir_mcp.server`

Verify:
```bash
claude mcp list          # should show fhir-synthetic
```
Inside a Claude Code session, type `/mcp` to see/reconnect servers. Then ask
something like: *"List the patients, then read pat-001."*

## In VS Code

The Claude Code extension uses the same configuration. Once `claude mcp add`
has registered the server, the tools are available in the extension's Claude
Code sessions too — open the Spark panel and ask it to use the tools.

## Configuration

- `FHIR_MCP_DATA` — path to the JSON data file (defaults to `data/synthetic_patients.json`)
- `FHIR_MCP_ACTOR` — the agent's audit identity (defaults to `agent:dev`)

## What's deliberately missing (the path to production)

This is v1. To harden, in order:
1. **Deterministic validation layer** — richer clinical checks (valid LOINC,
   value ranges) before a write can even be staged. (Basic checks exist in
   `store.stage_write`.)
2. **Auth** — authenticate the caller so the audit `actor` can't be spoofed.
3. **Tamper-evident audit sink** — append-only store, not stderr.
4. **Real persistence** — replace the JSON file with a transactional database.
5. **Remote HTTPS hosting** — only needed to connect as a *claude.ai* web
   connector; not needed for local Claude Code use.

## Files

```
src/fhir_mcp/
  models.py   # Pydantic v2 models (FHIR subset + pending-write records)
  store.py    # the only module that touches data; holds the write gate
  audit.py    # structured audit logging (IDs only, never contents)
  server.py   # FastMCP server: the tools Claude calls
tests/
  test_store.py
data/
  synthetic_patients.json   # editable synthetic data
```
