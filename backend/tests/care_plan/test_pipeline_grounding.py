"""Ledger-parsing, prompt-construction, and deterministic post-check tests
for grounding (PRD 03 §7.3). Uses real Unit/Fact/_GroundedFactRaw fixtures
throughout -- only the prompt-construction tests touch a monkeypatched
_generate_json; everything else exercises pure, deterministic functions."""

import pytest

from care_plan.pipeline import (
    CarePlanPipeline,
    _GroundedFactRaw,
    _QUOTE_LONG_WORD_MIN_LENGTH,
    _QUOTE_MIN_LENGTH,
    _format_units_for_prompt,
    _is_informative_quote,
    _is_verbatim_quote,
    _locate_quote_offsets,
    _verify_ledger,
)
from errors import ErrorCode, SimplifyError
from models.ledger import Fact, Unit
from utils.term_detection import format_abbreviations_for_prompt
from utils.text_normalization import normalize_text, normalize_with_offsets


# ---------------------------------------------------------------------------
# Prompt-construction tests
# ---------------------------------------------------------------------------

def test_format_units_for_prompt_groups_consecutive_same_page_units_under_one_header():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="first line"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="second line"),
        Unit(id=3, file="note.pdf", page=1, line=3, text="third line"),
    ]

    result = _format_units_for_prompt(units)
    lines = result.split("\n")

    headers = [line for line in lines if line == "=== note.pdf, page 1 ==="]
    assert len(headers) == 1
    assert "[1] first line" in lines
    assert "[2] second line" in lines
    assert "[3] third line" in lines


def test_format_units_for_prompt_emits_new_header_on_page_change():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="first line"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="second line"),
        Unit(id=3, file="note.pdf", page=2, line=1, text="third line"),
    ]

    result = _format_units_for_prompt(units)
    headers = [line for line in result.split("\n") if line.startswith("===")]

    assert headers == ["=== note.pdf, page 1 ===", "=== note.pdf, page 2 ==="]


def test_format_units_for_prompt_emits_new_header_on_file_change():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="first line"),
        Unit(id=2, file="other.pdf", page=1, line=1, text="second line"),
    ]

    result = _format_units_for_prompt(units)
    headers = [line for line in result.split("\n") if line.startswith("===")]

    assert headers == ["=== note.pdf, page 1 ===", "=== other.pdf, page 1 ==="]


def test_ground_builds_prompt_with_abbreviations_and_units():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Pt to cont. metoprolol 25mg BID"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="Follow up in two weeks for bloodwork"),
    ]
    abbreviations = [{"term": "BID", "expansion": "twice daily"}]
    captured: dict = {}

    def _fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        return [
            {
                "category": "medications",
                "unit_id": 1,
                "quote": "metoprolol 25mg",
                "text": "Continue metoprolol 25mg twice daily.",
            },
        ]

    pipeline._generate_json = _fake_generate_json
    pipeline.ground(units, abbreviations)

    prompt = captured["prompt"]
    assert format_abbreviations_for_prompt(abbreviations) in prompt
    for unit in units:
        assert f"[{unit.id}]" in prompt


# ---------------------------------------------------------------------------
# Deterministic post-check tests (D1) -- no LLM mock
# ---------------------------------------------------------------------------

def test_is_verbatim_quote_exact_match():
    assert _is_verbatim_quote("metoprolol 25mg", "Pt to cont. metoprolol 25mg BID") is True


def test_is_verbatim_quote_tolerates_whitespace_noise():
    unit_text = "cont.  metoprolol"
    quote = "cont. metoprolol"
    assert _is_verbatim_quote(quote, unit_text) is True


def test_is_verbatim_quote_tolerates_case_difference():
    unit_text = "Pt to cont. METOPROLOL 25mg BID"
    quote = "metoprolol 25mg"
    assert _is_verbatim_quote(quote, unit_text) is True


def test_is_verbatim_quote_rejects_fabricated_quote():
    unit_text = "Pt to cont. metoprolol 25mg BID"
    quote = "increase metoprolol to 50mg"
    assert _is_verbatim_quote(quote, unit_text) is False


def test_is_verbatim_quote_rejects_blank_quote():
    unit_text = "Pt to cont. metoprolol 25mg BID"
    assert _is_verbatim_quote("", unit_text) is False
    assert _is_verbatim_quote("   ", unit_text) is False


