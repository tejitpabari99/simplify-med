"""Tests for SP-09: prompt .txt files load correctly and placeholders match callers."""

import pytest

from care_plan.pipeline import (
    _ASSEMBLE_PROMPT,
    _CORRECT_PROMPT,
    _GROUND_PROMPT,
    _REVIEW_PROMPT,
    _STYLE_RULES,
)


# ---------------------------------------------------------------------------
# 1. Smoke / import tests — files exist and are non-empty
# ---------------------------------------------------------------------------

def test_ground_prompt_is_non_empty_string():
    assert isinstance(_GROUND_PROMPT, str) and len(_GROUND_PROMPT) > 0


def test_assemble_prompt_is_non_empty_string():
    assert isinstance(_ASSEMBLE_PROMPT, str) and len(_ASSEMBLE_PROMPT) > 0


# ---------------------------------------------------------------------------
# 2. Format-key tests — all expected placeholders are present
# ---------------------------------------------------------------------------

def test_ground_prompt_accepts_all_keys():
    result = _GROUND_PROMPT.format(schema="{}", abbrev_block="abbr", units_block="[1] text")
    assert "abbr" in result
    assert "[1] text" in result
    assert "{}" in result


def test_ground_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _GROUND_PROMPT.format(schema="{}", abbrev_block="abbr")
        # missing `units_block`


def test_assemble_prompt_accepts_all_keys():
    result = _ASSEMBLE_PROMPT.format(
        schema="{}",
        facts_block="[1] medications: x",
        style_rules="STYLE_RULES_MARKER",
        sub_block="s",
        medical_block="m",
        abbrev_block="a",
    )
    assert "{}" in result
    assert "[1] medications: x" in result
    assert "STYLE_RULES_MARKER" in result
    assert "s" in result
    assert "m" in result
    assert "a" in result


def test_assemble_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _ASSEMBLE_PROMPT.format(schema="{}", sub_block="s", medical_block="m", abbrev_block="a")
        # missing `facts_block` (and `style_rules`)


# ---------------------------------------------------------------------------
# 3. Ground prompt content guards (PRD 03 §7.1)
# ---------------------------------------------------------------------------

def test_ground_prompt_contains_contrast_dye_boundary_rule():
    assert "contrast dye" in _GROUND_PROMPT


def test_ground_prompt_lists_all_eight_categories():
    for category in (
        "reason_for_visit",
        "diagnosis",
        "medications",
        "tests",
        "procedures",
        "other",
        "follow_up",
        "warning_signs",
    ):
        assert category in _GROUND_PROMPT
    assert "low_priority" not in _GROUND_PROMPT


# ---------------------------------------------------------------------------
# 4. Assemble prompt content guards (PRD 04 §7.2)
# ---------------------------------------------------------------------------

def test_assemble_prompt_contains_not_stated_sentinel():
    assert "Not stated in your note." in _ASSEMBLE_PROMPT


def test_assemble_prompt_contains_merge_example():
    assert "left and right heart arteries" in _ASSEMBLE_PROMPT


def test_assemble_prompt_questions_rule_has_no_minimum():
    assert "no minimum" in _ASSEMBLE_PROMPT
    assert "exactly three" not in _ASSEMBLE_PROMPT
    assert "exactly 3" not in _ASSEMBLE_PROMPT


def test_assemble_prompt_lists_all_eight_mapping_rows():
    mapping_start = _ASSEMBLE_PROMPT.index("MAPPING")
    mapping_section = _ASSEMBLE_PROMPT[mapping_start:]
    for category in (
        "reason_for_visit",
        "diagnosis",
        "medications",
        "tests",
        "procedures",
        "other",
        "follow_up",
        "warning_signs",
    ):
        assert category in mapping_section


# ---------------------------------------------------------------------------
# 5. Review / correct / style_rules prompt tests (PRD 05 §7.2)
# ---------------------------------------------------------------------------

def test_review_prompt_is_non_empty_string():
    assert isinstance(_REVIEW_PROMPT, str) and len(_REVIEW_PROMPT) > 0


