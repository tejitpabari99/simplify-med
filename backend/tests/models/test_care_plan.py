"""Tests for the strict CarePlan model."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.care_plan import CarePlan
from models.care_plan.care_plan import Diagnosis
from utils.constants import Constants

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "care_plan.json"


@pytest.fixture
def full_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_care_plan_round_trips_full_fixture(full_fixture):
    model = CarePlan.model_validate(full_fixture)

    assert model.model_dump(mode="json") == full_fixture


def test_care_plan_rejects_extra_top_level_key(full_fixture):
    with pytest.raises(ValidationError):
        CarePlan.model_validate({**full_fixture, "extra": "drift"})


def test_care_plan_rejects_extra_nested_key(full_fixture):
    fixture = full_fixture.copy()
    fixture["medications"] = [{**fixture["medications"][0], "extra": "drift"}]

    with pytest.raises(ValidationError):
        CarePlan.model_validate(fixture)


def test_care_plan_minimal_payload_uses_pipeline_defaults():
    model = CarePlan.model_validate(
        {"version": Constants.Schema.CARE_PLAN_VERSION, "doc_type": "care_plan"}
    )

    assert model.version == Constants.Schema.CARE_PLAN_VERSION
    assert model.doc_type == "care_plan"
    assert model.urgency == "normal"
    assert model.summary == ""
    assert model.reason_for_visit == []
    assert model.diagnosis == Diagnosis()
    assert model.medications == []
    assert model.tests == []
    assert model.procedures == []
    assert model.other == []
    assert model.follow_up == []
    assert model.warning_signs == []
    assert model.questions == []
    assert model.low_priority == []
    assert model.terms == {}
    assert model.raw is None


def test_care_plan_rejects_appointment_note_doc_type():
    with pytest.raises(ValidationError):
        CarePlan.model_validate(
            {"version": Constants.Schema.CARE_PLAN_VERSION, "doc_type": "appointment_note"}
        )


def test_care_plan_from_dict_validates_directly():
    model = CarePlan.from_dict({"version": Constants.Schema.CARE_PLAN_VERSION, "doc_type": "care_plan"})

    assert isinstance(model, CarePlan)


def test_care_plan_from_pipeline_result_stamps_version_and_validates():
    model = CarePlan.from_pipeline_result({"doc_type": "care_plan"})

    assert isinstance(model, CarePlan)
    assert model.version == Constants.Schema.CARE_PLAN_VERSION


def test_care_plan_from_pipeline_result_validates_drift():
    with pytest.raises(ValidationError):
        CarePlan.from_pipeline_result({"doc_type": "care_plan", "extra": "drift"})


def test_structured_llm_schema_properties_match_care_plan_structured_fields():
    from care_plan.pipeline import _llm_schema

    care_plan_fields = set(CarePlan.model_fields)
    structured_fields = care_plan_fields - {"terms", "raw"}
    schema_properties = set(_llm_schema(CarePlan, {"terms", "raw"})["properties"])

    assert schema_properties == structured_fields
