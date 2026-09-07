"""Tests for CarePlanPipeline.iter_steps() — the canonical step-by-step generator."""
from unittest.mock import MagicMock
from care_plan.pipeline import CarePlanPipeline
from models.pipeline_events import StepEvent, PipelineRunResult, PipelineStepError


def _make_pipeline(monkeypatch):
    """Return a CarePlanPipeline with all LLM methods mocked."""
    import care_plan.pipeline as pipeline_module
    p = CarePlanPipeline.__new__(CarePlanPipeline)
    p.simplify_language_with_term_plan = MagicMock(return_value="simplified")
    p.clarify_and_action = MagicMock(return_value="clarified")
    p.structure_appointment_note = MagicMock(return_value={
        "doc_type": "care_plan",
        "version": "1.2",
        "summary": "summary",
    })
    monkeypatch.setattr(pipeline_module, "detect_terms", lambda text: {
        "substitution_candidates": [],
        "preserve_and_define_terms": [],
        "abbreviations": [],
    })
    monkeypatch.setattr(pipeline_module, "build_glossary_from_simplified_text",
                        lambda *a: {})
    return p


def test_iter_steps_yields_step_events_in_order(monkeypatch):
    p = _make_pipeline(monkeypatch)

    events = list(p.iter_steps("input text"))

    step_events = [e for e in events if isinstance(e, StepEvent)]
    assert [(e.step, e.status) for e in step_events] == [
        (2, "active"), (2, "done"),
        (3, "active"), (3, "done"),
        (4, "active"), (4, "done"),
        (5, "active"), (5, "done"),
    ]


def test_iter_steps_yields_pipeline_run_result(monkeypatch):
    p = _make_pipeline(monkeypatch)

    events = list(p.iter_steps("input text"))

    result_events = [e for e in events if isinstance(e, PipelineRunResult)]
    assert len(result_events) == 1
    assert result_events[0].simplified == "simplified"
    assert result_events[0].clarified == "clarified"
    assert result_events[0].raw_text == "input text"


def test_iter_steps_wrap_step_called_per_step(monkeypatch):
    p = _make_pipeline(monkeypatch)

    calls = []

    def wrap_step(step, label, fn):
        calls.append(step)
        return fn()

    list(p.iter_steps("text", wrap_step=wrap_step))

    # wrap_step is called for steps 2, 3, 4, 5
    assert calls == [2, 3, 4, 5]


def test_iter_steps_step3_failure_yields_step_error(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.simplify_language_with_term_plan = MagicMock(side_effect=RuntimeError("simplify failed"))

    events = list(p.iter_steps("text"))

    error_events = [e for e in events if isinstance(e, PipelineStepError)]
    assert len(error_events) == 1
    assert error_events[0].step == 3
    assert "simplify failed" in str(error_events[0].exc)

    # No PipelineRunResult after a fatal error
    assert not [e for e in events if isinstance(e, PipelineRunResult)]


def test_iter_steps_step4_failure_falls_back_to_simplified(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.clarify_and_action = MagicMock(side_effect=RuntimeError("clarify failed"))

    events = list(p.iter_steps("text"))

    # Step 4 is non-fatal: falls back to simplified; no PipelineStepError
    assert not [e for e in events if isinstance(e, PipelineStepError)]

    result_events = [e for e in events if isinstance(e, PipelineRunResult)]
    assert len(result_events) == 1
    # clarified falls back to simplified when step 4 fails
    assert result_events[0].clarified == "simplified"


def test_iter_steps_step5_failure_yields_step_error(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.structure_appointment_note = MagicMock(side_effect=RuntimeError("structure failed"))

    events = list(p.iter_steps("text"))

    error_events = [e for e in events if isinstance(e, PipelineStepError)]
    assert len(error_events) == 1
    assert error_events[0].step == 5

    assert not [e for e in events if isinstance(e, PipelineRunResult)]


def test_run_delegates_to_iter_steps(monkeypatch):
    from models.care_plan.care_plan import CarePlan
    p = _make_pipeline(monkeypatch)

    result = p.run("text")

    assert isinstance(result, CarePlan)
