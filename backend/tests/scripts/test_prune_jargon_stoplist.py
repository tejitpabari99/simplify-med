"""Tests for scripts/prune_jargon_stoplist.py — deterministic dictionary prune."""
import json
from pathlib import Path

from scripts.prune_jargon_stoplist import prune

_DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "jargon" / "michigan_medical_dictionary.json"


def test_prune_drops_records_whose_every_branch_is_stoplisted():
    dictionary = [
        {"term": "heart", "definition": "d1"},
        {"term": "plaque (in an artery)", "definition": "d2"},
        {"term": "abdomen, abdominal", "definition": "d3"},
    ]
    kept, dropped = prune(dictionary, {"heart"})
    assert [r["term"] for r in dropped] == ["heart"]
    assert {r["term"] for r in kept} == {"plaque (in an artery)", "abdomen, abdominal"}


def test_prune_never_drops_a_parenthetical_term():
    dictionary = [{"term": "plaque (in an artery)", "definition": "d"}]
    # Stoplist deliberately includes the bare, paren-stripped form.
    kept, dropped = prune(dictionary, {"plaque"})
    assert dropped == []
    assert kept == dictionary


def test_prune_keeps_record_if_any_branch_survives():
    dictionary = [{"term": "abdomen, abdominal", "definition": "d"}]
    kept, dropped = prune(dictionary, {"abdomen"})
    assert dropped == []
    assert kept == dictionary


def test_prune_drops_record_when_stoplist_entry_itself_has_commas():
    # A stoplist entry can itself be a comma-list ("foot, feet"); it must be
    # split into bare branches the same way a dictionary term is, so it
    # matches branch-for-branch instead of only ever comparing against the
    # literal, unsplit stoplist string.
    dictionary = [{"term": "foot, feet", "definition": "d"}]
    kept, dropped = prune(dictionary, {"foot, feet"})
    assert [r["term"] for r in dropped] == ["foot, feet"]
    assert kept == []


def test_committed_dictionary_excludes_named_stoplist_examples():
    dictionary = json.loads(_DICTIONARY_PATH.read_text())
    bare_terms = {record["term"] for record in dictionary}
    for word in ("heart", "blood", "pain", "brain", "stomach", "fever", "ability"):
        assert word not in bare_terms, f"{word!r} should have been pruned"
    # "foot, feet" is a comma-listed stoplist entry (§4.2); the fix in
    # prune_jargon_stoplist.py normalizes stoplist entries the same way a
    # dictionary term is split, so this record is also dropped -- all 14
    # starter-stoplist words/entries are now excluded.
    assert "foot, feet" not in bare_terms, "'foot, feet' should have been pruned"
    assert len(dictionary) == 1948
