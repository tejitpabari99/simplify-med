"""Tests for the strict Pydantic grading models."""

import pytest
from pydantic import ValidationError

import models.grading as grading_models
from models.grading import Grading, GradingEntry, build_grading_with_before_after_score
from utils.scoring import score_text
from utils.constants import Constants


FIXTURE_TEXT = (
    "The patient was diagnosed with hypertension. Take your blood pressure medicine every day. "
    "Call your doctor if you feel dizzy. Drink eight glasses of water daily. Avoid salty foods. "
    "Exercise for thirty minutes each day. Monitor your blood pressure at home. "
    "Come back for a follow-up in two weeks. Ask your doctor any questions you have. "
) * 5

FIXTURE_CLARIFIED = (
    "Your blood pressure is too high. Take your pill every morning with water. "
    "If you feel dizzy, call your doctor right away. Eat less salt. Walk every day. "
    "Check your blood pressure at home. See your doctor again in two weeks. "
) * 5


def test_grading_version_constant_is_defined():
    assert grading_models.GRADING_VERSION == "1.0"


def test_grading_default_serializes_expected_json():
    assert Grading().to_dict() == {"entries": [], "enabled": True, "graded_at": None}


def test_grading_round_trips_populated_instance_with_nested_entries():
    grading = Grading(
        entries=[
            GradingEntry(
                name="smog",
                target="before",
                grade=82.5,
                description="Readable",
                grade_breakdown={"grade": 7.5, "flags": {"sample": True}},
                reasoning="SMOG grade",
            )
        ],
        enabled=False,
        graded_at="2026-06-20T00:00:00+00:00",
    )

    assert Grading.from_dict(grading.to_dict()) == grading


def test_grading_entry_round_trips_with_description_set():
    entry = GradingEntry(
        name="combined",
        target="after",
        grade=91.0,
        description="Plain-language score",
    )

    assert GradingEntry.from_dict(entry.to_dict()) == entry
    assert entry.to_dict()["description"] == "Plain-language score"


def test_grading_entry_round_trips_with_description_unset():
    entry = GradingEntry(name="combined", target="after", grade=91.0)

    assert GradingEntry.from_dict(entry.to_dict()) == entry
    assert entry.description is None
    assert entry.to_dict()["description"] is None


def test_grading_entry_rejects_unknown_top_level_kwargs():
    with pytest.raises(ValidationError):
        GradingEntry(name="smog", target="before", grade=75.0, unexpected=True)


def test_grade_breakdown_accepts_arbitrary_nested_keys():
    breakdown = {
        "custom": {"nested": [{"arbitrary_key": "accepted"}]},
        "thresholds": {"green": 90, "yellow": 70},
    }

    entry = GradingEntry(
        name="custom",
        target="after",
        grade=88.0,
        grade_breakdown=breakdown,
    )

    assert entry.grade_breakdown == breakdown
    assert GradingEntry.from_dict(entry.to_dict()).grade_breakdown == breakdown


def test_grading_entry_rejects_unknown_target():
    with pytest.raises(ValidationError):
        GradingEntry(name="smog", target="during", grade=75.0)


def test_build_grading_returns_same_entries_and_no_descriptions():
    before_score = score_text(FIXTURE_TEXT)
    after_score = score_text(FIXTURE_CLARIFIED)

    grading = build_grading_with_before_after_score(before_score, FIXTURE_TEXT, after_score, FIXTURE_CLARIFIED)

    assert [(entry.name, entry.target) for entry in grading.entries] == [
        (Constants.Grading.GRADING_METHODS.SMOG.value.value, "before"),
        (Constants.Grading.GRADING_METHODS.FLESCH_KINCAID.value.value, "before"),
        (Constants.Grading.GRADING_METHODS.DALE_CHALL.value.value, "before"),
        (Constants.Grading.GRADING_METHODS.PEMAT.value.value, "before"),
        (Constants.Grading.GRADING_METHODS.SAM.value.value, "before"),
        (Constants.Grading.GRADING_METHODS.CDC_CCI.value.value, "before"),
        ("combined", "before"),
        (Constants.Grading.GRADING_METHODS.SMOG.value.value, "after"),
        (Constants.Grading.GRADING_METHODS.FLESCH_KINCAID.value.value, "after"),
        (Constants.Grading.GRADING_METHODS.DALE_CHALL.value.value, "after"),
        (Constants.Grading.GRADING_METHODS.PEMAT.value.value, "after"),
        (Constants.Grading.GRADING_METHODS.SAM.value.value, "after"),
        (Constants.Grading.GRADING_METHODS.CDC_CCI.value.value, "after"),
        ("combined", "after"),
    ]
    assert all(entry.description is None for entry in grading.entries)