"""Pydantic models for literature evidence and CMS crosswalk agreement.

PHI NOTE: These models hold only condition strings, study metadata, and
aggregate scores -- no patient identifiers or clinical note text ever
flow through this module.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PubMedStudy(BaseModel):
    """A single study returned from PubMed E-utilities."""

    pmid: str
    title: str
    journal: str = ""
    pub_year: int | None = None
    url: str


class LiteratureEvidence(BaseModel):
    """Aggregated literature evidence for one clinical condition."""

    condition: str
    studies: list[PubMedStudy] = Field(default_factory=list)

    @property
    def study_count(self) -> int:
        return len(self.studies)


class ConsensusScore(BaseModel):
    """Consensus.app-style claim agreement score."""

    claim: str
    consensus_score: float = Field(ge=0.0, le=1.0)
    paper_count: int = 0


class CMSCoverageCriterion(BaseModel):
    """Structured coverage criterion extracted from an NCD/LCD document."""

    condition: str
    document_id: str
    requires_evidence_of: str
    source_url: str = ""


class AgreementResult(BaseModel):
    """Outcome of comparing literature evidence against a CMS coverage criterion."""

    condition: str
    literature_supports: bool
    cms_requires: bool
    agrees: bool
    requires_human_review: bool = False
    reason: str = ""
