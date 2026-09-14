"""Assembly-level tests for CarePlanPipeline.assemble_and_render() and its
deterministic post-checks (_verify_assembly, _format_facts_for_prompt) --
PRD 04 §7.4. Uses the file's established convention: direct construction via
CarePlanPipeline.__new__(CarePlanPipeline) plus monkeypatched _generate_json,
building Fact/CarePlan fixtures directly."""

import logging

import pytest

import care_plan.pipeline as pipeline_module
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
    "reason_for_visit": ReasonForVisit,
    "medications": Medication,
    "tests": Test,
    "procedures": Procedure,
    "other": OtherInstruction,
    "follow_up": FollowUp,
    "warning_signs": WarningSign,
}


def _make_item(field: str, source_fact_ids: list[int], **overrides):
    """Build a minimal instance of the item model for `field`, with the
    given source_fact_ids. Every item type but warning_signs and
    reason_for_visit requires `status`; warning_signs requires `urgency`
    (nullable, no default); reason_for_visit has neither `status` nor
    `urgency` -- JsonModel's extra="forbid" would reject either key."""
    cls = _ITEM_MODEL_BY_FIELD[field]
    kwargs = {"source_fact_ids": list(source_fact_ids)}
    if field == "warning_signs":
        kwargs["urgency"] = None
    elif field == "reason_for_visit":
        pass
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

def test_assemble_and_render_accepts_null_why():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "medications": [
            {"why": None, "status": "to_do", "source_fact_ids": [1]}
        ],
    }

    result = pipeline.assemble_and_render(facts, [], [], [])

    assert result.medications[0].why is None
    assert result.medications[0].source_fact_ids == [1]


def test_assemble_and_render_normalizes_llm_empty_string_why_to_none():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]
    pipeline._generate_json = lambda *a, **k: {
        **_minimal_care_plan_response(),
        "medications": [{"why": "", "status": "to_do", "source_fact_ids": [1]}],
    }
    result = pipeline.assemble_and_render(facts, [], [], [])
    assert result.medications[0].why is None


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
                    "source_fact_ids": [1],
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
    "field",
    ["reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs"],
)
def test_verify_assembly_enforces_source_fact_ids_on_every_item_type(field):
    model = CarePlan(**{field: [_make_item(field, [999])]})
    facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert getattr(result, field) == []


def test_verify_assembly_leaves_diagnosis_untouched_when_fully_cited():
    model = CarePlan(
        diagnosis=Diagnosis(
            changed_since_last_visit="Blood pressure has worsened.",
            changed_since_last_visit_fact_ids=[1],
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    what_it_means_for_you="",
                    severity=None,
                    source_fact_ids=[1],
                )
            ],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.diagnosis == model.diagnosis
    assert result is model


# ---------------------------------------------------------------------------
# Soundness: diagnosis.details / diagnosis.changed_since_last_visit
# ---------------------------------------------------------------------------

def test_verify_assembly_drops_diagnosis_detail_with_empty_source_fact_ids():
    model = CarePlan(
        diagnosis=Diagnosis(
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    source_fact_ids=[],
                )
            ],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.diagnosis.details == []


def test_verify_assembly_drops_diagnosis_detail_with_all_hallucinated_source_fact_ids():
    model = CarePlan(
        diagnosis=Diagnosis(
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    source_fact_ids=[999],
                )
            ],
        ),
    )
    facts = [
        Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a"),
        Fact(id=2, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="b"),
    ]

    result = _verify_assembly(model, facts)

    assert result.diagnosis.details == []


def test_verify_assembly_filters_partial_hallucination_on_diagnosis_detail_without_dropping_it():
    model = CarePlan(
        diagnosis=Diagnosis(
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    source_fact_ids=[1, 999],
                )
            ],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert len(result.diagnosis.details) == 1
    assert result.diagnosis.details[0].source_fact_ids == [1]


def test_verify_assembly_drops_all_diagnosis_details_leaves_empty_list():
    model = CarePlan(
        diagnosis=Diagnosis(
            details=[
                DiagnosisDetail(
                    title="Hypertension",
                    plain_name="high blood pressure",
                    description="Your blood pressure remains elevated.",
                    source_fact_ids=[],
                ),
                DiagnosisDetail(
                    title="Diabetes",
                    plain_name="high blood sugar",
                    description="Your blood sugar remains high.",
                    source_fact_ids=[999],
                ),
            ],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.diagnosis.details == []


def test_verify_assembly_clears_uncited_changed_since_last_visit():
    model = CarePlan(
        diagnosis=Diagnosis(
            changed_since_last_visit="Blood pressure has worsened.",
            changed_since_last_visit_fact_ids=[999],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.diagnosis.changed_since_last_visit == ""
    assert result.diagnosis.changed_since_last_visit_fact_ids == []


def test_verify_assembly_leaves_empty_changed_since_last_visit_unchecked(caplog):
    model = CarePlan(
        diagnosis=Diagnosis(
            changed_since_last_visit="",
            changed_since_last_visit_fact_ids=[999],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    with caplog.at_level(logging.WARNING):
        result = _verify_assembly(model, facts)

    assert result.diagnosis == model.diagnosis
    assert not any("changed_since_last_visit" in r.message for r in caplog.records)


def test_verify_assembly_filters_partial_hallucination_on_changed_since_last_visit():
    model = CarePlan(
        diagnosis=Diagnosis(
            changed_since_last_visit="Blood pressure has worsened.",
            changed_since_last_visit_fact_ids=[1, 999],
        ),
    )
    facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="a")]

    result = _verify_assembly(model, facts)

    assert result.diagnosis.changed_since_last_visit == "Blood pressure has worsened."
    assert result.diagnosis.changed_since_last_visit_fact_ids == [1]


# ---------------------------------------------------------------------------
# §7.5 regression: every CarePlan field must have a recorded soundness
# classification
# ---------------------------------------------------------------------------

def test_every_care_plan_field_has_a_soundness_classification():
    """Regression guard for PRD 18's headline gap: a field added to CarePlan
    with no soundness decision recorded must fail this test, not ship
    silently the way reason_for_visit/diagnosis did."""
    all_fields = set(CarePlan.model_fields)
    classified = (
        set(pipeline_module._SOUNDNESS_CHECKED_FIELDS)
        | set(pipeline_module._SOUNDNESS_EXEMPT_FIELDS)
        | set(pipeline_module._SOUNDNESS_NOT_APPLICABLE_FIELDS)
    )
    unclassified = all_fields - classified
    assert not unclassified, (
        f"{unclassified} added to CarePlan with no soundness decision recorded "
        f"-- see PRD 18 S4.1's audit table and S7.5's classification sets."
    )


def test_soundness_checked_fields_all_carry_a_source_fact_ids_shape():
    """Would have caught PRD 01's original six-model scoping gap had it
    existed then: every soundness-checked item list's model must actually
    carry `source_fact_ids` (diagnosis/summary are structurally different
    and checked separately below)."""
    for field in pipeline_module._SOUNDNESS_CHECKED_FIELDS:
        if field in ("diagnosis", "summary"):
            continue
        assert "source_fact_ids" in _ITEM_MODEL_BY_FIELD[field].model_fields

    assert "source_fact_ids" in DiagnosisDetail.model_fields
    assert "changed_since_last_visit_fact_ids" in Diagnosis.model_fields


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


def test_verify_assembly_does_not_flag_null_why_as_thin(caplog):
    model = CarePlan(
        medications=[_make_item("medications", [1], why=None)]
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
