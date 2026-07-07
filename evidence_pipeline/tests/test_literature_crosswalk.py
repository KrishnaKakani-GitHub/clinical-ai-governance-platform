"""Tests for literature evidence models, PubMed client, and CMS crosswalk.

PubMed API calls are mocked -- no network access in CI, no flaky tests
from live API drift. The crosswalk itself is a pure function and is
tested directly against constructed model instances.
"""
from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

from evidence_pipeline.literature.crosswalk import (
    CONSENSUS_SUPPORT_THRESHOLD,
    MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT,
    compare_evidence_to_cms,
)
from evidence_pipeline.literature.models import (
    CMSCoverageCriterion,
    ConsensusScore,
    LiteratureEvidence,
    PubMedStudy,
)
from evidence_pipeline.literature.pubmed_client import search_pubmed


def _study(pmid: str = "1") -> PubMedStudy:
    return PubMedStudy(pmid=pmid, title="t", journal="j", pub_year=2024, url="u")


def _evidence(condition: str = "atrial fibrillation", n: int = 10) -> LiteratureEvidence:
    return LiteratureEvidence(condition=condition, studies=[_study(str(i)) for i in range(n)])


def _consensus(condition: str = "atrial fibrillation", score: float = 0.9) -> ConsensusScore:
    return ConsensusScore(claim=condition, consensus_score=score, paper_count=10)


def _cms(condition: str = "atrial fibrillation", requires: str = "documented episode") -> CMSCoverageCriterion:
    return CMSCoverageCriterion(
        condition=condition, document_id="NCD-1", requires_evidence_of=requires,
    )


# --- crosswalk ------------------------------------------------------------


def test_agreement_when_literature_and_cms_align() -> None:
    result = compare_evidence_to_cms(_evidence(), _consensus(score=0.9), _cms())
    assert result.agrees is True
    assert result.requires_human_review is False


def test_disagreement_flagged_for_human_review() -> None:
    result = compare_evidence_to_cms(_evidence(), _consensus(score=0.2), _cms())
    assert result.literature_supports is False
    assert result.cms_requires is True
    assert result.agrees is False
    assert result.requires_human_review is True
    assert "consensus" in result.reason


def test_thin_evidence_forces_human_review_even_when_scores_agree() -> None:
    thin = _evidence(n=2)
    result = compare_evidence_to_cms(thin, _consensus(score=0.9), _cms())
    assert result.agrees is True  # scores align...
    assert result.requires_human_review is True  # ...but N is too low to trust it
    assert "studies found" in result.reason


def test_mismatched_inputs_forces_human_review() -> None:
    result = compare_evidence_to_cms(
        _evidence(condition="diabetes"),
        _consensus(condition="diabetes"),
        _cms(condition="hypertension"),
    )
    assert result.requires_human_review is True
    assert "mismatch" in result.reason.lower()


def test_consensus_threshold_boundary() -> None:
    at_threshold = _consensus(score=CONSENSUS_SUPPORT_THRESHOLD)
    result = compare_evidence_to_cms(_evidence(), at_threshold, _cms())
    assert result.literature_supports is True


def test_min_study_count_constant_is_positive() -> None:
    assert MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT > 0


def test_no_evidence_required_case_agrees_when_literature_absent() -> None:
    # cms.requires_evidence_of empty -> cms_requires False; literature below
    # threshold -> literature_supports False; these agree with each other.
    no_req_cms = CMSCoverageCriterion(
        condition="atrial fibrillation", document_id="NCD-2", requires_evidence_of="",
    )
    result = compare_evidence_to_cms(_evidence(), _consensus(score=0.1), no_req_cms)
    assert result.cms_requires is False
    assert result.literature_supports is False
    assert result.agrees is True


# --- pubmed client (mocked) ------------------------------------------------


def _mock_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


@patch("evidence_pipeline.literature.pubmed_client.urllib.request.urlopen")
def test_search_pubmed_parses_results(mock_urlopen: MagicMock) -> None:
    esearch_payload = {"esearchresult": {"idlist": ["111", "222"]}}
    esummary_payload = {
        "result": {
            "uids": ["111", "222"],
            "111": {"title": "Study A", "fulljournalname": "J1", "pubdate": "2023 Jan"},
            "222": {"title": "Study B", "source": "J2", "pubdate": "2022"},
        }
    }
    mock_urlopen.side_effect = [
        _mock_response(esearch_payload),
        _mock_response(esummary_payload),
    ]

    result = search_pubmed("atrial fibrillation", max_results=5)

    assert result.condition == "atrial fibrillation"
    assert result.study_count == 2
    assert result.studies[0].pmid == "111"
    assert result.studies[0].pub_year == 2023
    assert result.studies[1].journal == "J2"


@patch("evidence_pipeline.literature.pubmed_client.urllib.request.urlopen")
def test_search_pubmed_returns_empty_on_no_results(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_response({"esearchresult": {"idlist": []}})
    result = search_pubmed("an extremely rare made-up condition")
    assert result.study_count == 0


@patch("evidence_pipeline.literature.pubmed_client.urllib.request.urlopen")
def test_search_pubmed_returns_empty_on_api_failure(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = urllib.error.URLError("network down")
    result = search_pubmed("hypertension")
    assert result.study_count == 0


@patch("evidence_pipeline.literature.pubmed_client.urllib.request.urlopen")
def test_search_pubmed_passes_api_key(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_response({"esearchresult": {"idlist": []}})
    search_pubmed("hypertension", api_key="test-key-123")
    called_url = mock_urlopen.call_args[0][0].full_url
    assert "api_key=test-key-123" in called_url
