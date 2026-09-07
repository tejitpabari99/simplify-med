"""Tests for run_care_plan_pipeline — the thin adapter over CarePlanPipeline.iter_steps()."""
from unittest.mock import patch, MagicMock

from models.metrics import Metrics
from services.care_plan_pipeline import run_care_plan_pipeline
from models.pipeline_events import (
    StepEvent,
    PipelineRunResult,
    PipelineStepError,
    AdapterStepEvent,
    AdapterResult,
    AdapterError,
)
from models.grading import Grading


def _make_metrics():
    return Metrics.start(session_id="session-1", pipeline_version="v1-2", input_type="text")


def _make_run_result(text="plain note"):
    """Return a PipelineRunResult with a minimal stub care_plan."""
    return PipelineRunResult(
        care_plan=MagicMock(),
        term_data={"substitution_candidates": [], "preserve_and_define_terms": [], "abbreviations": []},
        simplified="simplified",
        clarified="clarified",
        raw_text=text,
    )


class FakePipeline:
    """Fake pipeline that yields typed events from iter_steps without calling wrap_step."""

    def iter_steps(self, text, wrap_step=None):
        for step in (2, 3, 4, 5):
            yield StepEvent(step=step, status="active", label=f"Step {step}")
            yield StepEvent(step=step, status="done", label=f"Step {step}")
        yield _make_run_result(text)


class FailingPipeline:
    """Fake pipeline that yields a step error."""

    def iter_steps(self, text, wrap_step=None):
        yield PipelineStepError(step=3, exc=RuntimeError("fail"))


def _mock_markers():
    """Return a mock_scope and side_effect setter for Markers.CarePlan.Pipeline.execute."""
    mock_scope = MagicMock()
    return mock_scope


def test_run_care_plan_pipeline_yields_typed_step_events():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FakePipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)

        events = list(run_care_plan_pipeline("plain note", metrics, grading_enabled=False))

    step_events = [e for e in events if isinstance(e, AdapterStepEvent)]
    assert [(e.step, e.status) for e in step_events] == [
        (2, "active"), (2, "done"),
        (3, "active"), (3, "done"),
        (4, "active"), (4, "done"),
        (5, "active"), (5, "done"),
    ]


def test_run_care_plan_pipeline_yields_adapter_result():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FakePipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)

        events = list(run_care_plan_pipeline("plain note", metrics, grading_enabled=False))

    result_events = [e for e in events if isinstance(e, AdapterResult)]
    assert len(result_events) == 1
    result = result_events[0]
    assert result.raw_text == "plain note"
    assert result.care_plan is not None
    assert isinstance(result.grading, Grading)
    assert result.grading.enabled is False


def test_run_care_plan_pipeline_step_error_yields_adapter_error():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FailingPipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)

        events = list(run_care_plan_pipeline("text", metrics, grading_enabled=False))

    error_events = [e for e in events if isinstance(e, AdapterError)]
    assert len(error_events) == 1


# ── Task 3: concurrent before-score computation ─────────────────────────────────


class RaisingConstructorPipeline:
    """Not actually instantiated — CarePlanPipeline() itself raises."""
    pass


def test_grading_enabled_still_computes_before_and_after_scores():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FakePipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers, \
         patch("services.care_plan_pipeline.score_text_safe") as mock_score, \
         patch("services.care_plan_pipeline.build_grading_with_before_after_score") as mock_build:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)
        mock_markers.Grading.Run.execute.side_effect = lambda fn: fn(mock_scope)
        mock_score.side_effect = lambda text, label: {"composite": 50.0, "dimensions": {}}
        mock_build.return_value = MagicMock(entries=[])

        list(run_care_plan_pipeline("plain note", metrics, grading_enabled=True))

    assert mock_score.call_count == 2
    called_args = {c.args for c in mock_score.call_args_list}
    assert ("plain note", "before") in called_args
    assert ("clarified", "after") in called_args


def test_grading_disabled_never_creates_a_threadpool():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FakePipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers, \
         patch("services.care_plan_pipeline.ThreadPoolExecutor") as mock_pool:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)

        list(run_care_plan_pipeline("plain note", metrics, grading_enabled=False))

    mock_pool.assert_not_called()


def test_step_error_with_grading_enabled_does_not_hang_or_leak_thread():
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    with patch("services.care_plan_pipeline.CarePlanPipeline", return_value=FailingPipeline()), \
         patch("services.care_plan_pipeline.Markers") as mock_markers:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)

        events = list(run_care_plan_pipeline("text", metrics, grading_enabled=True))

    error_events = [e for e in events if isinstance(e, AdapterError)]
    assert len(error_events) == 1


def test_pipeline_constructor_failure_with_grading_enabled_does_not_hang_or_leak_thread():
    metrics = _make_metrics()

    with patch("services.care_plan_pipeline.CarePlanPipeline", side_effect=RuntimeError("boom")):
        events = list(run_care_plan_pipeline("text", metrics, grading_enabled=True))

    error_events = [e for e in events if isinstance(e, AdapterError)]
    assert len(error_events) == 1


def test_before_score_submitted_before_pipeline_construction():
    """Ordering proof: the before-score work is submitted to the executor before
    the pipeline is even constructed — i.e. before any of the three sequential
    LLM calls inside iter_steps() can start — not merely before before_score is
    consumed at the end."""
    order = []
    metrics = _make_metrics()
    mock_scope = _mock_markers()

    class OrderTrackingPipeline:
        def __init__(self):
            order.append("pipeline_constructed")

        def iter_steps(self, text, wrap_step=None):
            order.append("pipeline_iter_start")
            yield _make_run_result(text)

    mock_executor = MagicMock()

    def fake_submit(fn, *args, **kwargs):
        order.append("submit_before_score")
        fut = MagicMock()
        fut.result.return_value = {"composite": 1.0, "dimensions": {}}
        return fut

    mock_executor.submit.side_effect = fake_submit

    with patch("services.care_plan_pipeline.ThreadPoolExecutor", return_value=mock_executor), \
         patch("services.care_plan_pipeline.CarePlanPipeline", side_effect=OrderTrackingPipeline), \
         patch("services.care_plan_pipeline.Markers") as mock_markers, \
         patch("services.care_plan_pipeline.score_text_safe") as mock_score, \
         patch("services.care_plan_pipeline.build_grading_with_before_after_score") as mock_build:
        mock_markers.CarePlan.Pipeline.execute.side_effect = lambda fn: fn(mock_scope)
        mock_markers.Grading.Run.execute.side_effect = lambda fn: fn(mock_scope)
        mock_build.return_value = MagicMock(entries=[])

        list(run_care_plan_pipeline("plain note", metrics, grading_enabled=True))

    assert order.index("submit_before_score") < order.index("pipeline_constructed")
    assert order.index("submit_before_score") < order.index("pipeline_iter_start")
    mock_executor.shutdown.assert_called_once_with(wait=True)
    # after-score is still computed synchronously via a direct call, not via the
    # executor — only "before" is offloaded to the background thread.
    mock_score.assert_called_once_with("clarified", "after")
