"""Tests for the MIMIC demo-notes loader (evals/demo_notes.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.demo_notes import DemoNote, DemoNotesLoader


def test_demo_note_preview_truncates():
    note = DemoNote(note_id="n1", subject_id="s1", hadm_id="h1", text="x " * 200)
    p = note.preview(n=50)
    assert len(p) <= 51  # 50 chars + ellipsis
    assert p.endswith("…")


def test_demo_note_preview_short_text_no_ellipsis():
    note = DemoNote(note_id="n1", subject_id="", hadm_id="", text="short note")
    assert note.preview() == "short note"


def test_loader_missing_dir_raises():
    with pytest.raises(FileNotFoundError, match="not found"):
        DemoNotesLoader("/no/such/mimic/dir")


def test_loader_reads_txt_files(tmp_path):
    (tmp_path / "note-0001.txt").write_text("patient with chest pain")
    (tmp_path / "note-0002.txt").write_text("patient with diabetes")
    notes = DemoNotesLoader(tmp_path).load()
    assert len(notes) == 2
    assert {n.note_id for n in notes} == {"note-0001", "note-0002"}
    assert notes[0].text  # text loaded


def test_loader_respects_limit(tmp_path):
    for i in range(5):
        (tmp_path / f"note-{i:04d}.txt").write_text(f"note {i}")
    notes = DemoNotesLoader(tmp_path).load(limit=2)
    assert len(notes) == 2


def test_loader_reads_discharge_csv(tmp_path):
    csv_path = tmp_path / "discharge.csv"
    csv_path.write_text(
        "note_id,subject_id,hadm_id,text\n"
        "DN1,1001,2001,chest pain and dyspnea\n"
        "DN2,1002,2002,fever and cough\n"
    )
    notes = DemoNotesLoader(tmp_path).load()
    assert len(notes) == 2
    assert notes[0].note_id == "DN1"
    assert notes[0].subject_id == "1001"
    assert "chest pain" in notes[0].text


def test_csv_takes_precedence_over_txt(tmp_path):
    (tmp_path / "discharge.csv").write_text("note_id,text\nCSV1,from csv\n")
    (tmp_path / "ignored.txt").write_text("from txt")
    notes = DemoNotesLoader(tmp_path).load()
    assert len(notes) == 1 and notes[0].note_id == "CSV1"