def test_is_verbatim_quote_rejects_quote_that_normalizes_to_empty():
    # Non-blank raw quotes (quote.strip() is truthy) that normalize_text
    # nonetheless reduces to "" -- normalize_text in x is vacuously True
    # for any x, so these must be rejected against the NORMALIZED form,
    # not merely the raw/whitespace form (review-2026-09-13.md, Blocking #1).
    unit_text = "Patient has hypertension and continues lisinopril"

    plus_minus_quote = "±" * 12
    assert normalize_text(plus_minus_quote) == ""
    assert _is_verbatim_quote(plus_minus_quote, unit_text) is False

    symbol_quote = "©§×÷" * 3  # (c)(section)(x)(div) x3
    assert normalize_text(symbol_quote) == ""
    assert _is_verbatim_quote(symbol_quote, unit_text) is False

    cjk_quote = "中文の" * 4  # CJK, well over the length floor
    assert normalize_text(cjk_quote) == ""
    assert _is_verbatim_quote(cjk_quote, unit_text) is False


# ---------------------------------------------------------------------------
# Quote informativeness floor tests (D2)
# ---------------------------------------------------------------------------

def test_is_informative_quote_accepts_short_numeric_quote():
    assert _is_informative_quote("40 mg") is True


def test_is_informative_quote_accepts_short_drug_name():
    assert len("warfarin") < _QUOTE_MIN_LENGTH
    assert len("warfarin") >= _QUOTE_LONG_WORD_MIN_LENGTH
    assert _is_informative_quote("warfarin") is True


def test_is_informative_quote_rejects_short_common_word():
    assert _is_informative_quote("with") is False


def _short_word_phrase(length: int) -> str:
    """Build a phrase of exactly `length` characters out of words all
    shorter than _QUOTE_LONG_WORD_MIN_LENGTH and containing no digit, so
    only the bare length floor of _is_informative_quote is exercised."""
    word = "a" * (_QUOTE_LONG_WORD_MIN_LENGTH - 1)
    phrase = ""
    while len(phrase) < length:
        phrase += word if not phrase else " " + word
    phrase = phrase[:length]
    assert len(phrase) == length
    assert not any(ch.isdigit() for ch in phrase)
    assert all(len(w) < _QUOTE_LONG_WORD_MIN_LENGTH for w in phrase.split())
    return phrase


def test_is_informative_quote_boundary_at_min_length():
    at_min = _short_word_phrase(_QUOTE_MIN_LENGTH)
    assert _is_informative_quote(at_min) is True

    below_min = _short_word_phrase(_QUOTE_MIN_LENGTH - 1)
    assert _is_informative_quote(below_min) is False


# ---------------------------------------------------------------------------
# Offset-recovery tests
# ---------------------------------------------------------------------------

def test_locate_quote_offsets_exact_match():
    unit_text = "Pt to cont. metoprolol 25mg BID"
    quote = "metoprolol 25mg"

    char_start, char_end = _locate_quote_offsets(quote, unit_text)

    assert unit_text[char_start:char_end] == quote


def test_locate_quote_offsets_recovers_full_span_across_whitespace_noise():
    unit_text = "Pt to cont.  metoprolol 25mg BID"  # raw double space
    quote = "cont. metoprolol 25mg"  # single space

    assert _is_verbatim_quote(quote, unit_text) is True
    char_start, char_end = _locate_quote_offsets(quote, unit_text)

    assert unit_text[char_start:char_end] == "cont.  metoprolol 25mg"


def test_locate_quote_offsets_recovers_full_span_across_tab_noise():
    unit_text = "Pt to cont.\tmetoprolol 25mg BID"  # raw tab
    quote = "cont. metoprolol 25mg"  # single space

    assert _is_verbatim_quote(quote, unit_text) is True
    char_start, char_end = _locate_quote_offsets(quote, unit_text)

    assert unit_text[char_start:char_end] == "cont.\tmetoprolol 25mg"


def test_locate_quote_offsets_recovers_span_despite_case_difference():
    unit_text = "Pt to cont. METOPROLOL 25mg BID"
    quote = "metoprolol 25mg"

    assert _is_verbatim_quote(quote, unit_text) is True
    char_start, char_end = _locate_quote_offsets(quote, unit_text)

    assert unit_text[char_start:char_end] == "METOPROLOL 25mg"


