"""Tests for SP-09: prompt .txt files load correctly and placeholders match callers."""

import pytest

from care_plan.pipeline import (
    _CLARIFY_PROMPT,
    _SIMPLIFY_PROMPT,
    _STRUCTURE_PROMPT,
    _STRUCTURING_SCHEMA,
)


# ---------------------------------------------------------------------------
# 1. Smoke / import tests — files exist and are non-empty
# ---------------------------------------------------------------------------

def test_simplify_prompt_is_non_empty_string():
    assert isinstance(_SIMPLIFY_PROMPT, str) and len(_SIMPLIFY_PROMPT) > 0


def test_clarify_prompt_is_non_empty_string():
    assert isinstance(_CLARIFY_PROMPT, str) and len(_CLARIFY_PROMPT) > 0


def test_structure_prompt_is_non_empty_string():
    assert isinstance(_STRUCTURE_PROMPT, str) and len(_STRUCTURE_PROMPT) > 0


# ---------------------------------------------------------------------------
# 2. Format-key tests — all expected placeholders are present
# ---------------------------------------------------------------------------

def test_simplify_prompt_accepts_all_keys():
    result = _SIMPLIFY_PROMPT.format(
        sub_block="sub",
        medical_block="med",
        abbrev_block="abbr",
        text="note text",
    )
    assert "sub" in result
    assert "med" in result
    assert "abbr" in result
    assert "note text" in result


def test_simplify_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _SIMPLIFY_PROMPT.format(sub_block="s", medical_block="m", abbrev_block="a")
        # missing `text`


def test_clarify_prompt_accepts_all_keys():
    result = _CLARIFY_PROMPT.format(abbreviation_section="", text="patient text")
    assert "patient text" in result


def test_clarify_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _CLARIFY_PROMPT.format(text="patient text")
        # missing `abbreviation_section`


def test_structure_prompt_accepts_all_keys():
    result = _STRUCTURE_PROMPT.format(schema='{"type":"object"}', text="structured text")
    assert "structured text" in result
    assert '{"type":"object"}' in result


def test_structure_prompt_raises_on_missing_key():
    with pytest.raises(KeyError):
        _STRUCTURE_PROMPT.format(schema='{"type":"object"}')
        # missing `text`


# ---------------------------------------------------------------------------
# 3. abbreviation_section empty-string test
# ---------------------------------------------------------------------------

def test_clarify_prompt_with_empty_abbreviation_section_consumes_placeholder():
    result = _CLARIFY_PROMPT.format(abbreviation_section="", text="sample")
    assert "{abbreviation_section}" not in result


def test_clarify_prompt_with_abbreviation_section_present():
    abbrev_text = "\nIf any of these abbreviations remain in the text, expand them:\n- \"HTN\" -> \"high blood pressure\"\n"
    result = _CLARIFY_PROMPT.format(abbreviation_section=abbrev_text, text="sample")
    assert "HTN" in result
    assert "high blood pressure" in result


# ---------------------------------------------------------------------------
# 4. Whitespace-parity tests — new .format() path matches old inline f-string
# ---------------------------------------------------------------------------

def test_simplify_prompt_parity_with_inline_fstring():
    sub_block = "- hypertension → high blood pressure"
    medical_block = "- HTN"
    abbrev_block = "- BP → blood pressure"
    text = "Patient has HTN."

    # Reproduce the original inline f-string exactly (copied from pre-SP-09 source)
    expected = f"""You are a health literacy expert helping rewrite a provider note for a patient.

Rewrite the note so it is easier to understand at about a 6th-grade reading level.

Use these plain-language replacement suggestions when they fit naturally in context:
{sub_block}

Preserve these medical terms exactly. Do not define them inline. They will be explained separately in the UI:
{medical_block}

Expand these abbreviations when they appear:
{abbrev_block}

Rules:
1. Keep all medical facts from the source accurate.
2. Do not add diagnosis, medical advice, urgency, prognosis, or treatment interpretation.
3. Do not remove important information.
4. Use short sentences (under 20 words where possible).
5. Use active voice.
6. Use "you" and "your."
7. Do not include the patient's name, date of birth, address, insurance details, or other identifiers.
8. Do not add parenthetical definitions.
9. Do not return term annotations or spans.
10. Output only the rewritten text; no preamble, no commentary.

SOURCE NOTE:
{text}

REWRITTEN NOTE:"""

    actual = _SIMPLIFY_PROMPT.format(
        sub_block=sub_block,
        medical_block=medical_block,
        abbrev_block=abbrev_block,
        text=text,
    )
    assert actual == expected