def test_review_prompt_accepts_all_keys():
    result = _REVIEW_PROMPT.format(
        schema="{}",
        facts_block="[1] medications: x",
        care_plan_block="{}",
    )
    assert "{}" in result
    assert "[1] medications: x" in result


def test_review_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _REVIEW_PROMPT.format(schema="{}", facts_block="[1] medications: x")
        # missing `care_plan_block`


def test_review_prompt_names_the_three_op_vocabulary():
    assert '"correct"' in _REVIEW_PROMPT
    assert '"not_stated"' in _REVIEW_PROMPT
    assert '"remove"' in _REVIEW_PROMPT


def test_review_prompt_scopes_not_stated_to_four_why_fields():
    for path in (
        "medications[N].why",
        "tests[N].why",
        "procedures[N].why",
        "other[N].why",
    ):
        assert path in _REVIEW_PROMPT


def test_correct_prompt_is_non_empty_string():
    assert isinstance(_CORRECT_PROMPT, str) and len(_CORRECT_PROMPT) > 0


def test_correct_prompt_accepts_all_keys():
    result = _CORRECT_PROMPT.format(
        corrections_block="c",
        style_rules="s",
        care_plan_block="{}",
        schema="{}",
    )
    assert "c" in result
    assert "s" in result
    assert "{}" in result


def test_correct_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _CORRECT_PROMPT.format(style_rules="s", care_plan_block="{}", schema="{}")
        # missing `corrections_block`


def test_correct_prompt_contains_pii_sweep_instruction():
    assert "PII SWEEP" in _CORRECT_PROMPT


def test_correct_prompt_contains_not_stated_sentinel():
    assert "Not stated in your note." in _CORRECT_PROMPT


def test_style_rules_is_non_empty_and_shared():
    assert isinstance(_STYLE_RULES, str) and len(_STYLE_RULES) > 0
    assert "{style_rules}" in _ASSEMBLE_PROMPT
    # A distinctive phrase from the extracted PII paragraph now lives only in
    # _STYLE_RULES -- confirm it was moved out of assemble_and_render.txt,
    # not merely copied.
    assert "Doctor Alok Singh" in _STYLE_RULES
    assert "Doctor Alok Singh" not in _ASSEMBLE_PROMPT


# ---------------------------------------------------------------------------
# 6. NUMERACY content-regression tests (PRD 10 §4.1, §7.1)
# ---------------------------------------------------------------------------

def test_style_rules_contains_numeracy_block():
    assert "NUMERACY" in _STYLE_RULES


def test_style_rules_numeracy_forbids_added_label():
    assert "blood pressure 158/96" in _STYLE_RULES
    assert "unless the fact itself uses that word" in _STYLE_RULES


def test_style_rules_numeracy_forbids_reference_range():
    assert "normal range 4.0-5.6%" in _STYLE_RULES


def test_style_rules_numeracy_forbids_rounding():
    assert "ejection fraction 42%" in _STYLE_RULES


def test_style_rules_numeracy_forbids_unit_conversion():
    assert "creatinine 1.4 mg/dL" in _STYLE_RULES


def test_style_rules_numeracy_forbids_percentage_frequency_reframe():
    assert "3 out of 10 times" in _STYLE_RULES


def test_style_rules_numeracy_permits_source_stated_interpretation():
    assert "indicating poor control" in _STYLE_RULES


def test_assemble_and_correct_prompts_both_receive_numeracy_block():
    assembled = _ASSEMBLE_PROMPT.format(
        schema="{}",
        facts_block="[1] medications: x",
        style_rules=_STYLE_RULES,
        sub_block="s",
        medical_block="m",
        abbrev_block="a",
    )
    corrected = _CORRECT_PROMPT.format(
        corrections_block="c",
        style_rules=_STYLE_RULES,
        care_plan_block="{}",
        schema="{}",
    )
    assert "NUMERACY" in assembled
    assert "NUMERACY" in corrected
