"""Tests for CarePlanPipeline.review(), _resolve_path, and
_sanitize_review_result -- PRD 05 §7.2. Uses the file's established
convention: direct construction via CarePlanPipeline.__new__(CarePlanPipeline)
plus monkeypatched _generate_json, building Fact/CarePlan/ReviewResult
fixtures directly."""

import pytest

from care_plan.pipeline import (
    CarePlanPipeline,
    _resolve_path,
    _sanitize_review_result,
    _targets_removed_item,
)
from models.care_plan.care_plan import CarePlan, Medication
from models.ledger import Fact
from models.review import Correction, CoverageEntry, ReviewResult
from utils.constants import Constants


def _medication(**overrides) -> Medication:
    fields = dict(status="to_do", source_fact_ids=[1])
    fields.update(overrides)
    return Medication(**fields)


def _care_plan_with_two_medications() -> CarePlan:
    return CarePlan(
        summary="You came in for care.",
        medications=[
            _medication(dosage="10 mg", why="Prescribed for your condition."),
            _medication(dosage="20 mg", why="Not stated in your note."),
        ],
    )


def _facts(n: int) -> list[Fact]:
    return [
        Fact(id=i, category="medications", unit_id=1, char_start=0, char_end=1, text=f"fact {i}")
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------

def test_resolve_path_finds_nested_scalar():
    plan_dict = _care_plan_with_two_medications().model_dump(mode="json")

    found, value = _resolve_path(plan_dict, "medications[1].dosage")

    assert found is True
    assert value == "20 mg"


def test_resolve_path_returns_false_on_out_of_range_index():
    plan_dict = _care_plan_with_two_medications().model_dump(mode="json")

    result = _resolve_path(plan_dict, "medications[5].dosage")

    assert result == (False, None)


def test_resolve_path_returns_false_on_unknown_field_name():
    plan_dict = _care_plan_with_two_medications().model_dump(mode="json")

    result = _resolve_path(plan_dict, "nonexistent_field")

    assert result == (False, None)


# ---------------------------------------------------------------------------
# _sanitize_review_result
# ---------------------------------------------------------------------------

def test_sanitize_drops_correction_with_unresolvable_path():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[Correction(op="correct", path="medications[99].dosage", value="5 mg")],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert sanitized.corrections == []


@pytest.mark.parametrize("path", [
    "medications[0].why",
    "tests[0].why",
    "procedures[0].why",
    "other[0].why",
])
def test_sanitize_keeps_not_stated_on_each_of_the_four_why_fields(path):
    care_plan = CarePlan(
        medications=[_medication()],
        tests=[{"status": "to_do", "source_fact_ids": [1]}],
        procedures=[{"status": "to_do", "source_fact_ids": [1]}],
        other=[{"status": "to_do", "source_fact_ids": [1]}],
    )
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[Correction(op="not_stated", path=path)],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert len(sanitized.corrections) == 1
    assert sanitized.corrections[0].path == path


@pytest.mark.parametrize("path", [
    "medications[0].dosage",
    "summary",
    "warning_signs[0]",
])
def test_sanitize_drops_not_stated_outside_four_why_fields(path):
    care_plan = CarePlan(
        summary="You came in for care.",
        medications=[_medication()],
        warning_signs=[{"urgency": None, "source_fact_ids": [1]}],
    )
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[Correction(op="not_stated", path=path)],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert sanitized.corrections == []


def test_sanitize_drops_correct_with_no_value():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[Correction(op="correct", path="medications[0].dosage", value=None)],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert sanitized.corrections == []


def test_sanitize_remove_wins_over_correct_on_same_item():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[
            Correction(op="remove", path="medications[0]"),
            Correction(op="correct", path="medications[0].dosage", value="99 mg"),
        ],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert len(sanitized.corrections) == 1
    assert sanitized.corrections[0].op == "remove"
    assert sanitized.corrections[0].path == "medications[0]"


def test_sanitize_remove_wins_over_not_stated_on_same_item():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[
            Correction(op="remove", path="medications[0]"),
            Correction(op="not_stated", path="medications[0].why"),
        ],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert len(sanitized.corrections) == 1
    assert sanitized.corrections[0].op == "remove"


def test_sanitize_fills_missing_coverage_entry_as_not_present():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="pass",
        coverage=[
            CoverageEntry(fact_id=1, present=True),
            CoverageEntry(fact_id=2, present=True),
        ],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(3))

    coverage_by_id = {e.fact_id: e for e in sanitized.coverage}
    assert coverage_by_id[3].present is False


def test_sanitize_drops_coverage_entry_citing_unknown_fact_id():
    care_plan = _care_plan_with_two_medications()
    result = ReviewResult(
        verdict="pass",
        coverage=[
            CoverageEntry(fact_id=1, present=True),
            CoverageEntry(fact_id=999, present=True),
        ],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert {e.fact_id for e in sanitized.coverage} == {1}


def test_targets_removed_item_matches_leading_array_segment():
    assert _targets_removed_item("medications[0].dosage", {"medications[0]"}) is True
    assert _targets_removed_item("medications[1].dosage", {"medications[0]"}) is False
    assert _targets_removed_item("summary", {"medications[0]"}) is False


# ---------------------------------------------------------------------------
# review()
# ---------------------------------------------------------------------------

def test_review_runs_correct_from_corrections_length_not_verdict():
    """§4.5's contract: whether to run correct() is driven by
    len(result.corrections) > 0, not verdict. review() itself must never
    branch on verdict -- a canned verdict="pass" alongside a non-empty
    corrections list must still come back with that correction intact, so
    a caller computing len(result.corrections) > 0 gets True regardless of
    what verdict says."""
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    care_plan = _care_plan_with_two_medications()
    pipeline._generate_json = lambda *a, **k: {
        "verdict": "pass",
        "corrections": [
            {"op": "correct", "path": "medications[0].dosage", "value": "5 mg"},
        ],
    }

    result = pipeline.review(_facts(1), care_plan)

    assert result.verdict == "pass"
    assert len(result.corrections) == 1
    assert (len(result.corrections) > 0) is True
