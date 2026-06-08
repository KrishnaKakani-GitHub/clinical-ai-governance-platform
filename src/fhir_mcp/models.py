"""Pydantic v2 models for the FHIR MCP server.

These intentionally mirror a *subset* of FHIR fields. They are simplified for
a synthetic-data development server, not a spec-complete FHIR implementation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Gender(str, Enum):
    male = "male"
    female = "female"
    other = "other"
    unknown = "unknown"


class Patient(BaseModel):
    """Minimal FHIR Patient resource (synthetic)."""

    id: str = Field(..., description="Logical resource id, e.g. 'pat-001'.")
    name: str
    birth_date: date
    gender: Gender
    mrn: str = Field(..., description="Medical record number (synthetic).")


class Observation(BaseModel):
    """Minimal FHIR Observation resource (synthetic)."""

    id: str
    patient_id: str = Field(..., description="Reference to Patient.id.")
    code: str = Field(..., description="LOINC code.")
    display: str
    value: float
    unit: str
    effective_date: date


class DataStore(BaseModel):
    """Root document persisted to JSON."""

    patients: list[Patient] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)


# --- Gated-write models -------------------------------------------------------


class ProposedObservation(BaseModel):
    """A write an agent *proposes*. It is staged, never committed directly.

    PHI note: this carries clinical values. In production, persist only
    references/IDs where possible and minimise the raw payload retained.
    """

    patient_id: str
    code: str
    display: str
    value: float
    unit: str
    effective_date: date


class PendingWriteStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class PendingWrite(BaseModel):
    """A staged write awaiting human-in-the-loop approval."""

    write_id: str
    resource_type: Literal["Observation"] = "Observation"
    proposed: ProposedObservation
    status: PendingWriteStatus = PendingWriteStatus.pending
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    decided_at: datetime | None = None
    decided_by: str | None = None
