"""Tests for evidence_pipeline/ontology/cui_mapper.py."""
from __future__ import annotations

import pytest

from evidence_pipeline.ontology.cui_mapper import (
    OntologyMapping, crosswalk_stats, lookup_cui, map_icd10_to_cui, search_by_name,
)


# --- lookup_cui ---------------------------------------------------------------

def test_lookup_pnh_returns_mapping() -> None:
    m = lookup_cui("C0028344")
    assert m is not None
    assert m.preferred_name == "Paroxysmal Nocturnal Hemoglobinuria"
    assert "D59.5" in m.icd10
    assert "727910" in m.rxnorm   # eculizumab
    assert m.has_icd10 and m.has_rxnorm

def test_lookup_t2dm_has_all_five_vocabularies() -> None:
    m = lookup_cui("C0011860")
    assert m is not None
    vocabs = m.vocabulary_coverage
    assert "ICD-10-CM" in vocabs
    assert "RxNorm" in vocabs
    assert "LOINC" in vocabs
    assert "SNOMED CT" in vocabs
    assert "CPT-4" in vocabs

def test_lookup_unknown_cui_returns_none() -> None:
    assert lookup_cui("C9999999") is None

def test_lookup_returns_definition() -> None:
    m = lookup_cui("C0028344")
    assert m is not None and m.definition is not None and len(m.definition) > 20


# --- search_by_name -----------------------------------------------------------

def test_search_by_alias_pnh() -> None:
    m = search_by_name("PNH")
    assert m is not None and m.cui == "C0028344"

def test_search_by_alias_t2dm() -> None:
    assert search_by_name("T2DM") is not None
    assert search_by_name("type 2 diabetes") is not None

def test_search_case_insensitive() -> None:
    assert search_by_name("COPD") == search_by_name("copd")

def test_search_partial_match() -> None:
    # "Gaucher" should partially match "Gaucher Disease"
    m = search_by_name("Gaucher")
    assert m is not None and m.cui == "C0017205"

def test_search_unknown_returns_none() -> None:
    assert search_by_name("xyzzy disease") is None


# --- map_icd10_to_cui ---------------------------------------------------------

def test_icd10_exact_reverse_lookup() -> None:
    m = map_icd10_to_cui("D59.5")
    assert m is not None and m.cui == "C0028344"

def test_icd10_category_prefix_lookup() -> None:
    # "I10" should match the hypertension entry
    m = map_icd10_to_cui("I10")
    assert m is not None and m.cui == "C0020538"

def test_icd10_unknown_returns_none() -> None:
    assert map_icd10_to_cui("Z99.9") is None


# --- to_dict / stats ----------------------------------------------------------

def test_to_dict_has_required_keys() -> None:
    m = lookup_cui("C0028344")
    assert m is not None
    d = m.to_dict()
    assert all(k in d for k in ["cui", "preferred_name", "codes", "definition"])
    assert all(k in d["codes"] for k in ["icd10", "rxnorm", "loinc", "snomed", "cpt"])

def test_crosswalk_stats() -> None:
    stats = crosswalk_stats()
    assert stats["total_cuis"] >= 12
    assert stats["with_icd10"] == stats["total_cuis"]  # every entry has ICD-10
    assert stats["with_rxnorm"] >= 10
    assert stats["with_loinc"] >= 10
