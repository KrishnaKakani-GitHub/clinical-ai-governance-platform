# ADR-004: ChromaDB (dev) → pgvector (production) migration path

**Status:** Accepted (Day 3)

## Context

The RAG layer (Day 3) requires vector storage for clinical guideline embeddings.
Options:

- **ChromaDB** (embedded, local): no infrastructure, Python-native, installs
  ONNX runtime for default embeddings.
- **pgvector** (Postgres extension): same instance as clinical data, SQL-native,
  production-grade.
- **Hosted** (Pinecone, Weaviate): no infrastructure but external dependency,
  cost, and a third-party PHI data processor.

## Decision

ChromaDB for development and demo; pgvector for production. Migration is
explicit and documented below.

## Rationale

**ChromaDB for dev** eliminates infrastructure during the build week. No separate
process, no Postgres instance, batteries included (ONNX-based embeddings).

**pgvector for production** avoids a separate service. The same Postgres instance
that holds clinical data can host the `vector` extension, keeping PHI in one
transactional store with one audit boundary.

**Hosted services are ruled out** because they require shipping clinical content
(even synthetic, in dev) to a third-party — a pattern we want to avoid
establishing even in demo mode.

## Migration path

```python
# 1. Export from ChromaDB
collection = chroma_client.get_collection("clinical_guidelines")
result = collection.get(include=["embeddings", "documents", "metadatas"])

# 2. Enable pgvector on Postgres
# CREATE EXTENSION IF NOT EXISTS vector;
# CREATE TABLE guideline_embeddings (
#     id TEXT PRIMARY KEY,
#     document TEXT,
#     metadata JSONB,
#     embedding vector(384)   -- dimension matches the model
# );

# 3. Insert
for id_, doc, meta, emb in zip(
    result["ids"], result["documents"],
    result["metadatas"], result["embeddings"]
):
    cursor.execute(
        "INSERT INTO guideline_embeddings VALUES (%s, %s, %s, %s)",
        (id_, doc, json.dumps(meta), emb)
    )

# 4. Swap client in rag.py
# Replace: chroma_client.query(...)
# With:    cursor.execute("SELECT ... ORDER BY embedding <=> %s LIMIT %s", (query_vec, k))
```

Application code change: ~15 lines in `rag.py`. All upstream code (`orchestrator.py`,
`server.py`) is unaffected — `rag.py` presents the same `search_guidelines(query, k)` interface.

## Consequences

- `chromadb>=0.5` adds ~200MB to the install (ONNX runtime for default embeddings).
- For production, swap to `psycopg2-binary` + `pgvector` (much lighter).
- The embedding model dimension (384 for `all-MiniLM-L6-v2` default) must match
  the pgvector column definition.
