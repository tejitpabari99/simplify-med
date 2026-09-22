"""Strict Pydantic care-plan models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..base import JsonModel
from utils.constants import Constants


class ReasonForVisit(JsonModel):
    reason: str = ""
    description: str = ""


class DiagnosisDetail(JsonModel):
    title: str = ""
    plain_name: str = ""
    description: str = ""
    what_it_means_for_you: str = ""
    severity: Literal["high", "medium", "low"] | None = None


class Diagnosis(JsonModel):
    changed_since_last_visit: str = ""
    details: list[DiagnosisDetail] = Field(default_factory=list)


class Medication(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str = ""
    dosage: str = ""
    frequency: str = ""
    timing: str = ""
    duration: str = ""
    instructions: str = ""
    side_effects_to_watch: str = ""
    change: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)


class Test(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str = ""
    description: str = ""
    preparation: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)


class Procedure(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str = ""
    what_to_expect: str = ""
    timeframe: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)


class OtherInstruction(JsonModel):
    title: str = ""
    why: str = ""
    steps: list[str] = Field(default_factory=list)
    description: str = ""
    frequency: str = ""
    duration: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)


class FollowUp(JsonModel):
    time_frame: str = ""
    description: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)


class WarningSign(JsonModel):
    symptom: str = ""
    what_it_might_mean: str = ""
    what_to_do: str = ""
    urgency: Literal["emergency", "call_doctor", "monitor", "normal_side_effect"] | None
    related_to: str = ""
    source_fact_ids: list[int] = Field(default_factory=list)


class GlossaryTerm(JsonModel):
    definition: str
    source: str
    imgUrl: str | None = None
    altText: str | None = None


class CarePlan(JsonModel):
    """The care-plan document produced by the pipeline."""

    doc_type: Literal["care_plan"] = "care_plan"
    version: Literal["1.2"] = Constants.Schema.CARE_PLAN_VERSION
    summary: str = ""
    summary_fact_ids: list[int] = Field(default_factory=list)
    reason_for_visit: list[ReasonForVisit] = Field(default_factory=list)
    diagnosis: Diagnosis = Field(default_factory=Diagnosis)
    medications: list[Medication] = Field(default_factory=list)
    tests: list[Test] = Field(default_factory=list)
    procedures: list[Procedure] = Field(default_factory=list)
    other: list[OtherInstruction] = Field(default_factory=list)
    follow_up: list[FollowUp] = Field(default_factory=list)
    warning_signs: list[WarningSign] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    low_priority: list[str] = Field(default_factory=list)
    note: str | None = None
    terms: dict[str, GlossaryTerm] = Field(default_factory=dict)

    @classmethod
    def from_pipeline_result(cls, data: dict) -> "CarePlan":
        """Validate pipeline output against the care-plan schema, stamping
        the current schema version regardless of what the pipeline output
        itself carried."""
        return cls.from_dict({**data, "version": Constants.Schema.CARE_PLAN_VERSION})
