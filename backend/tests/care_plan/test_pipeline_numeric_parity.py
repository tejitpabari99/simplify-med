"""Tokenizer and numeric-parity tests for PRD 10 (Numeric Integrity) --
PRD 10 §7.2. Follows test_pipeline_assembly.py's established fixture
conventions: direct Fact/CarePlan construction, a local _make_item helper,
and caplog for asserting on _verify_assembly's log-only behavior."""

import logging

import pytest

from care_plan.pipeline import (
    _check_numeric_parity,
    _excluded_spans,
    _extract_number_tokens,
    _KNOWN_UNIT_WORDS,
    _normalize_number,
    _UNIT_WORD_MAX_LENGTH,
    _UNIT_WORD_RE,
    _verify_assembly,
)
from models.ledger import Fact
from models.care_plan.care_plan import (
    CarePlan,
    Diagnosis,
    DiagnosisDetail,
    FollowUp,
    Medication,
    OtherInstruction,
    Procedure,
    WarningSign,
    Test,
)


_ITEM_MODEL_BY_FIELD = {
    "medications": Medication,
    "tests": Test,
    "procedures": Procedure,
    "other": OtherInstruction,
    "follow_up": FollowUp,
    "warning_signs": WarningSign,
}


def _make_item(field: str, source_fact_ids: list[int], **overrides):
    """Build a minimal instance of the item model for `field`, with the
    given source_fact_ids. Every item type but warning_signs requires
    `status`; warning_signs requires `urgency` (nullable, no default)."""
    cls = _ITEM_MODEL_BY_FIELD[field]
    kwargs = {"source_fact_ids": list(source_fact_ids)}
    if field == "warning_signs":
        kwargs["urgency"] = None
    else:
        kwargs["status"] = "to_do"
    kwargs.update(overrides)
    return cls(**kwargs)


def _numeric_parity_records(caplog):
    """Filter caplog records down to this check's own warnings, so unrelated
    warnings (e.g. _log_thin_fields' thin-field logs) can't cause a false
    pass/fail on tests that assert about numeric-parity logging specifically."""
    return [r for r in caplog.records if "numeric parity" in r.message]


# ---------------------------------------------------------------------------
# Tokenizer: _extract_number_tokens, _normalize_number, _excluded_spans
# ---------------------------------------------------------------------------

def test_extract_number_tokens_normalizes_attached_vs_spaced_unit():
    assert _extract_number_tokens("25mg") == _extract_number_tokens("25 mg")
    assert _extract_number_tokens("25mg") == {("25", "mg")}


def test_extract_number_tokens_is_case_insensitive_on_unit():
    assert _extract_number_tokens("25MG") == _extract_number_tokens("25mg")


def test_normalize_number_strips_leading_zeros():
    assert _normalize_number("025") == "25"


def test_normalize_number_strips_trailing_decimal_zeros():
    assert _normalize_number("7.20") == "7.2"
    assert _normalize_number("7.0") == "7"


def test_extract_number_tokens_handles_thousands_separator():
    assert _extract_number_tokens("1,000 units") == _extract_number_tokens("1000 units")


def test_extract_number_tokens_matches_range():
    tokens = _extract_number_tokens("5-10 days")
    assert len(tokens) == 1
    (num, _unit), = tokens
    assert num == "5-10"


def test_extract_number_tokens_keeps_slash_pair_with_trailing_unit():
    assert _extract_number_tokens("158/96 mmHg") != set()
    assert _extract_number_tokens("1/2 tablet") != set()


def test_extract_number_tokens_excludes_bare_slash_pair_with_no_unit():
    assert _extract_number_tokens("4/12") == set()


def test_extract_number_tokens_excludes_written_month_and_day():
    assert _extract_number_tokens("April 12") == set()


def test_extract_number_tokens_excludes_time_of_day():
    assert _extract_number_tokens("7:30 AM") == set()


def test_extract_number_tokens_returns_empty_set_for_pure_word_frequency():
    assert _extract_number_tokens("twice a day") == set()


def test_excluded_spans_covers_time_and_date_shapes():
    spans = _excluded_spans("Take at 7:30 AM on April 12.")
    assert len(spans) >= 2


# ---------------------------------------------------------------------------
# PRD 10 review fixes: closed unit vocabulary for date exclusion, and
# non-unit words never reaching the log.
# ---------------------------------------------------------------------------

def test_extract_number_tokens_excludes_bare_date_followed_by_arbitrary_word():
    """A bare date followed by ANY word (not a known unit) must still be
    excluded as a date -- the original `[A-Za-z%]` lookahead matched any
    following word at all, so "4/12 with cardiology" was misread as
    unit-bearing and never excluded."""
    assert _extract_number_tokens("Follow up 4/12 with cardiology.") == set()
    assert _extract_number_tokens("return 4/12 for labs") == set()


