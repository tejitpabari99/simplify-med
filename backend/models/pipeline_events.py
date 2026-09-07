from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from models.care_plan.care_plan import CarePlan
    from models.grading import Grading


# ---------------------------------------------------------------------------
# Pipeline-layer events (care_plan/pipeline.py yields these)
# ---------------------------------------------------------------------------

@dataclass
class StepEvent:
    """Emitted immediately before and after each pipeline step."""
    step: int
    status: Literal["active", "done"]
    label: str


@dataclass
class PipelineRunResult:
    """Emitted once at the end of a successful pipeline run."""
    care_plan: CarePlan
    term_data: dict
    simplified: str
    clarified: str
    raw_text: str


@dataclass
class PipelineStepError:
    """Emitted when a step raises an unrecoverable exception. Generator stops after this."""
    step: int | None
    exc: Exception


# ---------------------------------------------------------------------------
# Adapter-layer events (services/care_plan_pipeline.py yields these to routes/worker.py)
# ---------------------------------------------------------------------------

@dataclass
class AdapterStepEvent:
    """Forwarded step progress event for the worker's stage-tracking loop."""
    step: int
    status: Literal["active", "done"]
    label: str


@dataclass
class AdapterResult:
    """Final result from the adapter; consumed by the worker to complete the job."""
    care_plan: CarePlan
    grading: Grading
    raw_text: str
    clarified_text: str


@dataclass
class AdapterError:
    """Rich error dict ready to pass directly to fail_job()."""
    error_data: dict
