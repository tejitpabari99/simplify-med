"""Tests for services/unitizer.py: unitize, provenance_for_pasted_text."""

import logging

from models.provenance import SourceSpan
from services.unitizer import provenance_for_pasted_text, unitize


def _span(**overrides) -> SourceSpan:
    fields = dict(file="f", page=1, start_line=0, end_line=1, extraction_method="native")
    fields.update(overrides)
    return SourceSpan(**fields)


def test_unitize_assigns_sequential_ids_skipping_blank_lines():
    text = "a\n\nb\n\n\nc"
    provenance = [_span(start_line=0, end_line=5)]

    units = unitize(text, provenance)

    assert [u.id for u in units] == [1, 2, 3]
    assert [u.text for u in units] == ["a", "b", "c"]
    # line numbers skip across the blank lines (1-indexed within the span)
    assert [u.line for u in units] == [1, 3, 6]
    assert all(u.extraction_method == "native" for u in units)


def test_unitize_is_deterministic_across_repeated_calls():
    text = "a\n\nb\nc"
    provenance = [_span(start_line=0, end_line=3)]

    first = unitize(text, provenance)
    second = unitize(text, provenance)

    assert first == second


def test_unitize_line_numbers_reset_per_page():
    text = "a\nb\nc\nd"
    provenance = [
        _span(page=1, start_line=0, end_line=1),
        _span(page=2, start_line=2, end_line=3),
    ]

    units = unitize(text, provenance)

    assert units[0].line == 1
    assert units[1].line == 2
    # second span's first unit resets to line 1, not a continuation (3)
    assert units[2].line == 1
    assert units[3].line == 2
    assert all(u.extraction_method == "native" for u in units)


def test_unitize_multi_file_preserves_distinct_file_identity():
    text = "a\nb"
    provenance = [
        _span(file="one.pdf", page=1, start_line=0, end_line=0),
        _span(file="two.pdf", page=1, start_line=1, end_line=1),
    ]

    units = unitize(text, provenance)

    assert units[0].file == "one.pdf"
    assert units[1].file == "two.pdf"
    assert all(u.extraction_method == "native" for u in units)


def test_unitize_empty_provenance_returns_empty_list():
    assert unitize("a\nb\nc", []) == []


def test_unitize_preserves_verbatim_line_text_including_internal_whitespace():
    text = "a\n  leading and trailing spaces  \nb"
    provenance = [_span(start_line=0, end_line=2)]

    units = unitize(text, provenance)

    assert units[1].text == "  leading and trailing spaces  "
    assert units[1].extraction_method == "native"


def test_unitize_tolerates_span_past_end_of_text():
    text = "a\nb"
    provenance = [_span(start_line=0, end_line=10)]

    units = unitize(text, provenance)

    assert [u.text for u in units] == ["a", "b"]
    assert all(u.extraction_method == "native" for u in units)


def test_unitize_copies_extraction_method_from_span_verbatim():
    text = "a\nb\nc"
    provenance = [_span(start_line=0, end_line=2, extraction_method="ocr")]

    units = unitize(text, provenance)

    assert len(units) == 3
    assert all(u.extraction_method == "ocr" for u in units)


def test_unitize_preserves_distinct_extraction_methods_across_mixed_spans():
    text = "a\nb\nc"
    provenance = [
        _span(file="f", page=1, start_line=0, end_line=0, extraction_method="native"),
        _span(file="f", page=2, start_line=1, end_line=1, extraction_method="ocr"),
        _span(file="f", page=3, start_line=2, end_line=2, extraction_method="pasted"),
    ]

    units = unitize(text, provenance)

    assert units[0].extraction_method == "native"
    assert units[1].extraction_method == "ocr"
    assert units[2].extraction_method == "pasted"


def test_unitize_logs_extraction_signal_aggregate(caplog):
    # 2 native spans -> 5 native units, 1 ocr span -> 2 ocr units
    text = "n1\nn2\nn3\nn4\nn5\no1\no2"
    provenance = [
        _span(file="f", page=1, start_line=0, end_line=2, extraction_method="native"),
        _span(file="f", page=2, start_line=3, end_line=4, extraction_method="native"),
        _span(file="f", page=3, start_line=5, end_line=6, extraction_method="ocr"),
    ]

    with caplog.at_level(logging.INFO, logger="services.unitizer"):
        units = unitize(text, provenance)

    assert len(units) == 7
    records = [r for r in caplog.records if r.name == "services.unitizer"]
    assert len(records) == 1
    assert records[0].extraction_signal == {
        "total": 7,
        "native": 5,
        "ocr": 2,
        "pasted": 0,
        "ocr_rate": 2 / 7,
    }


def test_unitize_empty_units_list_logs_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="services.unitizer"):
        units = unitize("", [])

    assert units == []
    assert [r for r in caplog.records if r.name == "services.unitizer"] == []


def test_provenance_for_pasted_text_single_span_covers_whole_text():
    spans = provenance_for_pasted_text("a\nb")

    assert spans == [
        SourceSpan(file="text_input", page=1, start_line=0, end_line=1, extraction_method="pasted")
    ]


def test_provenance_for_pasted_text_empty_string_returns_empty_list():
    assert provenance_for_pasted_text("") == []