def test_extract_number_tokens_keeps_slash_pair_followed_by_known_unit():
    assert _extract_number_tokens("1/2 tablet") == {("1/2", "tablet")}
    assert ("5/10", "mg") in _extract_number_tokens("5/10 mg daily")
    assert _extract_number_tokens("3/4 cup") != set()


def test_extract_number_tokens_keeps_slash_pair_followed_by_slash_unit():
    assert _extract_number_tokens("4/12 mg/dL") == {("4/12", "mg/dl")}


def test_numeric_parity_does_not_flag_bare_date_followed_by_unrelated_word(caplog):
    fact = Fact(id=1, category="follow_up", unit_id=1, char_start=0, char_end=1,
                text="Next visit 4/12.")
    item = _make_item("follow_up", [1], time_frame="Follow up 4/12 with cardiology.")
    model = CarePlan(follow_up=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert _numeric_parity_records(caplog) == []


def test_numeric_parity_does_not_flag_bare_date_with_different_trailing_words(caplog):
    fact = Fact(id=1, category="follow_up", unit_id=1, char_start=0, char_end=1,
                text="Follow-up 4/12 with cardiology")
    item = _make_item("follow_up", [1], time_frame="Follow up 4/12 at the clinic.")
    model = CarePlan(follow_up=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert _numeric_parity_records(caplog) == []


def test_numeric_parity_unit_mismatch_log_never_leaks_a_non_unit_word(caplog):
    """PHI guard: when a rendered field's number matches a cited fact's
    number but the following word is not a real unit (e.g. a drug name
    swapped in), the log must never contain that word -- only the
    '<non-unit word>' placeholder."""
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="take 5 tablets")
    item = _make_item("medications", [1], instructions="Take 5 Methamphetamine tablets")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any(
        "medications[0].instructions" in r.message and "different or missing unit" in r.message
        for r in records
    )
    for record in caplog.records:
        assert "methamphetamine" not in record.message.lower()
    assert any("<non-unit word>" in r.message for r in records)


def test_numeric_parity_unit_mismatch_still_logs_a_known_unit(caplog):
    """Existing mg-vs-mL behavior is unchanged: a real unit is still logged
    verbatim (not replaced with the placeholder)."""
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="warfarin 5 mg")
    item = _make_item("medications", [1], dosage="5 mL")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any("unit='ml'" in r.message for r in records)
    assert not any("<non-unit word>" in r.message for r in records)


def test_unit_word_re_is_derived_from_max_length_constant():
    assert f"{{0,{_UNIT_WORD_MAX_LENGTH - 1}}}" in _UNIT_WORD_RE


def test_known_unit_words_is_lowercase_frozenset():
    assert isinstance(_KNOWN_UNIT_WORDS, frozenset)
    assert all(w == w.lower() for w in _KNOWN_UNIT_WORDS)
    assert "mg" in _KNOWN_UNIT_WORDS
    assert "tablet" in _KNOWN_UNIT_WORDS


# ---------------------------------------------------------------------------
# Parity check: _check_numeric_parity, exercised through _verify_assembly
# ---------------------------------------------------------------------------