def test_locate_quote_offsets_uses_first_occurrence_when_quote_repeats():
    unit_text = "warfarin 5mg noted on admission. Later, warfarin 5mg confirmed."
    quote = "warfarin 5mg"

    char_start, char_end = _locate_quote_offsets(quote, unit_text)

    first_index = unit_text.find(quote)
    second_index = unit_text.find(quote, first_index + 1)
    assert second_index > first_index  # sanity: the quote really repeats
    assert char_start == first_index
    assert unit_text[char_start:char_end] == quote


_NORMALIZE_EQUIVALENCE_CASES = [
    "Hello World",
    "foo   bar",
    "  hello  ",
    "café",
    "",
    "  Hypertension  MANAGEMENT  ",
    "line one\nline two",
    "word1\t\tword2",
    "é",
]


def test_normalize_with_offsets_matches_normalize_text():
    for text in _NORMALIZE_EQUIVALENCE_CASES:
        normalized, spans = normalize_with_offsets(text)
        assert normalized == normalize_text(text)
        assert len(spans) == len(normalized)


# ---------------------------------------------------------------------------
# _verify_ledger-level tests (drafts are _GroundedFactRaw, results are Fact)
# ---------------------------------------------------------------------------

def test_verify_ledger_drops_fact_citing_unknown_unit_id():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily"),
    ]
    drafts = [
        _GroundedFactRaw(category="medications", unit_id=1, quote="warfarin 5mg", text="Take warfarin 5mg daily."),
        _GroundedFactRaw(category="medications", unit_id=999, quote="warfarin 5mg", text="bad citation"),
    ]

    facts = _verify_ledger(drafts, units)

    assert len(facts) == 1
    assert facts[0].unit_id == 1
    assert facts[0].text == "Take warfarin 5mg daily."


def test_verify_ledger_drops_fact_with_fabricated_quote():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Pt to cont. metoprolol 25mg BID"),
    ]
    drafts = [
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="metoprolol 25mg",
            text="Continue metoprolol 25mg.",
        ),
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="increase metoprolol to 50mg",
            text="fabricated fact",
        ),
    ]

    facts = _verify_ledger(drafts, units)

    assert len(facts) == 1
    assert facts[0].text == "Continue metoprolol 25mg."


def test_verify_ledger_drops_fact_failing_informativeness_floor():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient to continue with metoprolol 25mg"),
    ]
    drafts = [
        _GroundedFactRaw(category="medications", unit_id=1, quote="with", text="uninformative fact"),
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="metoprolol 25mg",
            text="Continue metoprolol 25mg.",
        ),
    ]

    facts = _verify_ledger(drafts, units)

    assert len(facts) == 1
    assert facts[0].text == "Continue metoprolol 25mg."


def test_verify_ledger_populates_char_start_and_char_end_from_quote():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Pt to cont. metoprolol 25mg BID"),
    ]
    drafts = [
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="metoprolol 25mg",
            text="Continue metoprolol 25mg.",
        ),
    ]

    facts = _verify_ledger(drafts, units)

    assert len(facts) == 1
    fact = facts[0]
    assert isinstance(fact.char_start, int)
    assert isinstance(fact.char_end, int)

    recovered = units[0].text[fact.char_start:fact.char_end]
    assert normalize_text(recovered) == normalize_text("metoprolol 25mg")

    assert hasattr(fact, "quote") is False
    assert "quote" not in Fact.model_fields


def test_verify_ledger_renumbers_surviving_facts_contiguously():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="Follow up in two weeks for bloodwork"),
        Unit(id=3, file="note.pdf", page=1, line=3, text="Continue metoprolol 25mg BID"),
    ]
    drafts = [
        _GroundedFactRaw(category="medications", unit_id=1, quote="warfarin 5mg", text="Take warfarin 5mg daily."),
        _GroundedFactRaw(category="follow_up", unit_id=999, quote="bloodwork", text="dropped -- bad unit_id"),
        _GroundedFactRaw(category="medications", unit_id=3, quote="metoprolol 25mg", text="Continue metoprolol 25mg."),
    ]

    facts = _verify_ledger(drafts, units)

    assert [fact.id for fact in facts] == [1, 2]
    assert [fact.text for fact in facts] == [
        "Take warfarin 5mg daily.",
        "Continue metoprolol 25mg.",
    ]


