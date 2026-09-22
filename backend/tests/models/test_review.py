"""Tests for the review models: Correction, CoverageEntry, ReviewResult."""

import pytest
from pydantic import ValidationError

from models.review import Correction, CoverageEntry, ReviewResult


def _correction(**overrides) -> Correction:
    fields = dict(op="correct", path="medications[0].dosage", value="10 mg")
    fields.update(overrides)
    return Correction(**fields)


def _coverage_entry(**overrides) -> CoverageEntry:
    fields = dict(fact_id=1, present=True)
    fields.update(overrides)
    return CoverageEntry(**fields)


def _review_result(**overrides) -> ReviewResult:
    fields = dict(
        verdict="needs_correction",
        corrections=[_correction()],
        coverage=[_coverage_entry()],
    )
    fields.update(overrides)
    return ReviewResult(**fields)


def test_correction_round_trips_through_dict():
    correction = _correction()

    assert Correction.from_dict(correction.to_dict()) == correction


def test_coverage_entry_round_trips_through_dict():
    entry = _coverage_entry()

    assert CoverageEntry.from_dict(entry.to_dict()) == entry


def test_review_result_round_trips_through_dict():
    result = _review_result()

    assert ReviewResult.from_dict(result.to_dict()) == result


def test_correction_rejects_unknown_key():
    with pytest.raises(ValidationError):
        Correction(op="correct", path="medications[0].dosage", value="10 mg", extra="x")


def test_coverage_entry_rejects_unknown_key():
    with pytest.raises(ValidationError):
        CoverageEntry(fact_id=1, present=True, extra="x")


def test_review_result_rejects_unknown_key():
    with pytest.raises(ValidationError):
        ReviewResult(verdict="pass", extra="x")


def test_correction_value_none_validates_at_model_level():
    # The "value required for correct" rule is enforced by
    # _sanitize_review_result (Task 5's pipeline code), not by Pydantic --
    # this test documents and pins that boundary.
    correction = Correction(op="correct", path="medications[0].dosage", value=None)

    assert correction.value is None


def test_review_result_defaults_corrections_and_coverage_to_empty_list():
    result = ReviewResult(verdict="pass")

    assert result.corrections == []
    assert result.coverage == []


def test_correction_op_rejects_value_outside_vocabulary():
    with pytest.raises(ValidationError):
        Correction(op="rewrite", path="x")
