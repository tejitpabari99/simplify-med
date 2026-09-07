"""Tests for the Input model and metrics model."""

import pytest
from pydantic import TypeAdapter, ValidationError

import models.input as input_models
from models.input import (
    Input,
    TextInput,
)
from models.metrics import Metrics

_input_adapter = TypeAdapter(Input)


def test_input_version_constant():
    assert input_models.INPUT_VERSION == "1.0"


# ---------------------------------------------------------------------------
# TextInput
# ---------------------------------------------------------------------------

def test_text_input_exact_shape():
    assert TextInput(text="Patient note").to_dict() == {
        "mode": "text",
        "text": "Patient note",
    }


def test_text_input_text_defaults_to_none():
    assert TextInput().to_dict() == {"mode": "text", "text": None}


# ---------------------------------------------------------------------------
# TypeAdapter dispatch
# ---------------------------------------------------------------------------

def test_type_adapter_dispatches_text():
    result = _input_adapter.validate_python({"mode": "text", "text": "x"})
    assert isinstance(result, TextInput)


def test_type_adapter_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        _input_adapter.validate_python({"mode": "unknown"})


# ---------------------------------------------------------------------------
# CarePlanInternal round-trips
# ---------------------------------------------------------------------------

def _make_internal(input_obj):
    from models.care_plan.care_plan import CarePlan
    from models.care_plan.envelope import CarePlanInternal
    from models.grading import Grading
    from models.metrics import Metrics

    metrics = Metrics.start("s1", "v1-2", input_obj.mode)
    grading = Grading(entries=[], enabled=False, graded_at=None)
    care_plan = CarePlan()
    return CarePlanInternal(
        metrics=metrics,
        input=input_obj,
        grading=grading,
        care_plan=care_plan,
    )


def test_care_plan_internal_round_trips_text_input():
    from models.care_plan.envelope import CarePlanInternal

    c = _make_internal(TextInput(text="hi"))
    restored = CarePlanInternal.model_validate(c.to_dict())
    assert isinstance(restored.input, TextInput)
    assert restored.input.text == "hi"


# ---------------------------------------------------------------------------
# Metrics (keep existing tests)
# ---------------------------------------------------------------------------

def test_metrics_start_is_mutable_and_serializes_mutations_without_step_durations():
    metrics = Metrics.start("session-1", "v1-2", "text")

    metrics.total_duration_ms = 42.5
    metrics.saved_id = "saved-123"

    data = metrics.to_dict()
    assert data["session_id"] == "session-1"
    assert data["pipeline_version"] == "v1-2"
    assert data["input_type"] == "text"
    assert data["total_duration_ms"] == 42.5
    assert data["saved_id"] == "saved-123"
    assert "created_at" in data
    assert "step_durations_ms" not in data
    assert "step_durations_ms" not in Metrics.model_fields


def test_metrics_rejects_extra_kwargs():
    with pytest.raises(ValidationError):
        Metrics(
            session_id="session-1",
            pipeline_version="v1-2",
            input_type="text",
            created_at="2026-06-20T00:00:00+00:00",
            unexpected=True,
        )
