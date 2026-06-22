# Clinical AI Governance Platform — Architecture

> v2.0 | Day 1 of 7

---

## 1. Problem

Healthcare operators deploying LLM agents face a structural failure mode:
**agents can write unvalidated clinical data**. The consequences range from
incorrect records to patient safety incidents, regulatory violations
(HIPAA, 21 CFR Part 11), and liability exposure.

Existing approaches fail in one of two ways:

- **No guardrails**: agents write directly. Fast, but clinically unsafe.
- **Human bottleneck**: every action requires human review. Safe, but doesn't scale.

This platform takes a third path: **deterministic validation at the gate,
human approval only at commit**. The agent handles research and proposal.
The deterministic layer enforces clinical rules. The human makes the final
call. Every step is audited with a tamper-evident chain.

---

## 2. Core Invariant

```
Agents propose.  A deterministic layer validates.  A human approves.  Every action is audited.
```

This invariant is enforced at the code level, not by convention:

- `store.stage_write()` runs deterministic validation before any write can
  be queued. A proposal that fails clinical checks is rejected before it
  enters the queue — not after review.
- `store.approve_write()` is the only path that writes to the database. It
  requires an explicit, verified `approver` identity.
- Agent-callable tools cannot call `approve_write`. That tool requires an
  identity in `FHIR_MCP_APPROVERS`, which must be disjoint from
  `FHIR_MCP_PRINCIPALS` (agent actors).

---

## 3. System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│               Clinical AI Governance Platform                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Agent SDK Orchestration  (src/clinical_agent/)  [Day 4]        │ │
│  │                                                                  │ │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────────┐          │ │
│  │  │ Reader     │─▶│ RAG        │─▶│ Proposal      │          │ │
│  │  │ Subagent   │  │ Subagent   │  │ Subagent      │          │ │
│  │  └────────────┘  └────────────┘  └───────────────┘          │ │
│  │  Hooks: PostToolUse → audit + cost/latency tracking              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                    │ calls tools via MCP                           │
│                    ▼                                                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  MCP Server  (src/fhir_mcp/server.py)  FastMCP 3.x              │ │
│  │  Tools:  list_patients · get_patient · list_observations         │ │
│  │           propose_observation · list_pending_writes             │ │
│  │           approve_write · reject_write                          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                    │                                                │
│                    ▼                                                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Deterministic Validation  (validator.py)  [Day 2]              │ │
│  │  LOINC code registry · value ranges · unit checks               │ │
│  │  Called in store.stage_write() before the write can be queued   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                    │                                                │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐ │
│  │ SQLite         │  │ ChromaDB       │  │ Audit Chain     │ │
│  │ patients       │  │ [Day 3]        │  │ append-only JSONL│ │
│  │ observations   │  │ guidelines     │  │ SHA-256 hash    │ │
│  │ WAL + FK       │  │ embeddings     │  │ chain           │ │
│  └────────────────┘  └────────────────┘  └─────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Layer Descriptions

### 4.1 Agent SDK Orchestration (Day 4)

Uses `claude-agent-sdk` (`query()`) with three subagents:

**Reader Subagent** (`allowed_tools: [list_patients, get_patient, list_observations]`) —
Reads patient data. Runs in parallel for multiple patients (parallelization workflow).

**RAG Subagent** (`allowed_tools: [search_guidelines]`) — Searches `data/clinical_guidelines.json`
via the hybrid BM25 + ChromaDB layer. Returns ranked guidelines with scores.

**Proposal Subagent** (`allowed_tools: [propose_observation]`) — Given patient context + guidelines,
generates a `ClinicalProposal` with structured Pydantic output, confidence score, and cited guidelines.
For proposals with values outside guideline ranges, routing sends this subagent into extended thinking
mode (`thinking: {type: enabled, budget_tokens: 5000}`) before finalising.

SDK hooks (`PostToolUse`) fire after every tool call, writing to the tamper-evident audit chain and
tracking latency and token cost per call.

### 4.2 MCP Server

Passive provider. Each tool:
1. Calls `verify_agent_actor()` or `verify_approver()` (auth layer)
2. Delegates to `store` (data layer)
3. Emits an audit record on both success and error paths

No business logic in `server.py`. Strict layering: server → store → models.

### 4.3 Deterministic Validation Layer (Day 2)

`validator.py` is called inside `store.stage_write()`, before a proposal can be queued:

```
propose_observation(patient_id, code, value, unit, ...)
  → store.stage_write(proposed)
      → validator.validate_observation(proposed)   ← deterministic gate
          → if violations: raise StoreError         ← rejected before queue
      → queue in _pending (in-memory only)
```

Rules live in `data/loinc_rules.json`. Example:
```json
{
  "8867-4": {
    "display": "Heart rate",
    "min": 20, "max": 300,
    "unit": "/min",
    "reject_below": 0,
    "flag_above": 200
  }
}
```

This layer is not best-effort — it is a hard gate that cannot be bypassed by
the agent.

### 4.4 Storage

**SQLite** (`data/fhir.db`):

```sql
patients     (id PK, name, birth_date, gender, mrn UNIQUE)
observations (id PK, patient_id FK, code, display, value, unit, effective_date)
```

WAL mode + foreign keys. The pending-write queue (`_pending`) is in-memory only —
unapproved proposals are never persisted. A server restart clears all pending writes;
this is intentional (stale proposals should not outlive the session).

**ChromaDB** (Day 3): local vector DB for clinical guidelines. Production upgrade:
pgvector on the same Postgres instance. See [ADR-004](adr/004-chromadb-to-pgvector-path.md).

### 4.5 Audit Chain

