"""Assembly-level tests for CarePlanPipeline.assemble_and_render() and its
deterministic post-checks (_verify_assembly, _format_facts_for_prompt) --
PRD 04 §7.4. Uses the file's established convention: direct construction via
CarePlanPipeline.__new__(CarePlanPipeline) plus monkeypatched _generate_json,
building Fact/CarePlan fixtures directly."""

import logging

import pytest

from care_plan.pipeline import (
    CarePlanPipeline,
    _FACT_CATEGORY_ORDER,
    _format_facts_for_prompt,
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
    ReasonForVisit,
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


def _minimal_care_plan_response() -> dict:
    return {"doc_type": "care_plan", "version": "1.2", "summary": "You came in for care."}


# ---------------------------------------------------------------------------
# Category -> field mapping
# ---------------------------------------------------------------------------

def test_format_facts_for_prompt_groups_by_category_in_fixed_order():
    facts = [
        Fact(id=1, category="warning_signs", unit_id=1, char_start=0, char_end=1, text="a"),
        Fact(id=2, category="reason_for_visit", unit_id=1, char_start=0, char_end=1, text="b"),
        Fact(id=3, category="medications", unit_id=1, char_start=0, char_end=1, text="c"),
    ]

    result = _format_facts_for_prompt(facts)
    lines = result.split("\n")

    # Assert lines appear in _FACT_CATEGORY_ORDER order, not input order.
    expected_order = ["reason_for_visit", "medications", "warning_signs"]
    seen_order = [
        category for category in _FACT_CATEGORY_ORDER
        if any(line.startswith("[") and f"] {category}:" in line for line in lines)
    ]
    assert seen_order == expected_order


def test_format_facts_for_prompt_includes_fact_id_and_category():
    facts = [
        Fact(id=5, category="tests", unit_id=1, char_start=0, char_end=1, text="check glucose"),
    ]

    result = _format_facts_for_prompt(facts)

    assert result == "[5] tests: check glucose"


@pytest.mark.parametrize("category", _FACT_CATEGORY_ORDER)
def test_assemble_prompt_construction_includes_fact_for_each_category(category):
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    fact = Fact(id=1, category=category, unit_id=1, char_start=0, char_end=1, text=f"content for {category}")
    captured = {}

    def _fake_generate_json(prompt, **kwargs):
        captured["prompt"] = prompt
        return _minimal_care_plan_response()

    pipeline._generate_json = _fake_generate_json
    pipeline.assemble_and_render([fact], [], [], [])

    assert f"[1] {category}: content for {category}" in captured["prompt"]


# ---------------------------------------------------------------------------
# "Not stated" rendering
# ---------------------------------------------------------------------------

def test_assemble_and_render_accepts_not_stated_why():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "medications": [
            {"why": "Not stated in your note.", "status": "to_do", "source_fact_ids": [1]}
        ],
    }

    result = pipeline.assemble_and_render(facts, [], [], [])

    assert result.medications[0].why == "Not stated in your note."
    assert result.medications[0].source_fact_ids == [1]


def test_assemble_prompt_not_stated_rule_names_all_four_why_fields():
    from care_plan.pipeline import _ASSEMBLE_PROMPT

    not_stated_start = _ASSEMBLE_PROMPT.index("\nNOT STATED --")
    next_section_start = _ASSEMBLE_PROMPT.index("\nMERGE --")
    not_stated_section = _ASSEMBLE_PROMPT[not_stated_start:next_section_start]

    for field in ("medications", "tests", "procedures", "other"):
        assert field in not_stated_section


# ---------------------------------------------------------------------------
# Merge rule preserving variants
# ---------------------------------------------------------------------------

def test_assemble_and_render_preserves_merged_diagnosis_variants():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="x")]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "diagnosis": {
            "changed_since_last_visit": "",
            "details": [
                {
                    "title": "Coronary artery disease",
                    "plain_name": "clogged heart arteries",
                    "description": "heavy plaque in your left and right heart arteries",
                    "what_it_means_for_you": "",
                    "severity": None,
                }
            ],
        },
    }

    result = pipeline.assemble_and_render(facts, [], [], [])

    description = result.diagnosis.details[0].description
    assert "left" in description
    assert "right" in description


# ---------------------------------------------------------------------------
# Questions cap (_verify_assembly level)
# ---------------------------------------------------------------------------

def test_verify_assembly_truncates_questions_over_three():
    questions = ["q1?", "q2?", "q3?", "q4?", "q5?"]
    model = CarePlan(questions=questions)

    result = _verify_assembly(model, facts=[])

    assert result.questions == ["q1?", "q2?", "q3?"]


@pytest.mark.parametrize("questions", [[], ["q1?"], ["q1?", "q2?"]])
def test_verify_assembly_leaves_questions_under_three_unchanged(questions):
    model = CarePlan(questions=list(questions))

    result = _verify_assembly(model, facts=[])

    assert result.questions == questions


