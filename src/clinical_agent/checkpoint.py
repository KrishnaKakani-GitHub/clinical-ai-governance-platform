"""CheckpointStore — persist stage outputs and resume interrupted workflows.

Checkpoint files are written to FHIR_MCP_CHECKPOINT_DIR (default: ./checkpoints/).
One file per workflow run: {patient_id}-{workflow_id}.json

Format::

    {
      "workflow_id": "uuid4",
      "patient_id": "pat-001",
      "actor": "orchestrator:prod",
      "started_at": "2026-06-23T03:00:00Z",
      "plan": { <WorkflowPlan dict> },
      "stages": {
        "intake": {"output": "...", "completed_at": "2026-06-23T03:00:01Z"},
        "evidence_rag": {"output": "...", "completed_at": "..."},
        ...
      }
    }

Resume: call CheckpointStore.load(checkpoint_id) to get a checkpoint, then
pass checkpoint_id to run_workflow() or run_workflow_stream(). The orchestrator
skips stages that already have a completed_at timestamp.

PHI NOTE: Checkpoint files contain stage outputs, which may include de-identified
patient context (structured JSON from the Intake agent). Apply the same access
controls as FHIR_MCP_DB. Never write checkpoint files to a shared or world-readable
directory. Set FHIR_MCP_CHECKPOINT_DIR to a secrets-manager-backed path in prod.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("clinical_agent.checkpoint")

_DEFAULT_CHECKPOINT_DIR = os.environ.get(
    "FHIR_MCP_CHECKPOINT_DIR", "./checkpoints"
)

# Ordered list of stage keys — used to determine resume point
STAGE_ORDER = [
    "plan",
    "intake",
    "evidence_rag",
    "evidence_trials",
    "reasoning",
    "refuter",
    "critic",
    "compliance",
]


class CheckpointStore:
    """Read/write workflow checkpoints to disk.

    Usage::

        # Start a new workflow
        store = CheckpointStore(patient_id="pat-001", actor="orchestrator:prod")
        store.save_stage("intake", intake_output)
        store.save_stage("evidence_rag", rag_output)

        # Later: resume after crash
        store = CheckpointStore.load(store.checkpoint_id)
        completed = store.completed_stages()
        # {"intake": "...", "evidence_rag": "..."}
    """

    def __init__(
        self,
        patient_id: str,
        actor: str,
        checkpoint_id: str | None = None,
        checkpoint_dir: str | None = None,
    ) -> None:
        self.patient_id = patient_id
        self.actor = actor
        self.checkpoint_id = checkpoint_id or str(uuid.uuid4())
        self._dir = Path(checkpoint_dir or _DEFAULT_CHECKPOINT_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{patient_id}-{self.checkpoint_id}.json"
        self._data: dict[str, Any] = self._load_or_init()

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, checkpoint_id: str, checkpoint_dir: str | None = None) -> "CheckpointStore":
        """Load an existing checkpoint by ID. Raises FileNotFoundError if not found."""
        directory = Path(checkpoint_dir or _DEFAULT_CHECKPOINT_DIR)
        matches = list(directory.glob(f"*-{checkpoint_id}.json"))
        if not matches:
            raise FileNotFoundError(
                f"No checkpoint found for id={checkpoint_id} in {directory}"
            )
        path = matches[0]
        with path.open("r") as f:
            data = json.load(f)
        patient_id = data["patient_id"]
        actor = data["actor"]
        store = cls(
            patient_id=patient_id,
            actor=actor,
            checkpoint_id=checkpoint_id,
            checkpoint_dir=str(directory),
        )
        store._data = data
        return store

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def completed_stages(self) -> dict[str, str]:
        """Return {stage_key: output} for all completed stages."""
        return {
            k: v["output"]
            for k, v in self._data.get("stages", {}).items()
            if v.get("completed_at")
        }

    def get_stage(self, stage: str) -> str | None:
        """Return output for a completed stage, or None if not yet done."""
        return self._data.get("stages", {}).get(stage, {}).get("output")

    def first_incomplete_stage(self) -> str | None:
        """Return the first stage in STAGE_ORDER that has not completed."""
        completed = set(self.completed_stages())
        for stage in STAGE_ORDER:
            if stage not in completed:
                return stage
        return None  # All stages complete

    def get_plan(self) -> dict[str, Any] | None:
        """Return the saved WorkflowPlan dict, or None."""
        return self._data.get("plan")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_plan(self, plan: dict[str, Any]) -> None:
        """Persist the workflow plan after Stage 0."""
        self._data["plan"] = plan
        self._write()

    def save_stage(self, stage: str, output: str) -> None:
        """Persist a completed stage output."""
        if "stages" not in self._data:
            self._data["stages"] = {}
        self._data["stages"][stage] = {
            "output": output,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write()
        _logger.debug("Checkpoint: saved stage=%s id=%s", stage, self.checkpoint_id)

    def delete(self) -> None:
        """Remove the checkpoint file after successful workflow completion."""
        if self._path.exists():
            self._path.unlink()
            _logger.info("Checkpoint: deleted id=%s", self.checkpoint_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_or_init(self) -> dict[str, Any]:
        if self._path.exists():
            with self._path.open("r") as f:
                data = json.load(f)
            _logger.info(
                "Checkpoint: loaded existing id=%s patient=%s",
                self.checkpoint_id, self.patient_id,
            )
            return data
        return {
            "workflow_id": self.checkpoint_id,
            "patient_id": self.patient_id,
            "actor": self.actor,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "plan": None,
            "stages": {},
        }

    def _write(self) -> None:
        with self._path.open("w") as f:
            json.dump(self._data, f, indent=2)
