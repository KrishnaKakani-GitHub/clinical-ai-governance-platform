"""PubMed E-utilities client (esearch + esummary).

Sourced study counts for the literature-evidence pipeline. Mirrors
fhir_mcp/trials.py's client shape: stdlib urllib only, condition-string
input, graceful empty-list return on any API failure -- never raises.

API: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/

PHI NOTE: Only condition strings are sent externally. No patient data.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from .models import LiteratureEvidence, PubMedStudy

_logger = logging.getLogger("evidence_pipeline.literature.pubmed")

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _get_json(url: str, params: dict[str, str], timeout: int = 8) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "User-Agent": "clinical-ai-governance/2.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def search_pubmed(
    condition: str,
    max_results: int = 20,
    api_key: str | None = None,
) -> LiteratureEvidence:
    """Search PubMed for peer-reviewed studies on a clinical condition.

    Args:
        condition:   Clinical condition string (e.g. 'atrial fibrillation').
        max_results: Maximum number of studies to return (default 20).
        api_key:     Optional NCBI API key for higher rate limits
                     (falls back to env var PUBMED_API_KEY).

    Returns:
        LiteratureEvidence with condition + list of PubMedStudy.
        Returns an empty study list if the API is unreachable or the
        response is malformed -- never raises on network failure.
    """
    key = api_key or os.environ.get("PUBMED_API_KEY", "").strip()

    search_params = {
        "db": "pubmed",
        "term": f"{condition}[Title/Abstract] AND (Clinical Trial[pt] OR Meta-Analysis[pt] OR Review[pt])",
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",
    }
    if key:
        search_params["api_key"] = key

    try:
        search_data = _get_json(_ESEARCH_URL, search_params)
        pmids = search_data.get("esearchresult", {}).get("idlist", [])
        if not pmids:
            return LiteratureEvidence(condition=condition, studies=[])

        summary_params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        if key:
            summary_params["api_key"] = key
        summary_data = _get_json(_ESUMMARY_URL, summary_params)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        _logger.warning("PubMed API unreachable: %s", e)
        return LiteratureEvidence(condition=condition, studies=[])

    result = summary_data.get("result", {})
    studies: list[PubMedStudy] = []
    for pmid in result.get("uids", []):
        doc = result.get(pmid, {})
        pub_date = doc.get("pubdate", "")
        year = int(pub_date[:4]) if pub_date[:4].isdigit() else None
        studies.append(
            PubMedStudy(
                pmid=pmid,
                title=doc.get("title", ""),
                journal=doc.get("fulljournalname", doc.get("source", "")),
                pub_year=year,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            )
        )

    return LiteratureEvidence(condition=condition, studies=studies)
