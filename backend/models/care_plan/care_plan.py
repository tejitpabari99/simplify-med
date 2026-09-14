"""Strict Pydantic care-plan models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from ..base import JsonModel
from utils.constants import Constants


def _blank_str_to_none(v: object) -> object:
    """Normalize an empty string to None so a field validated by this
    helper is always exactly one of {None, non-empty text} -- never a
    third, indistinguishable "" state (PRD 13 S4.1). `object`, not
    `str | None`: Pydantic calls a mode="before" validator with
    whatever raw value was actually given, before type coercion runs --
    a non-str value here is returned unchanged and Pydantic's own type
    check raises on it immediately afterward, exactly as it would have
    without this validator in the chain."""
    return (v or None) if isinstance(v, str) else v


class ReasonForVisit(JsonModel):
    reason: str = ""
    description: str = ""
    source_fact_ids: list[int] = Field(default_factory=list)


class DiagnosisDetail(JsonModel):
    title: str = ""
    plain_name: str = ""
    description: str = ""
    what_it_means_for_you: str = ""
    severity: Literal["high", "medium", "low"] | None = None
    source_fact_ids: list[int] = Field(default_factory=list)


class Diagnosis(JsonModel):
    changed_since_last_visit: str = ""
    changed_since_last_visit_fact_ids: list[int] = Field(default_factory=list)
    details: list[DiagnosisDetail] = Field(default_factory=list)


class Medication(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str | None = None
    dosage: str = ""
    frequency: str = ""
    timing: str = ""
    duration: str = ""
    instructions: str = ""
    side_effects_to_watch: str = ""
    change: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)

    @field_validator("why", mode="before")
    @classmethod
    def _normalize_why(cls, v):
        return _blank_str_to_none(v)


class Test(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str | None = None
    description: str = ""
    preparation: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)

    @field_validator("why", mode="before")
    @classmethod
    def _normalize_why(cls, v):
        return _blank_str_to_none(v)


class Procedure(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str | None = None
    what_to_expect: str = ""
    timeframe: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)

    @field_validator("why", mode="before")
    @classmethod
    def _normalize_why(cls, v):
        return _blank_str_to_none(v)


class OtherInstruction(JsonModel):
    title: str = ""
    why: str | None = None
    steps: list[str] = Field(default_factory=list)
    description: str = ""
    frequency: str = ""
    duration: str = ""
    status: Literal["to_do", "done"]
    source_fact_ids: list[int] = Field(default_factory=list)

    @field_validator("why", mode="before")
    @classmethod
    def _normalize_why(cls, v):
        return _blank_str_to_none(v)


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
