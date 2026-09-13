"""Tests for services/unitizer.py: unitize, provenance_for_pasted_text."""

from models.provenance import SourceSpan
from services.unitizer import provenance_for_pasted_text, unitize


def test_unitize_assigns_sequential_ids_skipping_blank_lines():
    text = "a\n\nb\n\n\nc"
    provenance = [SourceSpan(file="f", page=1, start_line=0, end_line=5)]

    units = unitize(text, provenance)

    assert [u.id for u in units] == [1, 2, 3]
    assert [u.text for u in units] == ["a", "b", "c"]
    # line numbers skip across the blank lines (1-indexed within the span)
    assert [u.line for u in units] == [1, 3, 6]


def test_unitize_is_deterministic_across_repeated_calls():
    text = "a\n\nb\nc"
    provenance = [SourceSpan(file="f", page=1, start_line=0, end_line=3)]

    first = unitize(text, provenance)
    second = unitize(text, provenance)

    assert first == second


def test_unitize_line_numbers_reset_per_page():
    text = "a\nb\nc\nd"
    provenance = [
        SourceSpan(file="f", page=1, start_line=0, end_line=1),
        SourceSpan(file="f", page=2, start_line=2, end_line=3),
    ]

    units = unitize(text, provenance)

    assert units[0].line == 1
    assert units[1].line == 2
    # second span's first unit resets to line 1, not a continuation (3)
    assert units[2].line == 1
    assert units[3].line == 2


def test_unitize_multi_file_preserves_distinct_file_identity():
    text = "a\nb"
    provenance = [
        SourceSpan(file="one.pdf", page=1, start_line=0, end_line=0),
        SourceSpan(file="two.pdf", page=1, start_line=1, end_line=1),
    ]

    units = unitize(text, provenance)

    assert units[0].file == "one.pdf"
    assert units[1].file == "two.pdf"


def test_unitize_empty_provenance_returns_empty_list():
    assert unitize("a\nb\nc", []) == []


def test_unitize_preserves_verbatim_line_text_including_internal_whitespace():
    text = "a\n  leading and trailing spaces  \nb"
    provenance = [SourceSpan(file="f", page=1, start_line=0, end_line=2)]

    units = unitize(text, provenance)

    assert units[1].text == "  leading and trailing spaces  "


def test_unitize_tolerates_span_past_end_of_text():
    text = "a\nb"
    provenance = [SourceSpan(file="f", page=1, start_line=0, end_line=10)]

    units = unitize(text, provenance)

    assert [u.text for u in units] == ["a", "b"]


def test_provenance_for_pasted_text_single_span_covers_whole_text():
    spans = provenance_for_pasted_text("a\nb")

    assert spans == [SourceSpan(file="text_input", page=1, start_line=0, end_line=1)]


def test_provenance_for_pasted_text_empty_string_returns_empty_list():
    assert provenance_for_pasted_text("") == []