def test_verify_ledger_preserves_order_of_surviving_facts():
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Continue metoprolol 25mg BID"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="Patient started on warfarin 5mg daily"),
        Unit(id=3, file="note.pdf", page=1, line=3, text="Follow up in two weeks for bloodwork"),
    ]
    # Deliberately out of category-sort order (follow_up before medications)
    # to prove _verify_ledger doesn't resort survivors by category or anything else.
    drafts = [
        _GroundedFactRaw(category="follow_up", unit_id=3, quote="bloodwork", text="Get bloodwork done."),
        _GroundedFactRaw(category="medications", unit_id=1, quote="metoprolol 25mg", text="Continue metoprolol 25mg."),
        _GroundedFactRaw(category="medications", unit_id=2, quote="warfarin 5mg", text="Take warfarin 5mg daily."),
    ]

    facts = _verify_ledger(drafts, units)

    assert [fact.category for fact in facts] == ["follow_up", "medications", "medications"]
    assert [fact.text for fact in facts] == [
        "Get bloodwork done.",
        "Continue metoprolol 25mg.",
        "Take warfarin 5mg daily.",
    ]


def test_verify_ledger_drops_fact_whose_quote_normalizes_to_empty():
    # Regression for review-2026-09-13.md Blocking #1: a quote made of
    # characters normalize_text strips entirely (here, plus-minus signs)
    # must not survive to become a Fact -- and, before the fix, the
    # fabricated fact's offsets resolved to (0, len(unit_text)), i.e. the
    # ENTIRE unit, because normalize_text(quote) == "" is vacuously a
    # substring of everything.
    unit_text = "Patient has hypertension and continues lisinopril"
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text=unit_text),
    ]
    drafts = [
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="lisinopril",
            text="Continue lisinopril.",
        ),
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="±" * 12,
            text="FABRICATED: patient takes unicorn tears 500mg twice daily",
        ),
    ]

    facts = _verify_ledger(drafts, units)

    assert len(facts) == 1
    assert facts[0].text == "Continue lisinopril."
    assert not any(
        fact.char_start == 0 and fact.char_end == len(unit_text)
        for fact in facts
    )


def test_verify_ledger_drops_quote_normalizing_to_empty_against_empty_unit():
    # Regression for review-2026-09-13.md Blocking #1's second manifestation:
    # when the cited unit's text is empty/all-whitespace, `spans` from
    # normalize_with_offsets is [], so before the fix
    # _locate_quote_offsets(quote, "") raised an unhandled IndexError
    # instead of _verify_ledger cleanly dropping the draft.
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text=""),
        Unit(id=2, file="note.pdf", page=1, line=2, text="   "),
    ]
    drafts = [
        _GroundedFactRaw(
            category="medications", unit_id=1, quote="±" * 12,
            text="FABRICATED against empty unit",
        ),
        _GroundedFactRaw(
            category="medications", unit_id=2, quote="±" * 12,
            text="FABRICATED against whitespace-only unit",
        ),
    ]

    facts = _verify_ledger(drafts, units)

    assert facts == []


# ---------------------------------------------------------------------------
# ground()-level fatal-failure test
# ---------------------------------------------------------------------------

def test_ground_raises_when_verified_ledger_is_empty():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily"),
    ]
    pipeline._generate_json = lambda *args, **kwargs: [
        {"category": "medications", "unit_id": 999, "quote": "warfarin 5mg", "text": "cites nonexistent unit"},
    ]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.ground(units, [])

    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
    assert "zero" in exc_info.value.detail.lower() or "empty" in exc_info.value.detail.lower()


def test_ground_validation_error_detail_excludes_patient_content():
    """Finding 1b regression: when the grounding LLM's structured output
    fails Pydantic validation, `_GroundedFactRaw`'s ValidationError embeds
    the actual rejected value (`str(e)`'s `input_value=...`) -- here, a
    patient-derived marker standing in for real clinical text sent back by
    the LLM in an invalid field. The raised SimplifyError.detail must never
    contain it (it flows into Firestore error_data.details, which the
    frontend's live listener reads); it must be built only from each
    error's structural `loc`/`type` (see `_validation_error_detail`)."""
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily"),
    ]
    marker = "PATIENT_MARKER_XYZ"
    pipeline._generate_json = lambda *args, **kwargs: [
        # `category` only accepts a fixed set of Literal values, so an
        # arbitrary string fails Pydantic validation with the marker
        # embedded verbatim as the error's `input_value`.
        {"category": marker, "unit_id": 1, "quote": "warfarin 5mg", "text": "note text"},
    ]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.ground(units, [])

    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
    assert marker not in exc_info.value.detail
    assert "category" in exc_info.value.detail
