"""Tests for glossary matching and message building."""
from __future__ import annotations

import json
import time

import pytest
from glossary import Glossary, GlossaryLoader, GlossaryTerm
from tests.conftest import make_glossary


# ── find_matches ─────────────────────────────────────────────────────────────

def test_basic_match():
    g = make_glossary(("flux", "幅能", ""), ("shield", "护盾", ""))
    matches = g.find_matches("The flux level is critical.")
    assert len(matches) == 1
    assert matches[0].english == "flux"


def test_multiple_matches():
    g = make_glossary(("flux", "幅能", ""), ("shield", "护盾", ""))
    matches = g.find_matches("Flux venting lowers the shield.")
    assert {m.english for m in matches} == {"flux", "shield"}


def test_case_insensitive():
    g = make_glossary(("Flux", "幅能", ""))
    assert g.find_matches("FLUX venting") != []
    assert g.find_matches("flux venting") != []
    assert g.find_matches("Flux venting") != []


def test_word_boundary_no_partial_match():
    g = make_glossary(("ore", "矿石", ""))
    assert g.find_matches("we need more supplies") == []
    assert g.find_matches("exploring lore") == []


def test_word_boundary_exact_match():
    g = make_glossary(("ore", "矿石", ""))
    assert g.find_matches("mining ore deposit") != []


def test_no_match():
    g = make_glossary(("flux", "幅能", ""))
    assert g.find_matches("nothing relevant here") == []


def test_empty_text():
    g = make_glossary(("flux", "幅能", ""))
    assert g.find_matches("") == []


def test_alternative_forms_match():
    term = GlossaryTerm(english="Domain", chinese="领域", notes="", alternatives=["The Domain"])
    g = Glossary([term])
    assert g.find_matches("remnants of The Domain") != []


def test_alternative_forms_primary_not_required():
    term = GlossaryTerm(english="Domain", chinese="领域", notes="", alternatives=["Hegemony"])
    g = Glossary([term])
    assert g.find_matches("the Hegemony fleet") != []


def test_deduplication_via_alternatives():
    """Same term matched via primary and alternative should appear only once."""
    term = GlossaryTerm(english="flux", chinese="幅能", notes="", alternatives=["fluxes"])
    g = Glossary([term])
    matches = g.find_matches("the flux and fluxes")
    assert len(matches) == 1


def test_empty_glossary():
    g = Glossary([])
    assert g.find_matches("flux shield colony") == []


# ── build_system_message ─────────────────────────────────────────────────────

def test_build_message_contains_terms():
    g = make_glossary(("flux", "幅能", ""), ("shield", "护盾", ""))
    matches = g.find_matches("flux and shield")
    msg = g.build_system_message(matches)
    assert "flux → 幅能" in msg
    assert "shield → 护盾" in msg


def test_build_message_includes_notes():
    g = make_glossary(("colony", "殖民地", "人类定居点"))
    matches = g.find_matches("colony expansion")
    msg = g.build_system_message(matches)
    assert "人类定居点" in msg


def test_build_message_no_notes_no_parentheses():
    g = make_glossary(("flux", "幅能", ""))
    matches = g.find_matches("flux")
    msg = g.build_system_message(matches)
    assert "（）" not in msg


def test_build_message_has_header():
    g = make_glossary(("flux", "幅能", ""))
    matches = g.find_matches("flux")
    msg = g.build_system_message(matches)
    assert "术语" in msg


# ── GlossaryLoader ────────────────────────────────────────────────────────────

def _write_json(path, terms: list[dict]) -> None:
    path.write_text(
        json.dumps({"updatedAt": "2024-01-01T00:00:00Z", "terms": terms}),
        encoding="utf-8",
    )


def test_loader_returns_empty_when_file_missing(tmp_path):
    loader = GlossaryLoader(tmp_path / "nonexistent.json")
    assert loader.find_matches("flux") == []
    assert loader.build_system_message([]) == ""


def test_loader_loads_on_first_use(tmp_path):
    path = tmp_path / "terms.json"
    _write_json(path, [{"term": "flux", "translation": "幅能", "note": ""}])
    loader = GlossaryLoader(path)
    matches = loader.find_matches("flux levels")
    assert len(matches) == 1
    assert matches[0].english == "flux"


def test_loader_reloads_when_file_changes(tmp_path):
    path = tmp_path / "terms.json"
    _write_json(path, [{"term": "flux", "translation": "幅能", "note": ""}])
    loader = GlossaryLoader(path)
    loader.find_matches("flux")  # initial load

    # Overwrite with new content; bump mtime by modifying the file
    time.sleep(0.01)  # ensure mtime differs
    _write_json(path, [{"term": "shield", "translation": "护盾", "note": ""}])
    # Touch the file to guarantee a different mtime on fast filesystems
    path.touch()

    assert loader.find_matches("shield damage") != []
    assert loader.find_matches("flux levels") == []


def test_loader_skips_terms_missing_translation(tmp_path):
    path = tmp_path / "terms.json"
    _write_json(path, [
        {"term": "flux", "translation": "", "note": ""},
        {"term": "shield", "translation": "护盾", "note": ""},
    ])
    loader = GlossaryLoader(path)
    matches = loader.find_matches("flux and shield")
    assert len(matches) == 1
    assert matches[0].english == "shield"


def test_loader_builds_system_message(tmp_path):
    path = tmp_path / "terms.json"
    _write_json(path, [{"term": "flux", "translation": "幅能", "note": ""}])
    loader = GlossaryLoader(path)
    matches = loader.find_matches("flux")
    msg = loader.build_system_message(matches)
    assert "flux → 幅能" in msg