Each record is a JSON line. `prev_hash` = SHA-256 of the previous line:

```
Record 1: {ts, actor, action, ..., "prev_hash": "GENESIS"}  → hash H1
Record 2: {ts, actor, action, ..., "prev_hash": H1}          → hash H2
Record 3: {ts, actor, action, ..., "prev_hash": H2}          → hash H3
```

Mutating any field changes its hash, which breaks the next record's `prev_hash` check.
Verify: `python scripts/audit_verify.py data/audit.jsonl`

### 4.6 Auth Layer

| Env var | Controls | Default |
|---|---|---|
| `FHIR_MCP_PRINCIPALS` | Which agent actor IDs can call tools | unset = dev mode |
| `FHIR_MCP_APPROVERS` | Which human IDs can approve/reject | unset = dev mode |

The two sets must be disjoint — an agent principal must not appear in `FHIR_MCP_APPROVERS`.
Enforced by the test `test_agent_cannot_self_approve`.

---

## 5. Write Gate Sequence

```
Agent                    MCP Server              Store              DB
  │                          │                     │               │
  │  propose_observation()   │                     │               │
  │────────────────────────▶│                     │               │
  │                          │  verify_agent_actor  │               │
  │                          │  stage_write()       │               │
  │                          │────────────────────▶│               │
  │                          │                     │  validate()   │
  │                          │                     │─ REJECT ─────▶ StoreError
  │                          │                     │  queue _pending│
  │                          │◄────────────────────│               │
  │◄─────────────────────────│                     │               │
  │  PendingWrite (write_id)  │                     │               │
  │                          │                     │               │
  │     (human reviews …)    │                     │               │
  │                          │                     │               │
Human  approve_write()        │                     │               │
  │────────────────────────▶│                     │               │
  │                          │  verify_approver     │               │
  │                          │  approve_write()     │               │
  │                          │────────────────────▶│               │
  │                          │                     │  INSERT obs   │
  │                          │                     │──────────────▶│
  │                          │◄────────────────────│               │
Human◄─────────────────────────│                     │               │
  │  Observation committed    │                     │               │
```

---

## 6. Security Model

| Threat | Mitigation |
|---|---|
| Agent spoofs approver identity | `FHIR_MCP_APPROVERS` ≠ `FHIR_MCP_PRINCIPALS`; `verify_approver()` enforces |
| Agent bypasses validation | `stage_write()` calls `validate_observation()` before queuing |
| Agent commits directly | `approve_write` requires identity in `FHIR_MCP_APPROVERS` |
| Audit log tampered | SHA-256 hash chain; any mutation breaks the chain |
| Stale proposals leak into DB | Pending writes are in-memory only; cleared on restart |
| Double-commit | `approve_write()` checks `status == pending`; second call raises `StoreError` |
| PHI in audit log | Audit records contain IDs only — never names, values, or note contents |

---

## 7. Data Model

```
Patient                         Observation
─────────────────────────────   ─────────────────────────────
id          TEXT PK             id              TEXT PK
name        TEXT                patient_id      TEXT FK→patients.id
birth_date  TEXT (ISO date)     code            TEXT (LOINC)
gender      TEXT (enum)         display         TEXT
mrn         TEXT UNIQUE         value           REAL
                                unit            TEXT
                                effective_date  TEXT (ISO date)

PendingWrite (in-memory only, never persisted until approved)
──────────────────────────────────────
 write_id        str (pw-{uuid[:8]})
 resource_type  "Observation"
 proposed       ProposedObservation
 status          pending | approved | rejected
 created_at     datetime (UTC)
 decided_at     datetime | None
 decided_by     str | None
```

---

## 8. Scaling to the Portfolio

The governance pattern is domain-agnostic. Deploying at a new portfolio company:

1. **Swap `data/loinc_rules.json`** — define clinical codes + value ranges for this domain
2. **Set `FHIR_MCP_PRINCIPALS`** — wire to the company's identity provider
3. **Set `FHIR_MCP_APPROVERS`** — define the human approval group
4. **Set `FHIR_MCP_DB`** — point at the company's database (SQLite → Postgres path: see ADR-002)
5. **Set `FHIR_MCP_AUDIT_FILE`** — point at the company's audit store
6. **Deploy `http_server.py`** (Day 7) — connect as a claude.ai web connector

The agent orchestration layer (`clinical_agent/`) is parameterised by system prompt
and MCP server URL, so multiple deployments can share the same orchestrator code.

See [docs/scale.md](scale.md) for the full portfolio playbook.

---

## 9. Production Hardening Status

| Item | Status |
|---|---|
| SQLite persistence (WAL, FK) | ✓ Done |
| Tamper-evident audit (SHA-256 chain) | ✓ Done |
| Auth (principal + approver verification) | ✓ Done |
| Deterministic validation (LOINC + ranges) | Day 2 |
| RAG (BM25 + ChromaDB) | Day 3 |
| Agent SDK orchestration + hooks | Day 4 |
| Clinical NLP + confidence scoring | Day 5 |
| Eval harness + CI regression | Day 6 |
| HTTP server + TLS + Railway deploy | Day 7 |

---

## 10. Decision Records

- [ADR-001](adr/001-mcp-over-direct-api.md) — MCP over direct Anthropic API tool definitions
- [ADR-002](adr/002-sqlite-over-json.md) — SQLite over JSON file storage
- [ADR-003](adr/003-agent-sdk-orchestration.md) — Claude Agent SDK over manual tool loop
- [ADR-004](adr/004-chromadb-to-pgvector-path.md) — ChromaDB (dev) → pgvector (production)
