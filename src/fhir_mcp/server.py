"""FHIR MCP server — Clinical AI Governance Platform.

This is the file Claude Code and the Agent SDK launch. It defines:
  - 10 tools (3 read, 4 write-gate, 1 RAG search, 1 ClinicalTrials.gov, 1 Nemotron Parse)
  - 2 MCP resources (fhir://patient/{id}/summary, fhir://guidelines/index)
  - 2 MCP prompts (review_pending, patient_overview)

End-to-end pipeline (Day 9):
  Raw PDF/Doc
    → parse_clinical_document (Nemotron Parse)  → structured markdown
    → [nlp.py] extract_entities                  → ICD-10/LOINC/NPI
    → propose_observation (LOINC gate)            → staged write
    → approve_write (human gate)                  → committed
    → audit chain                                 → SHA-256 JSONL

PHI NOTE on Nemotron Parse:
  Cloud NIM endpoint: synthetic/de-identified documents only.
  Self-hosted NIM (NEMOTRON_PARSE_BASE_URL): safe for PHI.

The write gate invariant is preserved:
  - Agents can READ, SEARCH, PROPOSE, LOOK UP TRIALS, and PARSE DOCUMENTS
  - Only a verified human approver can COMMIT via approve_write

Run locally:   python -m fhir_mcp.server
Register:      claude mcp add clinical-governance -- python -m fhir_mcp.server
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .audit import audit
from .auth import AuthError, verify_agent_actor, verify_approver
from .models import ProposedObservation
from .parse import parse_document
from .rag import get_rag
from .store import FhirStore, StoreError
from .trials import search_trials_for_condition
from .validator import get_rules

_DB_PATH = Path(
    os.environ.get(
        "FHIR_MCP_DB",
        Path(__file__).resolve().parents[2] / "data" / "fhir.db",
    )
)

mcp = FastMCP("clinical-ai-governance")
store = FhirStore(_DB_PATH)
_AGENT_ACTOR = os.environ.get("FHIR_MCP_ACTOR", "agent:dev")


# --- Read tools ---------------------------------------------------------------


@mcp.tool()
def list_patients(reason: str) -> list[str]:
    """List available patient IDs. `reason`: why you need this list."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
    except AuthError as e:
        audit(actor=_AGENT_ACTOR, action="list_patients", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise
    ids = store.get_patient_ids()
    audit(actor=_AGENT_ACTOR, action="list_patients", reason=reason, target_ids=ids)
    return ids


@mcp.tool()
def get_patient(patient_id: str, reason: str) -> dict:
    """Read one patient's demographics. `reason` is recorded in the audit trail."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
        patient = store.get_patient(patient_id)
    except (AuthError, StoreError) as e:
        audit(actor=_AGENT_ACTOR, action="get_patient", reason=reason,
              target_ids=[patient_id], outcome="error", extra={"error": str(e)})
        raise
    audit(actor=_AGENT_ACTOR, action="get_patient", reason=reason,
          target_ids=[patient_id])
    return patient.model_dump(mode="json")


@mcp.tool()
def list_observations(patient_id: str, reason: str) -> list[dict]:
    """List a patient's observations. `reason` is audited."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
        obs = store.list_observations(patient_id)
    except (AuthError, StoreError) as e:
        audit(actor=_AGENT_ACTOR, action="list_observations", reason=reason,
              target_ids=[patient_id], outcome="error", extra={"error": str(e)})
        raise
    audit(actor=_AGENT_ACTOR, action="list_observations", reason=reason,
          target_ids=[patient_id])
    return [o.model_dump(mode="json") for o in obs]


# --- Nemotron Parse tool ------------------------------------------------------


@mcp.tool()
def parse_clinical_document(
    source: str,
    document_type: str = "clinical",
    reason: str = "",
) -> dict:
    """Parse a clinical document using Nemotron Parse (NVIDIA NIM).

    First stage of the end-to-end pipeline:
      parse_clinical_document → [extract entities via nlp.py] → propose_observation

    Nemotron Parse handles complex document layouts that defeat standard OCR:
    multi-column prior auth letters, table-heavy EOB statements, treatment plans
    with mixed prose and structured fields.

    Args:
        source: File path, public URL, or base64-encoded document bytes.
                For PHI documents, use a self-hosted NIM endpoint
                (set NEMOTRON_PARSE_BASE_URL) so content stays on-prem.
        document_type: One of 'clinical', 'prior_auth', 'eob',
                       'treatment_plan', 'lab_report'. Guides the parser.
        reason: Why you are parsing this document (audited).

    Returns:
        dict with 'structured_text' (markdown), token counts, and parse_method.

    PHI NOTE: If NVIDIA_API_KEY is set and document contains PHI, deploy
    NIM self-hosted and set NEMOTRON_PARSE_BASE_URL to the internal endpoint.
    """
    try:
        verify_agent_actor(_AGENT_ACTOR)
    except AuthError as e:
        audit(actor=_AGENT_ACTOR, action="parse_clinical_document", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise

    try:
        result = parse_document(source=source, document_type=document_type)
    except (ValueError, RuntimeError) as e:
        audit(actor=_AGENT_ACTOR, action="parse_clinical_document", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise

    audit(
        actor=_AGENT_ACTOR, action="parse_clinical_document", reason=reason,
        extra={
            "document_type": document_type,
            "parse_method": result.parse_method,
            "output_word_count": result.output_word_count,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            # PHI NOTE: source path logged but not content
            "source_type": "url" if str(source).startswith("http") else "file",
        },
    )
    return result.to_dict()


# --- RAG search tool ----------------------------------------------------------


@mcp.tool()
def search_guidelines(
    query: str,
    k: int = 4,
    loinc_codes: str = "",
    reason: str = "",
) -> list[dict]:
    """Search clinical guidelines using hybrid BM25 + semantic retrieval."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
    except AuthError as e:
        audit(actor=_AGENT_ACTOR, action="search_guidelines", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise

    k = min(max(1, k), 8)
    loinc_filter = [c.strip() for c in loinc_codes.split(",") if c.strip()] or None
    rag = get_rag()
    results = rag.search_guidelines(query, k=k, loinc_filter=loinc_filter)

    audit(actor=_AGENT_ACTOR, action="search_guidelines", reason=reason,
          extra={"query": query[:120], "k": k, "loinc_filter": loinc_filter,
                 "result_count": len(results)})
    return [
        {
            "rank": r["rank"], "score": r["score"],
            "id": r["guideline"]["id"], "title": r["guideline"]["title"],
            "source": r["guideline"]["source"],
            "condition": r["guideline"]["condition"],
            "loinc_codes": r["guideline"].get("loinc_codes", []),
            "content": r["guideline"]["content"],
            "key_thresholds": r["guideline"].get("key_thresholds", {}),
        }
        for r in results
    ]


# --- ClinicalTrials.gov tool --------------------------------------------------


@mcp.tool()
def search_clinical_trials(
    condition: str,
    loinc_codes: str = "",
    max_results: int = 5,
    reason: str = "",
) -> list[dict]:
    """Search ClinicalTrials.gov for recruiting trials matching a condition.

    Call when search_guidelines returns validation_warnings (flagged observations)
    to surface trials the patient may qualify for.
    PHI-safe: only condition strings transmitted externally.
    """
    try:
        verify_agent_actor(_AGENT_ACTOR)
    except AuthError as e:
        audit(actor=_AGENT_ACTOR, action="search_clinical_trials", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise

    max_results = min(max(1, max_results), 10)
    codes = [c.strip() for c in loinc_codes.split(",") if c.strip()]
    trials = search_trials_for_condition(
        condition=condition, loinc_codes=codes or None, max_results=max_results,
    )
    audit(actor=_AGENT_ACTOR, action="search_clinical_trials", reason=reason,
          extra={"condition": condition[:120], "loinc_codes": codes,
                 "result_count": len(trials), "phi_transmitted": False})
    return trials


# --- Gated write tools --------------------------------------------------------


@mcp.tool()
def propose_observation(
    patient_id: str, code: str, display: str,
    value: float, unit: str, effective_date: str, reason: str,
) -> dict:
    """Propose a new observation. Stages it for human approval; does NOT write."""
    proposed = ProposedObservation(
        patient_id=patient_id, code=code, display=display,
        value=value, unit=unit, effective_date=date.fromisoformat(effective_date),
    )
    try:
        verify_agent_actor(_AGENT_ACTOR)
        pending = store.stage_write(proposed)
    except (AuthError, StoreError, ValueError) as e:
        audit(actor=_AGENT_ACTOR, action="propose_observation", reason=reason,
              target_ids=[patient_id], outcome="error", extra={"error": str(e)})
        raise
    audit(actor=_AGENT_ACTOR, action="propose_observation", reason=reason,
          target_ids=[patient_id],
          extra={"write_id": pending.write_id, "status": "pending",
                 "has_warnings": bool(pending.validation_warnings)})
    return pending.model_dump(mode="json")


@mcp.tool()
def list_pending_writes(reason: str) -> list[dict]:
    """List writes awaiting human approval."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
    except AuthError as e:
        audit(actor=_AGENT_ACTOR, action="list_pending_writes", reason=reason,
              outcome="error", extra={"error": str(e)})
        raise
    pending = store.list_pending()
    audit(actor=_AGENT_ACTOR, action="list_pending_writes", reason=reason,
          target_ids=[p.write_id for p in pending])
    return [p.model_dump(mode="json") for p in pending]


@mcp.tool()
def approve_write(write_id: str, approver: str, reason: str) -> dict:
    """HUMAN-IN-THE-LOOP GATE. Commit a staged write."""
    try:
        verify_approver(approver)
        obs = store.approve_write(write_id, approver=approver)
    except (AuthError, StoreError) as e:
        audit(actor=approver, action="approve_write", reason=reason,
              target_ids=[write_id], outcome="error", extra={"error": str(e)})
        raise
    audit(actor=approver, action="approve_write", reason=reason,
          target_ids=[write_id, obs.id],
          extra={"committed_observation_id": obs.id})
    return obs.model_dump(mode="json")


@mcp.tool()
def reject_write(write_id: str, approver: str, reason: str) -> dict:
    """HUMAN-IN-THE-LOOP GATE. Reject a staged write."""
    try:
        verify_approver(approver)
        pending = store.reject_write(write_id, approver=approver)
    except (AuthError, StoreError) as e:
        audit(actor=approver, action="reject_write", reason=reason,
              target_ids=[write_id], outcome="error", extra={"error": str(e)})
        raise
    audit(actor=approver, action="reject_write", reason=reason,
          target_ids=[write_id], extra={"status": "rejected"})
    return pending.model_dump(mode="json")


# --- MCP Resources ------------------------------------------------------------


@mcp.resource("fhir://patient/{patient_id}/summary")
def patient_summary(patient_id: str) -> str:
    """FHIR patient summary as structured text."""
    try:
        verify_agent_actor(_AGENT_ACTOR)
        patient = store.get_patient(patient_id)
        observations = store.list_observations(patient_id)
    except (AuthError, StoreError) as e:
        return f"Error: {e}"
    audit(actor=_AGENT_ACTOR, action="read_patient_summary",
          reason="MCP resource request", target_ids=[patient_id])
    lines = [
        f"Patient: {patient.name} ({patient.id})",
        f"DOB: {patient.birth_date} | Gender: {patient.gender.value} | MRN: {patient.mrn}",
        "", "Observations:",
    ]
    if not observations:
        lines.append("  (none recorded)")
    else:
        for o in observations:
            lines.append(f"  [{o.effective_date}] {o.display} ({o.code}): {o.value} {o.unit}")
    return "\n".join(lines)


@mcp.resource("fhir://guidelines/index")
def guidelines_index() -> str:
    """Index of available clinical guidelines."""
    rag = get_rag()
    lines = ["Clinical Guidelines Index:", ""]
    for g in rag._guidelines:
        loinc = ", ".join(g.get("loinc_codes", [])) or "none"
        lines.append(f"  {g['id']}: {g['title']}")
        lines.append(f"    Source: {g['source']} | Condition: {g['condition']} | LOINC: {loinc}")
        lines.append("")
    return "\n".join(lines)


# --- MCP Prompts --------------------------------------------------------------


@mcp.prompt()
def review_pending() -> list[dict[str, Any]]:
    """Prompt template for a human reviewer approving/rejecting pending writes."""
    rules = get_rules()
    rule_summary = json.dumps(
        {
            code: {
                "display": r["display"],
                "range": f"{r.get('min', '?')}-{r.get('max', '?')} {r.get('unit', '')}",
                "flag_above": r.get("flag_above"),
            }
            for code, r in rules.items()
        },
        indent=2,
    )
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You are a clinical documentation reviewer for the Clinical AI Governance Platform. "
                        "Your role is to evaluate proposed FHIR observations staged for approval.\n\n"
                        "LOINC validation rules:\n"
                        f"<loinc_rules>\n{rule_summary}\n</loinc_rules>"
                    ),
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": "Review pending writes from `list_pending_writes` and recommend APPROVE or REJECT.",
                },
            ],
        }
    ]


@mcp.prompt()
def patient_overview(patient_id: str) -> list[dict[str, Any]]:
    """Prompt template for comprehensive patient overview."""
    summary = patient_summary(patient_id)
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You are a clinical AI assistant. Analyse the patient summary and identify: "
                        "(1) observations outside normal ranges, (2) trends warranting attention, "
                        "(3) missing but clinically indicated observations.\n\n"
                        f"<patient_summary>\n{summary}\n</patient_summary>"
                    ),
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "Please provide your clinical assessment."},
            ],
        }
    ]


if __name__ == "__main__":
    mcp.run()
