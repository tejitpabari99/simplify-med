"""services/care_plan_pipeline.py — pipeline-execution adapter.

Orchestrates CarePlanPipeline.iter_steps(), wires Markers/SimplifyContext
instrumentation around each step, and runs grading and scoring. Distinct
from care_plan/pipeline.py, which holds the pure step algorithm
implementations; this module is the adapter that turns the algorithm's
step events into Adapter* events for the job worker.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Generator

from flask import g

from care_plan.pipeline import CarePlanPipeline
from utils.scoring import score_text_safe
from models.metrics import Metrics
from models.grading import Grading, build_grading_with_before_after_score
from utils.markers import Markers, SimplifyContext
from models.pipeline_events import (
    StepEvent,
    PipelineRunResult,
    PipelineStepError,
    AdapterStepEvent,
    AdapterResult,
    AdapterError,
)
from errors import build_error_data_from_exc
from observability.telemetry import get_tracer

logger = logging.getLogger(__name__)


# ── Pipeline adapter ───────────────────────────────────────────────────────────
def run_care_plan_pipeline(
    text: str,
    metrics: Metrics,
    grading_enabled: bool,
    source_kind: str = "upload",
) -> Generator[AdapterStepEvent | AdapterResult | AdapterError, None, None]:
    # Kick off the CPU-only "before" grading score immediately: it depends
    # only on `text` (already available, before the pipeline's first LLM
    # call even starts), not on any pipeline step's output — so it runs
    # concurrently with the three sequential Vertex AI calls below instead
    # of serially after all of them (Finding 3).
    # score_text_safe already swallows its own exceptions and returns None
    # on failure (utils/scoring.py:307-313), so no new exception handling
    # is needed across the thread boundary.
    executor = ThreadPoolExecutor(max_workers=1) if grading_enabled else None
    before_score_future = executor.submit(score_text_safe, text, "before") if executor else None
    try:
        try:
            pipeline = CarePlanPipeline()
        except Exception as e:
            yield AdapterError(error_data=build_error_data_from_exc(e))
            return

        _STEP_MARKER_MAP = {
            2: (Markers.CarePlan.FindMedicalTerms, "find_medical_terms", None),
            3: (Markers.CarePlan.SimplifyLanguage, "simplify_language", "care_plan.simplify_language"),
            4: (Markers.CarePlan.ClarifyActions,   "clarify_actions",   "care_plan.clarify_actions"),
            5: (Markers.CarePlan.StructureNote,    "structure_note",    "care_plan.structure_note"),
        }

        def wrap_step(step: int, label: str, fn):
            marker, simplify_fn, span_name = _STEP_MARKER_MAP.get(step, (None, None, None))
            if marker is None:
                return fn()

            def _inner(scope):
                SimplifyContext.from_g(function=simplify_fn).apply(scope)
                if span_name:
                    with get_tracer().start_as_current_span(span_name) as span:
                        try:
                            span.set_attribute("session.id", g.session_id)
                        except (AttributeError, RuntimeError):
                            span.set_attribute("session.id", "")
                        result = fn()
                else:
                    result = fn()
                if step == 2:
                    substitution_count = len((result or {}).get("substitution_candidates", []))
                    preserve_count = len((result or {}).get("preserve_and_define_terms", []))
                    scope.add("term_count", substitution_count + preserve_count)
                    scope.add("substitution_count", substitution_count)
                if step == 3:
                    scope.add("input_chars", len(text))
                return result

            return marker.execute(_inner)

        for event in pipeline.iter_steps(text, wrap_step=wrap_step):
            if isinstance(event, StepEvent):
                yield AdapterStepEvent(
                    step=event.step, status=event.status, label=event.label
                )

            elif isinstance(event, PipelineStepError):
                yield AdapterError(error_data=build_error_data_from_exc(event.exc))
                return

            elif isinstance(event, PipelineRunResult):
                if grading_enabled:
                    before_score = before_score_future.result()
                    after_score  = score_text_safe(event.clarified, "after")

                    def _grade(scope):
                        SimplifyContext.from_g(function="grading").apply(scope)
                        result = build_grading_with_before_after_score(before_score, text, after_score, event.clarified)
                        scope.add("before_composite", (before_score or {}).get("composite", 0.0))
                        scope.add("after_composite",  (after_score  or {}).get("composite", 0.0))
                        scope.add("grading_method_count", len({e.name for e in result.entries if e.name != "combined"}))
                        return result

                    grading = Markers.Grading.Run.execute(_grade)
                else:
                    grading = Grading(enabled=False)

                def _pipeline_done(scope):
                    SimplifyContext.from_g(function="pipeline").apply(scope)
                    scope.add("input_chars", len(text))
                    scope.add("source_kind", source_kind)
                    scope.add("grading_enabled", grading_enabled)
                Markers.CarePlan.Pipeline.execute(_pipeline_done)

                yield AdapterResult(
                    care_plan=event.care_plan,
                    grading=grading,
                    raw_text=event.raw_text,
                    clarified_text=event.clarified,
                )

    except Exception as exc:
        def _pipeline_fail(scope):
            SimplifyContext.from_g(function="pipeline").apply(scope)
            scope.mark_failed()
        Markers.CarePlan.Pipeline.execute(_pipeline_fail)
        logger.exception("care_plan: unexpected pipeline error")
        yield AdapterError(error_data=build_error_data_from_exc(exc))
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
