"""Focused tests for the pipeline's Pydantic schema boundary."""

import json

import pytest

from care_plan import pipeline as pipeline_module
from care_plan.pipeline import CarePlanPipeline
from errors import SimplifyError, ErrorCode
from models.care_plan.care_plan import CarePlan
from models.ledger import Fact, Unit
from models.review import Correction
from utils.constants import Constants
from care_plan.pipeline import _llm_schema


def _minimal_care_plan_dict() -> dict:
    return {
        "doc_type": "care_plan",
        "version": Constants.Schema.CARE_PLAN_VERSION,
        "summary": "You came in for care.",
    }


def _minimal_facts() -> list[Fact]:
    return [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]


def test_llm_schema_excludes_terms_and_raw():
    schema = _llm_schema(CarePlan, {"terms", "raw"})
    props = schema["properties"]

    assert "terms" not in props
    assert "raw" not in props
    expected = set(CarePlan.model_fields) - {"terms", "raw"}
    assert set(props) == expected


def test_llm_schema_excludes_note():
    schema = _llm_schema(CarePlan, {"terms", "raw", "note"})
    assert "note" not in schema["properties"]


def test_grounding_schema_is_a_json_array_of_grounded_fact_raw():
    schema = json.loads(pipeline_module._GROUNDING_SCHEMA)

    assert schema["type"] == "array"
    props = schema["items"]["properties"]
    assert "category" in props
    assert "unit_id" in props
    assert "quote" in props
    assert "text" in props
    assert "id" not in props
    assert "char_start" not in props
    assert "char_end" not in props


def test_ground_assigns_sequential_ids_from_array_position():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [
        Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily", extraction_method="native"),
        Unit(id=2, file="note.pdf", page=1, line=2, text="Follow up in two weeks for bloodwork", extraction_method="native"),
    ]
    pipeline._generate_json = lambda *args, **kwargs: [
        {
            "category": "medications",
            "unit_id": 1,
            "quote": "warfarin 5mg",
            "text": "Take warfarin 5mg daily.",
        },
        {
            "category": "follow_up",
            "unit_id": 2,
            "quote": "bloodwork",
            "text": "Get bloodwork done.",
        },
    ]

    facts = pipeline.ground(units, [])

    assert [fact.id for fact in facts] == [1, 2]


def test_ground_rejects_non_list_llm_output():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: {"not": "a list"}

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.ground([], [])
    assert exc_info.value.error_code == ErrorCode.LLM_INVALID_JSON


