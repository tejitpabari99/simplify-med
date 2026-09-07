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
    main_conclusion: str = ""
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
    importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW
    source: Constants.Enums.SOURCE | None = None
    change: bool = False
    change_description: str = ""


class Test(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str = ""
    description: str = ""
    preparation: str = ""
    importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW
    source: Constants.Enums.SOURCE | None = None


class Procedure(JsonModel):
    title: str = ""
    plain_name: str = ""
    why: str = ""
    what_to_expect: str = ""
    timeframe: str = ""
    importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW
    source: Constants.Enums.SOURCE | None = None


class OtherInstruction(JsonModel):
    title: str = ""
    why: str = ""
    steps: list[str] = Field(default_factory=list)
    description: str = ""
    frequency: str = ""
    duration: str = ""
    importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW
    source: Constants.Enums.SOURCE | None = None


class FollowUp(JsonModel):
    time_frame: str = ""
    description: str = ""


class WarningSign(JsonModel):
    symptom: str = ""
    what_it_might_mean: str = ""
    what_to_do: str = ""
    urgency: Literal["emergency", "call_doctor", "monitor", "normal_side_effect"] = "monitor"
    related_to: str = ""
    importance: Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW
    source: Constants.Enums.SOURCE | None = None


class GlossaryTerm(JsonModel):
    definition: str
    source: str
    imgUrl: str | None = None
    altText: str | None = None


class RawArtifacts(JsonModel):
    text: str
    simplified_text: str
    clarified_text: str


class CarePlan(JsonModel):
    """The care-plan document produced by the pipeline."""

    doc_type: Literal["care_plan"] = "care_plan"
    version: Literal["1.2"] = Constants.Schema.CARE_PLAN_VERSION
    urgency: Literal["normal", "caution", "concern", "urgent"] = "normal"
    summary: str = ""
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
    raw: RawArtifacts | None = None
    additional_info: list[str] = Field(default_factory=list)

    @classmethod
    def from_pipeline_result(cls, data: dict) -> "CarePlan":
        """Validate pipeline output against the care-plan schema, stamping
        the current schema version regardless of what the pipeline output
        itself carried."""
        return cls.from_dict({**data, "version": Constants.Schema.CARE_PLAN_VERSION})