def test_numeric_parity_passes_silently_when_dosage_matches_cited_fact(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol 25 mg")
    item = _make_item("medications", [1], dosage="25 mg")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert _numeric_parity_records(caplog) == []


def test_numeric_parity_logs_when_dosage_drifts_from_cited_fact(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol 25mg")
    item = _make_item("medications", [1], dosage="250 mg")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        result = _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any("medications[0].dosage" in r.message for r in records)
    # log-only: the field itself must be untouched.
    assert result.medications[0].dosage == "250 mg"


def test_numeric_parity_logs_unit_mismatch_as_a_distinct_message_from_missing_value(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="warfarin 5 mg")
    item = _make_item("medications", [1], dosage="5 mL")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any(
        "medications[0].dosage" in r.message and "different or missing unit" in r.message
        for r in records
    )
    assert not any("not found in any" in r.message for r in records)


def test_numeric_parity_checks_union_of_multiple_cited_facts(caplog):
    fact_1 = Fact(id=1, category="tests", unit_id=1, char_start=0, char_end=1,
                  text="glucose 120 mg/dL")
    fact_2 = Fact(id=2, category="tests", unit_id=1, char_start=0, char_end=1,
                  text="glucose 130 mg/dL")
    item = _make_item(
        "tests", [1, 2],
        description="Your glucose readings were 120 mg/dL and 130 mg/dL.",
    )
    model = CarePlan(tests=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact_1, fact_2])

    assert not any("tests[0].description" in r.message for r in _numeric_parity_records(caplog))


def test_numeric_parity_ignores_field_with_no_digits(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol 25 mg")
    item = _make_item("medications", [1], why="Take this to help your heart.")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert not any("medications[0].why" in r.message for r in _numeric_parity_records(caplog))


def test_numeric_parity_flags_added_reference_range_not_in_any_cited_fact(caplog):
    fact = Fact(id=1, category="tests", unit_id=1, char_start=0, char_end=1,
                text="A1c 7.2%")
    item = _make_item(
        "tests", [1],
        description="A1c 7.2% (normal range 4.0-5.6%)",
    )
    model = CarePlan(tests=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = [r for r in _numeric_parity_records(caplog) if "tests[0].description" in r.message]
    assert len(records) == 1
    assert "not found in any" in records[0].message


def test_numeric_parity_does_not_flag_bid_to_twice_daily_rewrite(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol twice daily")
    item = _make_item("medications", [1], frequency="twice a day")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert _numeric_parity_records(caplog) == []


def test_numeric_parity_does_not_flag_date_reformatted_to_month_name(caplog):
    fact = Fact(id=1, category="follow_up", unit_id=1, char_start=0, char_end=1,
                text="follow-up 4/12")
    item = _make_item("follow_up", [1], time_frame="Follow up on April 12.")
    model = CarePlan(follow_up=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    assert _numeric_parity_records(caplog) == []


def test_numeric_parity_summary_checked_against_summary_fact_ids(caplog):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol 25 mg")
    model = CarePlan(summary="You are taking 250 mg of metoprolol.", summary_fact_ids=[1])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any("summary" in r.message and "summary" in r.message for r in records)
    assert any("summary[-].summary" in r.message for r in records)


def test_numeric_parity_skips_diagnosis_and_reason_for_visit(caplog):
    model = CarePlan(
        diagnosis=Diagnosis(
            changed_since_last_visit="",
            details=[
                DiagnosisDetail(
                    title="Heart failure",
                    plain_name="weak heart pumping",
                    description="Your ejection fraction is 42%, but the earlier note said 55%.",
                    what_it_means_for_you="",
                    severity=None,
                )
            ],
        ),
    )

    with caplog.at_level(logging.WARNING):
        result = _verify_assembly(model, facts=[])

    assert _numeric_parity_records(caplog) == []
    assert result.diagnosis == model.diagnosis


def test_numeric_parity_log_never_contains_the_raw_digits_or_field_text(caplog):
    """PHI-adjacent guard, mirroring
    test_verify_assembly_thin_field_log_never_contains_clinical_text: the
    field path may be logged, the mismatched value itself never may."""
    distinctive_value = "777 mg"
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="unrelated note with no numbers in it")
    item = _make_item("medications", [1], dosage=distinctive_value)
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, [fact])

    records = _numeric_parity_records(caplog)
    assert any("medications[0].dosage" in r.message for r in records)
    for record in caplog.records:
        assert distinctive_value not in record.message
        assert repr(distinctive_value) not in record.message
        assert "777" not in record.message


def test_check_numeric_parity_called_directly_is_log_only(caplog):
    """_check_numeric_parity itself (not just via _verify_assembly) never
    mutates the model it is given -- it is called on the already-filtered
    model as the last statement of _verify_assembly, but is exercised here
    directly to confirm its own contract independent of that wiring."""
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text="metoprolol 25mg")
    item = _make_item("medications", [1], dosage="250 mg")
    model = CarePlan(medications=[item])

    with caplog.at_level(logging.WARNING):
        _check_numeric_parity(model, [fact])

    assert any("medications[0].dosage" in r.message for r in _numeric_parity_records(caplog))
    assert model.medications[0].dosage == "250 mg"


@pytest.mark.parametrize(
    "dosage,fact_text",
    [
        pytest.param("25 mg", "metoprolol 25 mg", id="match"),
        pytest.param("250 mg", "metoprolol 25mg", id="mismatch"),
    ],
)
def test_numeric_parity_never_mutates_or_drops_the_care_plan(dosage, fact_text):
    fact = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1,
                text=fact_text)
    item = _make_item("medications", [1], dosage=dosage)
    model = CarePlan(medications=[item])

    result = _verify_assembly(model, [fact])

    assert len(result.medications) == 1
    assert result.medications[0].dosage == dosage
    assert result.medications[0].source_fact_ids == [1]
