"""Tests for CarePlanPipeline.iter_steps() — the canonical step-by-step generator."""

from unittest.mock import MagicMock

from care_plan.pipeline import CarePlanPipeline
from models.care_plan.care_plan import CarePlan
from models.ledger import Fact
from models.pipeline_events import PipelineRunResult, PipelineStepError, StepEvent
from models.review import ReviewResult
from utils.constants import Constants


FACT_FIXTURE = Fact(
    id=1,
    category="medications",
    unit_id=1,
    char_start=0,
    char_end=1,
    text="x",
)
CARE_PLAN_FIXTURE = CarePlan(
    doc_type="care_plan",
    version=Constants.Schema.CARE_PLAN_VERSION,
    summary="summary",
)


def _make_pipeline(monkeypatch):
    """Return a CarePlanPipeline with all pipeline methods mocked."""
    import care_plan.pipeline as pipeline_module

    p = CarePlanPipeline.__new__(CarePlanPipeline)
    p.ground = MagicMock(return_value=[FACT_FIXTURE])
    p.assemble_and_render = MagicMock(return_value=CARE_PLAN_FIXTURE)
    p.review = MagicMock(return_value=ReviewResult(verdict="pass", corrections=[]))
    p.correct = MagicMock(return_value=CARE_PLAN_FIXTURE)
    monkeypatch.setattr(pipeline_module, "detect_terms", lambda text: {
        "substitution_candidates": [],
        "preserve_and_define_terms": [],
        "abbreviations": [],
    })
    monkeypatch.setattr(pipeline_module, "curate_glossary_terms", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline_module, "build_glossary_from_care_plan", lambda cp, terms: {})
    monkeypatch.setattr(pipeline_module, "LLMClient", lambda: MagicMock())
    return p


def _result_event(events):
    result_events = [event for event in events if isinstance(event, PipelineRunResult)]
    assert len(result_events) == 1
    return result_events[0]


def test_iter_steps_yields_step_events_in_order(monkeypatch):
    p = _make_pipeline(monkeypatch)

    events = list(p.iter_steps("input text", []))

    step_events = [event for event in events if isinstance(event, StepEvent)]
    assert [(event.step, event.status) for event in step_events] == [
        (2, "active"), (2, "done"),
        (3, "active"), (3, "done"),
        (4, "active"), (4, "done"),
        (5, "active"), (5, "done"),
        (6, "active"), (6, "done"),
    ]


def test_iter_steps_yields_pipeline_run_result(monkeypatch):
    p = _make_pipeline(monkeypatch)

    result = _result_event(list(p.iter_steps("input text", [])))

    # Glossary projection returns a CarePlan copy, so equality is the public
    # contract; the identity check guards against accidentally bypassing it.
    assert result.care_plan == CARE_PLAN_FIXTURE
    assert result.care_plan is not CARE_PLAN_FIXTURE
    assert result.term_data == {
        "substitution_candidates": [],
        "preserve_and_define_terms": [],
        "abbreviations": [],
    }
    assert result.raw_text == "input text"
    assert not hasattr(result, "simplified")
    assert not hasattr(result, "clarified")


def test_iter_steps_wrap_step_called_per_step(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.review = MagicMock(return_value=ReviewResult(
        verdict="needs_correction",
        corrections=[{"op": "correct", "path": "summary", "value": "updated"}],
    ))
    calls = []

    def wrap_step(step, label, fn):
        calls.append(step)
        return fn()

    list(p.iter_steps("text", [], wrap_step=wrap_step))

    assert calls == [2, 3, 4, 5, 6]


def test_iter_steps_ground_failure_yields_step_error(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.ground = MagicMock(side_effect=RuntimeError("ground failed"))

    events = list(p.iter_steps("text", []))

    error_events = [event for event in events if isinstance(event, PipelineStepError)]
    assert len(error_events) == 1
    assert error_events[0].step == 3
    assert "ground failed" in str(error_events[0].exc)
    assert not [event for event in events if isinstance(event, PipelineRunResult)]


def test_iter_steps_assemble_and_render_failure_yields_step_error(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.assemble_and_render = MagicMock(side_effect=RuntimeError("assemble failed"))

    events = list(p.iter_steps("text", []))

    error_events = [event for event in events if isinstance(event, PipelineStepError)]
    assert len(error_events) == 1
    assert error_events[0].step == 4
    assert "assemble failed" in str(error_events[0].exc)
    assert not [event for event in events if isinstance(event, PipelineRunResult)]


def test_iter_steps_review_failure_is_non_fatal(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.review = MagicMock(side_effect=RuntimeError("review failed"))

    events = list(p.iter_steps("text", []))

    assert not [event for event in events if isinstance(event, PipelineStepError)]
    p.correct.assert_not_called()
    assert _result_event(events).care_plan == CARE_PLAN_FIXTURE


def test_iter_steps_correct_failure_falls_back_to_pre_correction_plan(monkeypatch):
    p = _make_pipeline(monkeypatch)
    p.review = MagicMock(return_value=ReviewResult(
        verdict="needs_correction",
        corrections=[{"op": "correct", "path": "summary", "value": "updated"}],
    ))
    p.correct = MagicMock(side_effect=RuntimeError("correct failed"))

    events = list(p.iter_steps("text", []))

    assert not [event for event in events if isinstance(event, PipelineStepError)]
    p.correct.assert_called_once()
    assert _result_event(events).care_plan == CARE_PLAN_FIXTURE


def test_iter_steps_skips_correct_call_when_no_corrections(monkeypatch):
    p = _make_pipeline(monkeypatch)

    events = list(p.iter_steps("text", []))

    p.correct.assert_not_called()
    step_events = [event for event in events if isinstance(event, StepEvent)]
    assert [(event.step, event.status) for event in step_events[-2:]] == [
        (6, "active"),
        (6, "done"),
    ]


def test_run_delegates_to_iter_steps(monkeypatch):
    p = _make_pipeline(monkeypatch)

    result = p.run("text", units=[])

    assert isinstance(result, CarePlan)
    assert result == CARE_PLAN_FIXTURE


def test_glossary_executor_is_shut_down_even_on_fatal_ground_failure(monkeypatch):
    import care_plan.pipeline as pipeline_module

    p = _make_pipeline(monkeypatch)
    p.ground = MagicMock(side_effect=RuntimeError("ground failed"))
    executor = MagicMock()
    executor.submit.return_value = MagicMock()
    monkeypatch.setattr(pipeline_module, "ThreadPoolExecutor", lambda **kwargs: executor)

    list(p.iter_steps("text", []))

    executor.shutdown.assert_called_once_with(wait=False)
