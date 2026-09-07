"""
Tests for backend/utils/markers/ package.
TDD: written before implementation.
"""
from __future__ import annotations

import logging
import pytest

from utils.markers import (
    Scope, register_sink, InMemorySink, SimplifySink,
    SimplifyContext,
    Markers,
)


# ---------------------------------------------------------------------------
# 1. test_marker_names
# ---------------------------------------------------------------------------
def test_marker_names():
    expected = {
        Markers.CarePlan.ReadInput: "care_plan.read_input",
        Markers.CarePlan.FindMedicalTerms: "care_plan.find_medical_terms",
        Markers.CarePlan.SimplifyLanguage: "care_plan.simplify_language",
        Markers.CarePlan.ClarifyActions: "care_plan.clarify_actions",
        Markers.CarePlan.StructureNote: "care_plan.structure_note",
        Markers.CarePlan.SaveOutput: "care_plan.save_output",
        Markers.CarePlan.Pipeline: "care_plan.pipeline",
        Markers.Grading.Run: "grading.run",
        Markers.Http.Request: "http.request",
    }
    for cls, name in expected.items():
        assert cls.name() == name, f"Expected {cls!r}.name() == {name!r}"


# ---------------------------------------------------------------------------
# 2. test_execute_returns_value
# ---------------------------------------------------------------------------
def test_execute_returns_value():
    register_sink(None)  # disable emission so we get a clean test
    result = Markers.CarePlan.SimplifyLanguage.execute(lambda s: 42)
    assert result == 42


# ---------------------------------------------------------------------------
# 3. test_execute_emits_to_sink
# ---------------------------------------------------------------------------
def test_execute_emits_to_sink():
    sink = InMemorySink()
    register_sink(sink)
    try:
        Markers.CarePlan.SimplifyLanguage.execute(lambda s: None)
        assert len(sink.events) == 1
        event = sink.events[0]
        assert event["name"] == "care_plan.simplify_language"
        assert event["success"] is True
        assert event["duration_ms"] >= 0
    finally:
        register_sink(None)


# ---------------------------------------------------------------------------
# 4. test_execute_failure_path
# ---------------------------------------------------------------------------
def test_execute_failure_path():
    sink = InMemorySink()
    register_sink(sink)
    try:
        with pytest.raises(ValueError):
            Markers.CarePlan.SimplifyLanguage.execute(
                lambda s: (_ for _ in ()).throw(ValueError("boom"))
            )
        assert len(sink.events) == 1
        event = sink.events[0]
        assert event["success"] is False
        assert event["dimensions"]["OpOutcome"] == "Failed"
    finally:
        register_sink(None)


# ---------------------------------------------------------------------------
# 5. test_simplify_sink_success_emits_two_records
# ---------------------------------------------------------------------------
def test_simplify_sink_success_emits_two_records():
    metric_logger = logging.getLogger("simplify.metrics")
    event_logger = logging.getLogger("simplify.markers")

    records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapturingHandler()
    metric_logger.addHandler(handler)
    event_logger.addHandler(handler)
    metric_logger.setLevel(logging.DEBUG)
    event_logger.setLevel(logging.DEBUG)

    try:
        SimplifySink().emit({
            "name": "care_plan.simplify_language",
            "duration_ms": 12,
            "success": True,
            "dimensions": {"session_id": "s"},
        })

        assert len(records) == 2, f"Expected 2 records, got {len(records)}"
        metric_record = next(
            (r for r in records if getattr(r, "metric", None) is True), None
        )
        assert metric_record is not None, "No record with metric=True found"
        assert getattr(metric_record, "metric_type", None) == "marker"

        timeline_record = next(
            (r for r in records if r.getMessage() == "op_complete"), None
        )
        assert timeline_record is not None, "No record with msg='op_complete' found"
    finally:
        metric_logger.removeHandler(handler)
        event_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# 6. test_simplify_sink_failure_emits_error_level
# ---------------------------------------------------------------------------
def test_simplify_sink_failure_emits_error_level():
    event_logger = logging.getLogger("simplify.markers")

    records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapturingHandler()
    event_logger.addHandler(handler)
    event_logger.setLevel(logging.DEBUG)

    try:
        SimplifySink().emit({
            "name": "care_plan.simplify_language",
            "duration_ms": 5,
            "success": False,
            "dimensions": {},
        })

        timeline_records = [r for r in records if r.getMessage() == "op_complete"]
        assert len(timeline_records) >= 1
        assert timeline_records[0].levelno == logging.ERROR
    finally:
        event_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# 7. test_simplify_context_outside_request
# ---------------------------------------------------------------------------
def test_simplify_context_outside_request():
    ctx = SimplifyContext.from_g(function="x", foo="bar")
    scope = Scope("test.op")
    ctx.apply(scope)

    assert scope._dims.get("function") == "x"
    assert scope._dims.get("foo") == "bar"
    # No None values should be in dims
    for k, v in scope._dims.items():
        assert v is not None, f"Dimension {k!r} has None value"
