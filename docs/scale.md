# Portfolio Company Playbook

The Clinical AI Governance Platform is a reusable framework. This document
describes how to deploy it at a new portfolio company in one working day.

## What stays the same

- The governance pattern: propose → validate → approve → audit
- The MCP server interface (7 tools, same signatures)
- The Agent SDK orchestration code
- The eval harness structure

## What you configure per-company

### 1. Clinical domain (`data/loinc_rules.json`)

Define the LOINC codes relevant to the company's clinical workflow and their
acceptable value ranges:

```json
{
  "2339-0": {
    "display": "Glucose [Mass/volume] in Blood",
    "min": 20, "max": 600,
    "unit": "mg/dL",
    "reject_below": 0,
    "flag_above": 400,
    "clinical_note": "Values above 400 require immediate clinical review."
  }
}
```

### 2. Identity (`FHIR_MCP_PRINCIPALS`, `FHIR_MCP_APPROVERS`)

Wire to the company's identity provider (SAML, OIDC, or API keys):

```bash
export FHIR_MCP_PRINCIPALS="agent:copilot-prod,agent:copilot-staging"
export FHIR_MCP_APPROVERS="dr.johnson@company.com,dr.lee@company.com"
```

### 3. Database (`FHIR_MCP_DB`)

For production, migrate from SQLite to Postgres:

```bash
# Run schema on Postgres
psql -c "CREATE TABLE patients (...); CREATE TABLE observations (...);"
# Seed from existing data
python scripts/seed_db.py  # or write a custom seeder
```

Then set:
```bash
export FHIR_MCP_DB=postgresql://user:pass@host/clinical_db
```
(Store adapter update in `store.py`: swap `sqlite3.connect()` for `psycopg2.connect()`.)

### 4. Audit store (`FHIR_MCP_AUDIT_FILE`)

For tamper-evidence in production, point at an append-only log store:

```bash
export FHIR_MCP_AUDIT_FILE=/var/log/clinical-governance/audit.jsonl
```

Cron job to verify chain daily:
```bash
0 6 * * * python /app/scripts/audit_verify.py $FHIR_MCP_AUDIT_FILE
```

### 5. Deploy the HTTP server (`http_server.py`, Day 7)

For remote access (claude.ai web connector):

```bash
docker build -t clinical-governance .
docker run -e FHIR_MCP_DB=... -e ANTHROPIC_API_KEY=... -p 8080:8080 clinical-governance
```

Then in claude.ai: Settings → Connectors → Add → `https://your-deployment/mcp`

### 6. Eval golden dataset (`evals/golden_dataset.json`)

Add 25+ test cases specific to the company's clinical workflows. The eval runner
(Day 6) will measure accuracy, false-negative rate, and cost against these cases
on every CI push.

## Estimated deployment time

| Step | Time |
|---|---|
| loinc_rules.json | 2-4 hours (clinical SME review) |
| Identity wiring | 1-2 hours |
| Database migration | 2-4 hours |
| Audit store setup | 1 hour |
| HTTP deployment | 1-2 hours |
| Golden dataset | 4-8 hours (requires real clinical cases) |
| **Total** | **~1.5 days** |