def test_ground_rejects_extra_key_on_fact():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily", extraction_method="native")]
    pipeline._generate_json = lambda *args, **kwargs: [
        {
            "category": "medications",
            "unit_id": 1,
            "quote": "warfarin 5mg",
            "text": "Take warfarin 5mg daily.",
            "importance": "high",
        },
    ]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.ground(units, [])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_ground_uses_long_form_token_budget_and_json_temperature():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    units = [Unit(id=1, file="note.pdf", page=1, line=1, text="Patient started on warfarin 5mg daily", extraction_method="native")]
    captured_kwargs = {}

    def _fake_generate_json(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return [
            {
                "category": "medications",
                "unit_id": 1,
                "quote": "warfarin 5mg",
                "text": "Take warfarin 5mg daily.",
            },
        ]

    pipeline._generate_json = _fake_generate_json
    pipeline.ground(units, [])

    assert captured_kwargs["max_tokens"] == Constants.Llm.MAX_TOKENS_LONG_FORM
    assert captured_kwargs["temperature"] == Constants.Llm.TEMPERATURE_JSON


def test_llm_schema_model_validate_without_terms_and_raw():
    model = CarePlan.model_validate(
        {"doc_type": "care_plan", "version": "1.2", "summary": "You came in for care."}
    )
    dumped = model.model_dump(mode="json", exclude={"terms", "raw"})

    assert "terms" not in dumped
    assert "raw" not in dumped
    assert dumped["summary"] == "You came in for care."


# ---------------------------------------------------------------------------
# Assemble schema / assemble_and_render boundary tests (PRD 04 §7.3)
# ---------------------------------------------------------------------------

def test_assemble_schema_is_generated_from_care_plan_minus_terms_and_note():
    # NOTE: pydantic v2's model_json_schema() emits nested models as a
    # `$ref` into a top-level `$defs` map rather than inlining them under
    # `items` -- so `medications`'s item schema is resolved via
    # `$defs[Medication]`, not `props["medications"]["items"]["properties"]`
    # as the TASKS.md example assumed. Deviation noted; same assertion intent.
    schema = json.loads(pipeline_module._ASSEMBLE_SCHEMA)
    props = schema["properties"]

    assert "terms" not in props
    assert "note" not in props
    assert "summary_fact_ids" in props
    assert "medications" in props
    medication_ref = props["medications"]["items"]["$ref"]
    medication_def_name = medication_ref.rsplit("/", 1)[-1]
    assert "source_fact_ids" in schema["$defs"][medication_def_name]["properties"]


def test_assemble_and_render_returns_care_plan_instance():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: _minimal_care_plan_dict()

    result = pipeline.assemble_and_render(_minimal_facts(), [], [], [])

    assert isinstance(result, CarePlan)


def test_assemble_and_render_uses_long_form_token_budget_and_json_temperature():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    captured_kwargs = {}

    def _fake_generate_json(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _minimal_care_plan_dict()

    pipeline._generate_json = _fake_generate_json
    pipeline.assemble_and_render(_minimal_facts(), [], [], [])

    assert captured_kwargs["max_tokens"] == Constants.Llm.MAX_TOKENS_LONG_FORM
    assert captured_kwargs["temperature"] == Constants.Llm.TEMPERATURE_JSON


def test_assemble_and_render_rejects_non_dict_llm_output():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: ["not", "a", "dict"]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.assemble_and_render(_minimal_facts(), [], [], [])
    assert exc_info.value.error_code == ErrorCode.LLM_INVALID_JSON


def test_assemble_and_render_rejects_extra_llm_key():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: {
        **_minimal_care_plan_dict(),
        "importance": "high",
    }

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.assemble_and_render(_minimal_facts(), [], [], [])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_assemble_and_render_raises_on_empty_fact_list():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    called = False

    def _fake_generate_json(*args, **kwargs):
        nonlocal called
        called = True
        return _minimal_care_plan_dict()

    pipeline._generate_json = _fake_generate_json

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.assemble_and_render(facts=[], substitution_candidates=[], preserve_and_define_terms=[], abbreviations=[])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
    assert called is False


# ---------------------------------------------------------------------------
# review()/correct() schema-boundary tests (PRD 05 §7.1, §7.2)
# ---------------------------------------------------------------------------

def _minimal_care_plan() -> CarePlan:
    return CarePlan.model_validate(_minimal_care_plan_dict())


def test_review_schema_is_generated_from_review_result():
    schema = json.loads(pipeline_module._REVIEW_SCHEMA)
    props = schema["properties"]

    assert "verdict" in props
    assert "corrections" in props
    assert "coverage" in props


def test_review_uses_long_form_token_budget_and_json_temperature():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    captured_kwargs = {}

    def _fake_generate_json(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return {"verdict": "pass"}

    pipeline._generate_json = _fake_generate_json
    pipeline.review(_minimal_facts(), _minimal_care_plan())

    assert captured_kwargs["max_tokens"] == Constants.Llm.MAX_TOKENS_LONG_FORM
    assert captured_kwargs["temperature"] == Constants.Llm.TEMPERATURE_JSON


def test_review_rejects_non_dict_llm_output():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: ["not", "a", "dict"]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.review(_minimal_facts(), _minimal_care_plan())
    assert exc_info.value.error_code == ErrorCode.LLM_INVALID_JSON


def test_review_rejects_invalid_verdict_value():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: {"verdict": "maybe"}

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.review(_minimal_facts(), _minimal_care_plan())
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_correct_uses_long_form_token_budget_and_json_temperature_when_corrections_present():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    captured_kwargs = {}

    def _fake_generate_json(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return {**_minimal_care_plan_dict(), "summary": ""}

    pipeline._generate_json = _fake_generate_json
    corrections = [Correction(op="remove", path="summary")]

    pipeline.correct(_minimal_care_plan(), corrections, [], [], [])

    assert captured_kwargs["max_tokens"] == Constants.Llm.MAX_TOKENS_LONG_FORM
    assert captured_kwargs["temperature"] == Constants.Llm.TEMPERATURE_JSON


def test_correct_short_circuits_on_empty_corrections():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    called = False

    def _fake_generate_json(*args, **kwargs):
        nonlocal called
        called = True
        return _minimal_care_plan_dict()

    pipeline._generate_json = _fake_generate_json
    care_plan = _minimal_care_plan()

    result = pipeline.correct(care_plan, [], [], [], [])

    assert called is False
    assert result is care_plan


def test_correct_rejects_non_dict_llm_output():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: ["not", "a", "dict"]
    corrections = [Correction(op="remove", path="summary")]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.correct(_minimal_care_plan(), corrections, [], [], [])
    assert exc_info.value.error_code == ErrorCode.LLM_INVALID_JSON


def test_correct_rejects_extra_llm_key():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    pipeline._generate_json = lambda *args, **kwargs: {
        **_minimal_care_plan_dict(),
        "importance": "high",
    }
    corrections = [Correction(op="remove", path="summary")]

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.correct(_minimal_care_plan(), corrections, [], [], [])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
