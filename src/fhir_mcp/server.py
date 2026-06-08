"""FHIR MCP server (FastMCP 3.x, stdio transport).

This is the file Claude Code launches. It defines the *tools* Claude can call.
Each tool is a normal Python function with a @mcp.tool() decorator; FastMCP
turns the type hints + docstring into the schema Claude sees.

Mental model: this server is a passive provider. Claude connects, asks "what
tools do you have?", and calls them. The server never calls Claude.

Run locally:   python -m fhir_mcp.server
Register:      claude mcp add fhir-synthetic -- python -m fhir_mcp.server
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastmcp import FastMCP

from .audit import audit
from .models import ProposedObservation
from .store import FhirStore, StoreError

# Data path is configurable via env var so you never hardcode a real path.
_DATA_PATH = Path(
    os.environ.get(
        "FHIR_MCP_DATA",
        Path(__file__).resolve().parents[2] / "data" / "synthetic_patients.json",
    )
)

mcp = FastMCP("fhir-synthetic")
store = FhirStore(_DATA_PATH)

# Who the agent is. In a real deployment this comes from authenticated identity,
# NOT a constant — the audit "actor" is only as trustworthy as your auth layer.
_AGENT_ACTOR = os.environ.get("FHIR_MCP_ACTOR", "agent:dev")


# --- Read tools ---------------------------------------------------------------


@mcp.tool()
def list_patients(reason: str) -> list[str]:
    """List available patient IDs (synthetic). `reason`: why you need this."""
    ids = store.get_patient_ids()
    audit(actor=_AGENT_ACTOR, action="list_patients", reason=reason, target_ids=ids)
    return ids


@mcp.tool()
def get_patient(patient_id: str, reason: str) -> dict:
    """Read one patient's demographics (synthetic PHI-shaped data).

    Returns minimal fields. `reason` is recorded in the audit trail.
    """
    try:
        patient = store.get_patient(patient_id)
    except StoreError as e:
        audit(
            actor=_AGENT_ACTOR,
            action="get_patient",
            reason=reason,
            target_ids=[patient_id],
            outcome="error",
            extra={"error": str(e)},
        )
        raise
    audit(
        actor=_AGENT_ACTOR,
        action="get_patient",
        reason=reason,
        target_ids=[patient_id],
    )
    return patient.model_dump(mode="json")


@mcp.tool()
def list_observations(patient_id: str, reason: str) -> list[dict]:
    """List a patient's observations (synthetic). `reason` is audited."""
    try:
        obs = store.list_observations(patient_id)
    except StoreError as e:
        audit(
            actor=_AGENT_ACTOR,
            action="list_observations",
            reason=reason,
            target_ids=[patient_id],
            outcome="error",
            extra={"error": str(e)},
        )
        raise
    audit(
        actor=_AGENT_ACTOR,
        action="list_observations",
        reason=reason,
        target_ids=[patient_id],
    )
    return [o.model_dump(mode="json") for o in obs]


# --- Gated write tools --------------------------------------------------------
# The agent can PROPOSE a write and LIST what's pending, but it CANNOT approve.
# Approval is a separate tool meant to be driven by a human in the loop.


@mcp.tool()
def propose_observation(
    patient_id: str,
    code: str,
    display: str,
    value: float,
    unit: str,
    effective_date: str,
    reason: str,
) -> dict:
    """Propose a new observation. Stages it for human approval; does NOT write.

    Returns a pending-write ticket (write_id). A human must call
    `approve_write` before anything is committed to the data file.
    `effective_date` is ISO format YYYY-MM-DD.
    """
    proposed = ProposedObservation(
        patient_id=patient_id,
        code=code,
        display=display,
        value=value,
        unit=unit,
        effective_date=date.fromisoformat(effective_date),
    )
    try:
        pending = store.stage_write(proposed)
    except (StoreError, ValueError) as e:
        audit(
            actor=_AGENT_ACTOR,
            action="propose_observation",
            reason=reason,
            target_ids=[patient_id],
            outcome="error",
            extra={"error": str(e)},
        )
        raise
    audit(
        actor=_AGENT_ACTOR,
        action="propose_observation",
        reason=reason,
        target_ids=[patient_id],
        extra={"write_id": pending.write_id, "status": "pending"},
    )
    return pending.model_dump(mode="json")


@mcp.tool()
def list_pending_writes(reason: str) -> list[dict]:
    """List writes awaiting human approval. For the reviewer's eyes."""
    pending = store.list_pending()
    audit(
        actor=_AGENT_ACTOR,
        action="list_pending_writes",
        reason=reason,
        target_ids=[p.write_id for p in pending],
    )
    return [p.model_dump(mode="json") for p in pending]


@mcp.tool()
def approve_write(write_id: str, approver: str, reason: str) -> dict:
    """HUMAN-IN-THE-LOOP GATE. Commit a staged write.

    `approver` must identify the human authorising this. This is the only
    path that writes patient data to the store. Use deliberately.
    """
    try:
        obs = store.approve_write(write_id, approver=approver)
    except StoreError as e:
        audit(
            actor=approver,
            action="approve_write",
            reason=reason,
            target_ids=[write_id],
            outcome="error",
            extra={"error": str(e)},
        )
        raise
    audit(
        actor=approver,  # the HUMAN is the actor here, not the agent
        action="approve_write",
        reason=reason,
        target_ids=[write_id, obs.id],
        extra={"committed_observation_id": obs.id},
    )
    return obs.model_dump(mode="json")


@mcp.tool()
def reject_write(write_id: str, approver: str, reason: str) -> dict:
    """HUMAN-IN-THE-LOOP GATE. Reject a staged write (nothing is committed)."""
    pending = store.reject_write(write_id, approver=approver)
    audit(
        actor=approver,
        action="reject_write",
        reason=reason,
        target_ids=[write_id],
        extra={"status": "rejected"},
    )
    return pending.model_dump(mode="json")


if __name__ == "__main__":
    # Default transport is stdio: Claude Code launches this as a subprocess.
    mcp.run()