def test_clarify_prompt_parity_no_abbreviations():
    text = "Take your medication daily."
    abbreviation_section = ""

    expected = f"""You are a health literacy expert helping patients understand what they need to do.

Review the text below and:
1. Use active voice throughout.
2. Address the patient as "you."
3. Start every patient action with a clear verb: Take / Call / Schedule / Ask / Bring / Watch / Avoid / Continue / Stop.
4. Do not fabricate numbers. Do not convert vague wording into exact numbers unless the source contains the exact number.
5. Do not add urgency unless the source implies urgency.
6. Do not create new medical advice.
7. Break multi-step instructions into separate steps.
8. Output only the improved text; no commentary, no headings.
{abbreviation_section}
TEXT:
{text}

IMPROVED TEXT:"""

    actual = _CLARIFY_PROMPT.format(abbreviation_section=abbreviation_section, text=text)
    assert actual == expected


def test_clarify_prompt_parity_with_abbreviations():
    text = "Take your medication daily."
    abbrev_list = '- "HTN" -> "high blood pressure"'
    abbreviation_section = f"\nIf any of these abbreviations remain in the text, expand them:\n{abbrev_list}\n"

    expected = f"""You are a health literacy expert helping patients understand what they need to do.

Review the text below and:
1. Use active voice throughout.
2. Address the patient as "you."
3. Start every patient action with a clear verb: Take / Call / Schedule / Ask / Bring / Watch / Avoid / Continue / Stop.
4. Do not fabricate numbers. Do not convert vague wording into exact numbers unless the source contains the exact number.
5. Do not add urgency unless the source implies urgency.
6. Do not create new medical advice.
7. Break multi-step instructions into separate steps.
8. Output only the improved text; no commentary, no headings.
{abbreviation_section}
TEXT:
{text}

IMPROVED TEXT:"""

    actual = _CLARIFY_PROMPT.format(abbreviation_section=abbreviation_section, text=text)
    assert actual == expected


def test_structure_prompt_parity_with_inline_fstring():
    text = "Patient is stable."

    expected = f"""You are structuring a simplified provider note for a patient.

Return JSON only. Use this schema:
{_STRUCTURING_SCHEMA}

Rules:
1. Use only information found in the source text.
2. Do not add diagnosis, urgency, prognosis, or medical advice not in the source.
3. If the source does not contain a field, use an empty string or empty array.
4. Every medication must have a 'why' field explaining the reason for this specific patient.
5. Every warning sign must have a 'what_to_do' field: specific instruction (call doctor, go to ER, or normal side effect).
6. Classify warning sign urgency as: emergency, call_doctor, monitor, or normal_side_effect.
7. Use active voice. Address the patient as 'you'. No abbreviations.
8. Write one idea per sentence. Maximum 20 words per sentence.
9. The summary must be exactly 3 sentences: (1) why came in, (2) main conclusion, (3) most important next step.
10. Generate exactly 3 questions that help the patient understand or manage their care.
11. Put low-priority details in low_priority array.
12. Do not return term annotations or spans.
13. Output only valid JSON; no markdown, no commentary.

SOURCE TEXT:
{text}

JSON OUTPUT:"""

    actual = _STRUCTURE_PROMPT.format(schema=_STRUCTURING_SCHEMA, text=text)
    assert actual == expected
