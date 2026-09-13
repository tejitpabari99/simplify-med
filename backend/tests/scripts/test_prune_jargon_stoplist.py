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


def test_committed_dictionary_excludes_named_stoplist_examples():
    dictionary = json.loads(_DICTIONARY_PATH.read_text())
    bare_terms = {record["term"] for record in dictionary}
    for word in ("heart", "blood", "pain", "brain", "stomach", "fever", "ability"):
        assert word not in bare_terms, f"{word!r} should have been pruned"