def test_verify_assembly_drops_summary_fact_ids_not_in_ledger():
    model = CarePlan(summary_fact_ids=[1, 2, 999])
    facts = [
        Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a"),
        Fact(id=2, category="medications", unit_id=1, char_start=0, char_end=1, text="b"),
    ]

    result = _verify_assembly(model, facts)

    assert result.summary_fact_ids == [1, 2]


def test_verify_assembly_returns_same_object_when_no_correction_needed():
    model = CarePlan(questions=["q1?"], summary_fact_ids=[1])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result is model


# ---------------------------------------------------------------------------
# Soundness: source_fact_ids
# ---------------------------------------------------------------------------

def test_verify_assembly_drops_item_with_empty_source_fact_ids():
    model = CarePlan(medications=[_make_item("medications", [])])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.medications == []


def test_verify_assembly_drops_item_with_all_hallucinated_source_fact_ids():
    model = CarePlan(medications=[_make_item("medications", [999])])
    facts = [
        Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a"),
        Fact(id=2, category="medications", unit_id=1, char_start=0, char_end=1, text="b"),
    ]

    result = _verify_assembly(model, facts)

    assert result.medications == []


def test_verify_assembly_filters_partial_hallucination_without_dropping_item():
    model = CarePlan(medications=[_make_item("medications", [1, 999])])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert len(result.medications) == 1
    assert result.medications[0].source_fact_ids == [1]


def test_verify_assembly_keeps_fully_valid_source_fact_ids_unchanged():
    item = _make_item("medications", [1])
    model = CarePlan(medications=[item])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.medications == [item]
    assert result is model


@pytest.mark.parametrize(
    "field", ["medications", "tests", "procedures", "other", "follow_up", "warning_signs"]
)
def test_verify_assembly_enforces_source_fact_ids_on_every_item_type(field):
    model = CarePlan(**{field: [_make_item(field, [999])]})
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert getattr(result, field) == []


def test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched():
    model = CarePlan(
        reason_for_visit=[ReasonForVisit(reason="checkup", description="A routine visit.")],
        diagnosis=Diagnosis(
            changed_since_last_visit="",
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    what_it_means_for_you="",
                    severity=None,
                )
            ],
        ),
    )
    # Empty ledger: if reason_for_visit/diagnosis were (wrongly) subject to
    # the source_fact_ids check, an empty ledger would drop everything.
    result = _verify_assembly(model, facts=[])

    assert result.reason_for_visit == model.reason_for_visit
    assert result.diagnosis == model.diagnosis


# ---------------------------------------------------------------------------
# Content-richness floor
# ---------------------------------------------------------------------------

def test_verify_assembly_logs_warning_for_thin_why_field(caplog):
    model = CarePlan(medications=[_make_item("medications", [1], why="for BP")])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    with caplog.at_level(logging.WARNING):
        result = _verify_assembly(model, facts)

    assert any("thin" in record.message for record in caplog.records)
    assert result.medications[0].why == "for BP"


def test_verify_assembly_thin_field_log_never_contains_clinical_text(caplog):
    """PHI/PHI-adjacent guard: _log_thin_fields must log only the field path
    and value length, never the raw patient-facing text itself."""
    thin_text = "for BP only"
    model = CarePlan(medications=[_make_item("medications", [1], why=thin_text)])
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, facts)

    assert any("thin" in record.message for record in caplog.records)
    for record in caplog.records:
        assert thin_text not in record.message
        assert repr(thin_text) not in record.message
    # The field path (with index) and value length should be present instead.
    assert any("medications[0].why" in record.message for record in caplog.records)
    assert any(str(len(thin_text)) in record.message for record in caplog.records)


def test_verify_assembly_does_not_flag_not_stated_sentinel_as_thin(caplog):
    model = CarePlan(
        medications=[_make_item("medications", [1], why="Not stated in your note.")]
    )
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, facts)

    assert not any("thin" in record.message for record in caplog.records)


def test_verify_assembly_does_not_flag_informative_why_field(caplog):
    model = CarePlan(
        medications=[_make_item("medications", [1], why="for high blood pressure")]
    )
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    with caplog.at_level(logging.WARNING):
        _verify_assembly(model, facts)

    assert not any("thin" in record.message for record in caplog.records)


def test_verify_assembly_content_richness_check_never_mutates_or_drops():
    model = CarePlan(
        medications=[_make_item("medications", [1], why="for BP")],
        tests=[_make_item("tests", [1], why="check", description="ok")],
        summary_fact_ids=[1],
        questions=["q1?"],
    )
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    # Only questions/summary_fact_ids/source_fact_ids guards may change the
    # model; the content-richness pass must never mutate or drop.
    assert result.medications[0].why == "for BP"
    assert len(result.tests) == 1
    assert result.tests[0].why == "check"
    assert result.tests[0].description == "ok"
