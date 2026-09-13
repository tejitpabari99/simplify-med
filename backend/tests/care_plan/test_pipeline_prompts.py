"""Tests for SP-09: prompt .txt files load correctly and placeholders match callers."""

import pytest

from care_plan.pipeline import (
    _ASSEMBLE_PROMPT,
    _GROUND_PROMPT,
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
        sub_block="s",
        medical_block="m",
        abbrev_block="a",
    )
    assert "{}" in result
    assert "[1] medications: x" in result
    assert "s" in result
    assert "m" in result
    assert "a" in result


def test_assemble_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _ASSEMBLE_PROMPT.format(schema="{}", sub_block="s", medical_block="m", abbrev_block="a")
        # missing `facts_block`


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


def test_assemble_prompt_contains_pii_rule_for_clinicians():
    assert "Doctor Alok Singh" in _ASSEMBLE_PROMPT
    assert "your doctor" in _ASSEMBLE_PROMPT


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
