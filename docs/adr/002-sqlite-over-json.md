# ADR-002: SQLite over JSON file storage

**Status:** Accepted

## Context

v1 used a JSON file as the data store. Limitations that became blocking:

- **No transactions**: read-modify-write is not atomic; concurrent calls could
  corrupt the file or lose writes.
- **No constraints**: orphaned observations (patient_id referencing non-existent
  patient) are possible with JSON; foreign keys prevent this.
- **No indexing**: loading the entire file to find one patient's observations
  doesn't scale beyond a toy dataset.
- **No query capability**: filtering observations by code or date range requires
  in-memory iteration.

Options considered: JSON file, SQLite, PostgreSQL (with pgvector for Day 3 RAG).

## Decision

SQLite (`sqlite3` stdlib), WAL mode, foreign keys enforced. No ORM.

## Rationale

**ACID transactions without an external process.** SQLite's WAL mode allows
concurrent reads without blocking writes, matching the access pattern (many
reads, occasional writes via the approval gate).

**No additional dependencies.** `sqlite3` is stdlib. Adding SQLAlchemy or
another ORM would add complexity to a 4-table schema with no joins needed.

**Identical public interface to v1.** `FhirStore`'s methods are unchanged.
`server.py` required zero changes. `import_from_json()` handles migration
from the JSON fixture.

**Upgrade path to Postgres is straightforward.** The SQL dialect used is a
subset of PostgreSQL. To migrate: run the same schema DDL on Postgres, copy
rows, change the connection string. pgvector can then run on the same instance
(see ADR-004).

## Consequences

- `seed_db.py` is required before first run (`python scripts/seed_db.py`).
- Test fixtures change from file-copy to SQLite seed (`import_from_json`).
  All test cases pass with the new fixture — the interface is identical.
- `data/synthetic_patients.json` is kept as the seed source; `data/fhir.db`
  is gitignored.
