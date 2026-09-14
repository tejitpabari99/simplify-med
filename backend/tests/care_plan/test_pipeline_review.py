"""Tests for CarePlanPipeline.review(), _resolve_path, and
_sanitize_review_result -- PRD 05 §7.2. Uses the file's established
convention: direct construction via CarePlanPipeline.__new__(CarePlanPipeline)
plus monkeypatched _generate_json, building Fact/CarePlan/ReviewResult
fixtures directly."""

import logging

import pytest

from care_plan.pipeline import (
    CarePlanPipeline,
    _log_coverage_summary,
    _resolve_path,
    _sanitize_review_result,
    _targets_removed_item,
)
from models.care_plan.care_plan import CarePlan, Diagnosis, DiagnosisDetail, Medication
from models.ledger import Fact
from models.review import Correction, CoverageEntry, ReviewResult


def _medication(**overrides) -> Medication:
    fields = dict(status="to_do", source_fact_ids=[1])
    fields.update(overrides)
    return Medication(**fields)


def _care_plan_with_two_medications() -> CarePlan:
    return CarePlan(
        summary="You came in for care.",
        medications=[
            _medication(dosage="10 mg", why="Prescribed for your condition."),
            _medication(dosage="20 mg", why=None),
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


def test_targets_removed_item_matches_nested_dotted_array_path():
    """Finding 2 regression: a removed item at a dotted, nested array path
    (e.g. `diagnosis.details[0]`, not a bare top-level `array[N]`) must
    still match a path naming a field on that same item
    (`diagnosis.details[0].description`) -- the old anchored regex
    (`^[a-zA-Z_][a-zA-Z0-9_]*\\[\\d+\\]`) only ever matched an UNDOTTED
    leading segment and so silently never matched here."""
    assert _targets_removed_item("diagnosis.details[0].description", {"diagnosis.details[0]"}) is True
    assert _targets_removed_item("diagnosis.details[0]", {"diagnosis.details[0]"}) is True
    # A different index under the same dotted array must NOT match --
    # nor should numeric-prefix collisions ([1] vs [10]) be conflated.
    assert _targets_removed_item("diagnosis.details[1].description", {"diagnosis.details[0]"}) is False
    assert _targets_removed_item("diagnosis.details[10]", {"diagnosis.details[1]"}) is False
    assert _targets_removed_item("diagnosis.details[1]", {"diagnosis.details[10]"}) is False


def test_sanitize_remove_wins_over_correct_on_same_nested_item():
    """Finding 2 regression, exercised through _sanitize_review_result
    (mirrors test_sanitize_remove_wins_over_correct_on_same_item, but with
    a dotted nested array path): a `remove` on `diagnosis.details[0]` must
    still suppress a `correct` targeting `diagnosis.details[0].description`."""
    care_plan = CarePlan(
        summary="You came in for care.",
        diagnosis=Diagnosis(
            details=[
                DiagnosisDetail(title="Hypertension", description="High blood pressure."),
                DiagnosisDetail(title="Diabetes", description="Type 2 diabetes."),
            ],
        ),
    )
    result = ReviewResult(
        verdict="needs_correction",
        corrections=[
            Correction(op="remove", path="diagnosis.details[0]"),
            Correction(op="correct", path="diagnosis.details[0].description", value="Updated text."),
        ],
    )

    sanitized = _sanitize_review_result(result, care_plan, _facts(1))

    assert len(sanitized.corrections) == 1
    assert sanitized.corrections[0].op == "remove"
    assert sanitized.corrections[0].path == "diagnosis.details[0]"


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


# ---------------------------------------------------------------------------
# _log_coverage_summary -- PRD 11 §7.1
# ---------------------------------------------------------------------------

def test_log_coverage_summary_all_facts_covered(caplog):
    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary(
            [CoverageEntry(fact_id=i, present=True) for i in (1, 2, 3)],
            _facts(3),
        )

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    assert records[0].coverage_signal == {
        "total": 3,
        "omitted": 0,
        "rate": 0.0,
        "omitted_by_category": {},
    }


def test_log_coverage_summary_some_facts_omitted_mixed_categories(caplog):
    facts = [
        Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="fact 1"),
        Fact(id=2, category="medications", unit_id=1, char_start=0, char_end=1, text="fact 2"),
        Fact(id=3, category="warning_signs", unit_id=1, char_start=0, char_end=1, text="fact 3"),
    ]
    coverage = [
        CoverageEntry(fact_id=1, present=False),
        CoverageEntry(fact_id=2, present=True),
        CoverageEntry(fact_id=3, present=False),
    ]

    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary(coverage, facts)

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    assert records[0].coverage_signal == {
        "total": 3,
        "omitted": 2,
        "rate": pytest.approx(2 / 3, abs=1e-4),
        "omitted_by_category": {"medications": 1, "warning_signs": 1},
    }


def test_log_coverage_summary_empty_coverage_and_empty_facts_logs_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary([], [])

    assert caplog.records == []


def test_log_coverage_summary_empty_coverage_with_nonempty_facts_treats_all_as_omitted(caplog):
    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary([], _facts(2))

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    assert records[0].coverage_signal["omitted"] == 2
    assert records[0].coverage_signal["total"] == 2
    assert records[0].coverage_signal["rate"] == 1.0


def test_log_coverage_summary_ignores_coverage_entry_for_unknown_fact_id(caplog):
    coverage = [
        CoverageEntry(fact_id=1, present=True),
        CoverageEntry(fact_id=999, present=True),
    ]

    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary(coverage, _facts(1))

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    assert records[0].coverage_signal["omitted"] == 0
    assert records[0].coverage_signal["total"] == 1


def test_log_coverage_summary_extra_dict_has_exactly_four_keys(caplog):
    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary([CoverageEntry(fact_id=1, present=True)], _facts(1))

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    assert set(records[0].coverage_signal.keys()) == {
        "total", "omitted", "rate", "omitted_by_category",
    }


def test_log_coverage_summary_message_has_no_per_fact_category_interpolation(caplog):
    """Sanity check, not a strict requirement (PRD 11 §7.1): the human-readable
    message stays generic/aggregate-shaped -- per-fact category detail only
    ever goes into `extra`, never into the message string. Uses category
    values ("warning_signs", "follow_up") that don't appear anywhere in the
    generic message text, so a substring match here is meaningful."""
    facts = [
        Fact(id=1, category="warning_signs", unit_id=1, char_start=0, char_end=1, text="fact 1"),
        Fact(id=2, category="follow_up", unit_id=1, char_start=0, char_end=1, text="fact 2"),
    ]
    coverage = [
        CoverageEntry(fact_id=1, present=False),
        CoverageEntry(fact_id=2, present=False),
    ]

    with caplog.at_level(logging.INFO, logger="care_plan.pipeline"):
        _log_coverage_summary(coverage, facts)

    records = [r for r in caplog.records if r.getMessage().startswith("review: coverage signal")]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "warning_signs" not in message
    assert "follow_up" not in message
