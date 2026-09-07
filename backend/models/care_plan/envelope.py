"""Internal care-plan envelope for pipeline output composition."""

from typing import Any

from pydantic import field_serializer, field_validator

from ..base import JsonModel
from .care_plan import CarePlan
from ..grading import Grading
from ..input import Input
from ..metrics import Metrics


class CarePlanInternal(JsonModel):
    """Internal composite of care plan, metrics, input, grading, and scores."""

    metrics: Metrics
    input: Input
    grading: Grading
    care_plan: CarePlan
    @field_validator("care_plan", mode="before")
    @classmethod
    def _validate_care_plan(cls, value: Any) -> CarePlan:
        if isinstance(value, CarePlan):
            return value
        if isinstance(value, dict):
            return CarePlan.from_dict(value)
        return value

    @field_serializer("care_plan")
    def _serialize_care_plan(self, value: CarePlan) -> dict:
        return value.to_dict()
