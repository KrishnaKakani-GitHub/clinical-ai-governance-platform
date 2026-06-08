"""Data store: the ONLY module that reads/writes the synthetic data file.

Keeping all persistence in one place means every PHI touchpoint is in a single
auditable spot. In production this layer would be a real database with
transactions; for a first server, a JSON file is enough to learn the pattern.

PHI NOTE: in a real system the patient/observation records below would be PHI.
Here they are synthetic. The store deliberately never logs record *contents* —
that responsibility (and the choice to log IDs only) lives in audit.py.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from .models import (
    DataStore,
    Observation,
    PendingWrite,
    PendingWriteStatus,
    ProposedObservation,
)


class StoreError(Exception):
    """Raised for store-level problems (missing records, bad state)."""


class FhirStore:
    """Loads synthetic data and holds the pending-write queue in memory.

    A lock guards mutations because Claude may call tools concurrently. This is
    a coarse lock (fine for a single-process learning server); a real datastore
    would use row-level transactions instead.
    """

    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path
        self._lock = threading.Lock()
        self._data = self._load()
        # Pending writes live in memory only; they are intentionally NOT
        # persisted until approved, so an unapproved proposal can never leak
        # into the data file.
        self._pending: dict[str, PendingWrite] = {}

    def _load(self) -> DataStore:
        if not self._data_path.exists():
            raise StoreError(f"Data file not found: {self._data_path}")
        raw = json.loads(self._data_path.read_text(encoding="utf-8"))
        return DataStore.model_validate(raw)

    def _persist(self) -> None:
        """Write the committed data back to disk (Pydantic handles encoding)."""
        self._data_path.write_text(
            self._data.model_dump_json(indent=2), encoding="utf-8"
        )

    # --- Reads ----------------------------------------------------------------

    def get_patient_ids(self) -> list[str]:
        return [p.id for p in self._data.patients]

    def get_patient(self, patient_id: str):
        for p in self._data.patients:
            if p.id == patient_id:
                return p
        raise StoreError(f"Unknown patient_id: {patient_id}")

    def list_observations(self, patient_id: str) -> list[Observation]:
        # Validates the patient exists first (raises if not).
        self.get_patient(patient_id)
        return [o for o in self._data.observations if o.patient_id == patient_id]

    # --- Gated write: stage -> approve/reject ---------------------------------

    def stage_write(self, proposed: ProposedObservation) -> PendingWrite:
        """Stage a proposed observation. Does NOT commit. Returns the ticket."""
        # Deterministic validation gate: reject obviously bad data before it can
        # even be queued. This is the "deterministic layer" the architecture
        # relies on — agents propose, this code decides what's eligible.
        self.get_patient(proposed.patient_id)  # patient must exist
        if proposed.value < 0:
            raise StoreError("Observation value cannot be negative.")
        if not proposed.code.strip():
            raise StoreError("Observation code is required.")

        with self._lock:
            write_id = f"pw-{uuid.uuid4().hex[:8]}"
            pending = PendingWrite(write_id=write_id, proposed=proposed)
            self._pending[write_id] = pending
            return pending

    def get_pending(self, write_id: str) -> PendingWrite:
        pending = self._pending.get(write_id)
        if pending is None:
            raise StoreError(f"Unknown write_id: {write_id}")
        return pending

    def list_pending(self) -> list[PendingWrite]:
        return [
            w
            for w in self._pending.values()
            if w.status == PendingWriteStatus.pending
        ]

    def approve_write(self, write_id: str, approver: str) -> Observation:
        """Commit a staged write. Only reachable after explicit human approval."""
        from datetime import datetime, timezone

        with self._lock:
            pending = self.get_pending(write_id)
            if pending.status != PendingWriteStatus.pending:
                raise StoreError(
                    f"Write {write_id} already {pending.status.value}."
                )
            obs = Observation(
                id=f"obs-{uuid.uuid4().hex[:8]}",
                patient_id=pending.proposed.patient_id,
                code=pending.proposed.code,
                display=pending.proposed.display,
                value=pending.proposed.value,
                unit=pending.proposed.unit,
                effective_date=pending.proposed.effective_date,
            )
            self._data.observations.append(obs)
            self._persist()
            pending.status = PendingWriteStatus.approved
            pending.decided_at = datetime.now(timezone.utc)
            pending.decided_by = approver
            return obs

    def reject_write(self, write_id: str, approver: str) -> PendingWrite:
        from datetime import datetime, timezone

        with self._lock:
            pending = self.get_pending(write_id)
            if pending.status != PendingWriteStatus.pending:
                raise StoreError(
                    f"Write {write_id} already {pending.status.value}."
                )
            pending.status = PendingWriteStatus.rejected
            pending.decided_at = datetime.now(timezone.utc)
            pending.decided_by = approver
            return pending
