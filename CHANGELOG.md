# Changelog

## [2.0.0] — 2026-06-23 (Day 1)

Rebrand: fhir-synthetic-mcp → **Clinical AI Governance Platform**.

### Added
- `src/fhir_mcp/auth.py` — principal and approver verification
  (`FHIR_MCP_PRINCIPALS`, `FHIR_MCP_APPROVERS` env vars)
- `src/clinical_agent/` — Agent SDK orchestration package (skeleton, Day 4)
- `scripts/seed_db.py` — JSON → SQLite migration script
- `scripts/audit_verify.py` — tamper-evident chain integrity verifier
- `tests/test_audit_chain.py` — chain link, tamper detection, insertion detection
- `tests/test_auth.py` — principal/approver verification, dev mode, self-approve guard
- `docs/architecture.md` — full system design with diagrams, security model, sequence diagram
- `docs/adr/` — four Architecture Decision Records (MCP, SQLite, Agent SDK, ChromaDB)
- `docs/scale.md` — portfolio company deployment playbook

### Changed
- `store.py` — replaced JSON file with SQLite (WAL mode, FK enforcement);
  same public interface; `import_from_json()` added for seeding
- `audit.py` — SHA-256 hash chain replacing plain stderr logging; chain tip
  persists across restarts; `verify_chain()` exported
- `server.py` — `verify_agent_actor()` + `verify_approver()` added to every tool
- `tests/test_store.py` — fixture migrated from file-copy to SQLite seed;
  `test_approve_commits_and_persists` now verifies durability via a second store instance
- `pyproject.toml` — renamed to `clinical-ai-governance-platform` v2.0.0;
  all future deps added (anthropic, claude-agent-sdk, rank-bm25, chromadb, fastapi)

### Removed
- JSON file persistence (`_data_path`, `_persist()`, `DataStore` root document)
  — replaced by SQLite. `DataStore` model kept for `import_from_json()` seeding.

## [1.0.0] — 2026-06-08

Initial release: `fhir-synthetic-mcp`. FastMCP server, synthetic FHIR data,
gated write pattern, basic audit logging to stderr.
