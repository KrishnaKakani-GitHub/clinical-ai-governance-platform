"""Tests for evidence_pipeline/datasets/medquad.py."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from evidence_pipeline.datasets.medquad import (
    LoadResult, MedQuADItem, MedQuADLoader, get_loader,
)

CSV_CONTENT = textwrap.dedent("""\
    qtype,Question,Answer,source,Focus,CUI,SemanticType,url
    information,What is Type 2 Diabetes?,"Type 2 diabetes is a chronic condition.",niddk,Type 2 Diabetes,C0011860,Disease or Syndrome,https://niddk.nih.gov
    treatment,How is PNH treated?,"Treatment includes eculizumab.",GARD,Paroxysmal nocturnal hemoglobinuria,C0028344,Disease or Syndrome,https://rarediseases.info.nih.gov
    symptoms,What are the symptoms of diabetes?,,niddk,Type 2 Diabetes,C0011860,Disease or Syndrome,
    information,What causes anemia?,,medlineplus,,,,
""")

XML_CONTENT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Dataset>
      <Source>GARD</Source>
      <URL>https://rarediseases.info.nih.gov/diseases/7537</URL>
      <Focus>Gaucher disease</Focus>
      <FocusAnnotations>
        <UMLS><CUIs><CUI>C0017205</CUI></CUIs>
        <SemanticTypeList><SemanticType>Disease or Syndrome</SemanticType></SemanticTypeList>
        </UMLS>
      </FocusAnnotations>
      <QAPairs>
        <QAPair pid="1"><Question qtype="information">What is Gaucher disease?</Question><Answer>Gaucher disease is a rare genetic disorder.</Answer></QAPair>
        <QAPair pid="2"><Question qtype="treatment">How is it treated?</Question><Answer>Enzyme replacement therapy.</Answer></QAPair>
        <QAPair pid="3"><Question qtype="frequency">How common?</Question><Answer></Answer></QAPair>
      </QAPairs>
    </Dataset>
""")


@pytest.fixture()
def csv_corpus(tmp_path: Path) -> Path:
    d = tmp_path / "medquad"; d.mkdir()
    (d / "test.csv").write_text(CSV_CONTENT, encoding="utf-8")
    return d


@pytest.fixture()
def xml_corpus(tmp_path: Path) -> Path:
    d = tmp_path / "medquad"; d.mkdir()
    (d / "GARD_gaucher.xml").write_text(XML_CONTENT, encoding="utf-8")
    return d


def test_csv_loads_all_questions(csv_corpus: Path) -> None:
    assert MedQuADLoader(corpus_dir=csv_corpus).load().total == 4

def test_csv_answered_count(csv_corpus: Path) -> None:
    assert MedQuADLoader(corpus_dir=csv_corpus).load().answered == 2

def test_csv_rare_disease_flag(csv_corpus: Path) -> None:
    rare = [i for i in MedQuADLoader(corpus_dir=csv_corpus).load().items if i.is_rare_disease]
    assert len(rare) == 1 and rare[0].focus == "Paroxysmal nocturnal hemoglobinuria"

def test_csv_gold_cui_flag(csv_corpus: Path) -> None:
    items = MedQuADLoader(corpus_dir=csv_corpus).load().items
    assert sum(1 for i in items if i.has_gold_cui) == 3

def test_xml_loads_qa_pairs(xml_corpus: Path) -> None:
    assert MedQuADLoader(corpus_dir=xml_corpus).load().total == 3

def test_xml_metadata_propagated(xml_corpus: Path) -> None:
    for item in MedQuADLoader(corpus_dir=xml_corpus).load().items:
        assert item.focus == "Gaucher disease"
        assert item.cui == "C0017205"
        assert item.is_rare_disease

def test_xml_unanswered_item(xml_corpus: Path) -> None:
    items = MedQuADLoader(corpus_dir=xml_corpus).load().items
    assert sum(1 for i in items if not i.is_answered) == 1

def test_filter_by_question_type(csv_corpus: Path) -> None:
    info = MedQuADLoader(corpus_dir=csv_corpus).filter(question_type="information")
    assert all(i.question_type == "information" for i in info)

def test_missing_corpus_returns_empty(tmp_path: Path) -> None:
    result = MedQuADLoader(corpus_dir=tmp_path / "nope").load()
    assert not bool(result) and result.total == 0
