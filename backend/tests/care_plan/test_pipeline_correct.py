"""Tests for CarePlanPipeline.correct() and the corrector-diff check
(_verify_correction_diff, _diff_item, _looks_like_pii_substitution,
_split_array_path) -- PRD 05 §7.3, the load-bearing test group for this
sub-project. Uses the file's established convention: direct construction
via CarePlanPipeline.__new__(CarePlanPipeline) plus monkeypatched
_generate_json, building CarePlan/Correction fixtures directly."""

import copy

import pytest

from care_plan.pipeline import CarePlanPipeline, _verify_correction_diff
from errors import SimplifyError, ErrorCode
from models.care_plan.care_plan import CarePlan
from models.review import Correction


def _medication(**overrides) -> dict:
    fields = dict(
        title="Metoprolol",
        plain_name="a heart medication",
        why="Prescribed by Doctor Alok Singh",
        dosage="10 mg",
        frequency="once daily",
        timing="",
        duration="",
        instructions="",
        side_effects_to_watch="",
        change="",
        status="to_do",
        source_fact_ids=[1],
    )
    fields.update(overrides)
    return fields


def _warning_sign(**overrides) -> dict:
    fields = dict(
        symptom="a symptom",
        what_it_might_mean="",
        what_to_do="",
        urgency=None,
        related_to="",
        source_fact_ids=[1],
    )
    fields.update(overrides)
    return fields


def _base_care_plan_dict(**overrides) -> dict:
    fields = dict(
        doc_type="care_plan",
        version="1.2",
        summary="You came in for care.",
        summary_fact_ids=[1],
        reason_for_visit=[],
        diagnosis={"changed_since_last_visit": "", "details": []},
        medications=[
            _medication(dosage="10 mg", frequency="once daily", source_fact_ids=[1]),
            _medication(dosage="20 mg", frequency="twice daily", source_fact_ids=[2]),
        ],
        tests=[],
        procedures=[],
        other=[],
        follow_up=[],
        warning_signs=[
            _warning_sign(symptom="signal 0"),
            _warning_sign(symptom="signal 1"),
            _warning_sign(symptom="signal 2"),
            _warning_sign(symptom="signal 3"),
        ],
        questions=[],
        low_priority=[],
        note=None,
        terms={},
    )
    fields.update(overrides)
    return fields


def _base_care_plan(**overrides) -> CarePlan:
    return CarePlan.model_validate(_base_care_plan_dict(**overrides))


def _mutate(plan: CarePlan, mutate_fn) -> CarePlan:
    """Deep-copy plan's JSON dump, apply mutate_fn to the dict in place, and
    revalidate -- mirrors how _verify_correction_diff itself compares two
    CarePlan.model_dump(mode="json") dicts."""
    plan_dict = copy.deepcopy(plan.model_dump(mode="json"))
    mutate_fn(plan_dict)
    return CarePlan.model_validate(plan_dict)


# ---------------------------------------------------------------------------
# Correction application on fixtures
# ---------------------------------------------------------------------------

def test_correct_applies_correct_op_to_exactly_the_named_field():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan()
    corrections = [Correction(op="correct", path="medications[0].dosage", value="5 mg")]
    after_dict = copy.deepcopy(before.model_dump(mode="json"))
    after_dict["medications"][0]["dosage"] = "5 mg"
    pipeline._generate_json = lambda *a, **k: after_dict

    result = pipeline.correct(before, corrections, [], [], [])

    assert result.medications[0].dosage == "5 mg"
    assert result.medications[1] == before.medications[1]
    assert result.warning_signs == before.warning_signs
    assert result.summary == before.summary


def test_correct_applies_not_stated_to_exact_sentinel_text():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan()
    corrections = [Correction(op="not_stated", path="medications[0].why")]
    after_dict = copy.deepcopy(before.model_dump(mode="json"))
    after_dict["medications"][0]["why"] = "Not stated in your note."
    pipeline._generate_json = lambda *a, **k: after_dict

    result = pipeline.correct(before, corrections, [], [], [])

    assert result.medications[0].why == "Not stated in your note."


def test_correct_applies_remove_on_array_item():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan(
        warning_signs=[_warning_sign(symptom="keep"), _warning_sign(symptom="drop")]
    )
    corrections = [Correction(op="remove", path="warning_signs[1]")]
    after_dict = copy.deepcopy(before.model_dump(mode="json"))
    del after_dict["warning_signs"][1]
    pipeline._generate_json = lambda *a, **k: after_dict

    result = pipeline.correct(before, corrections, [], [], [])

    assert len(result.warning_signs) == 1
    assert result.warning_signs[0].symptom == "keep"


def test_correct_applies_remove_on_summary():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan()
    corrections = [Correction(op="remove", path="summary")]
    after_dict = copy.deepcopy(before.model_dump(mode="json"))
    after_dict["summary"] = ""
    pipeline._generate_json = lambda *a, **k: after_dict

    result = pipeline.correct(before, corrections, [], [], [])

    assert result.summary == ""


def test_correct_short_circuits_and_returns_input_unchanged_when_corrections_empty():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan()

    result = pipeline.correct(before, [], [], [], [])

    assert result == before


# ---------------------------------------------------------------------------
# The corrector-diff check
# ---------------------------------------------------------------------------

def test_diff_check_passes_when_only_named_field_changes():
    before = _base_care_plan()
    corrections = [Correction(op="correct", path="medications[0].dosage", value="5 mg")]
    after = _mutate(before, lambda d: d["medications"][0].__setitem__("dosage", "5 mg"))

    _verify_correction_diff(before, after, corrections)  # no exception


def test_diff_check_rejects_change_to_unnamed_unrelated_field():
    before = _base_care_plan()
    corrections = [Correction(op="correct", path="medications[0].dosage", value="5 mg")]

    def _mutate_fn(d):
        d["medications"][0]["dosage"] = "5 mg"
        d["medications"][1]["frequency"] = "three times daily as needed for pain"

    after = _mutate(before, _mutate_fn)

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections)
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_diff_check_passes_small_pii_substitution_on_eligible_field():
    before = _base_care_plan()
    after = _mutate(
        before,
        lambda d: d["medications"][0].__setitem__("why", "Prescribed by your doctor"),
    )

    _verify_correction_diff(before, after, corrections=[])  # no exception


def test_diff_check_rejects_large_rewrite_disguised_as_pii():
    before = _base_care_plan()
    after = _mutate(
        before,
        lambda d: d["medications"][0].__setitem__(
            "why",
            "This medication was started because your recent lab work showed "
            "elevated blood pressure readings over several visits",
        ),
    )

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections=[])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_diff_check_rejects_pii_substitution_on_non_eligible_field():
    """dosage/status/severity/urgency must never be "PII-swept" -- a small
    token delta on a non-eligible field is still rejected."""
    before = _base_care_plan()
    after = _mutate(before, lambda d: d["medications"][0].__setitem__("dosage", "20 mg"))

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections=[])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_diff_check_accounts_for_removed_array_length():
    before = _base_care_plan()
    corrections = [
        Correction(op="remove", path="warning_signs[1]"),
        Correction(op="remove", path="warning_signs[3]"),
    ]

    def _mutate_fn(d):
        d["warning_signs"] = [d["warning_signs"][0], d["warning_signs"][2]]

    after = _mutate(before, _mutate_fn)

    _verify_correction_diff(before, after, corrections)  # no exception


def test_diff_check_rejects_wrong_surviving_count():
    before = _base_care_plan()
    corrections = [
        Correction(op="remove", path="warning_signs[1]"),
        Correction(op="remove", path="warning_signs[3]"),
    ]

    def _mutate_fn(d):
        # Only one of the two expected removals actually happened.
        d["warning_signs"] = [d["warning_signs"][0], d["warning_signs"][2], d["warning_signs"][3]]

    after = _mutate(before, _mutate_fn)

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections)
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
    assert "warning_signs" in exc_info.value.detail


def test_diff_check_rejects_reordered_items():
    before = _base_care_plan()
    corrections: list[Correction] = []

    def _mutate_fn(d):
        d["medications"] = [d["medications"][1], d["medications"][0]]

    after = _mutate(before, _mutate_fn)

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections)
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_diff_check_rejects_change_to_source_fact_ids():
    before = _base_care_plan()
    corrections = [Correction(op="correct", path="medications[0].dosage", value="5 mg")]

    def _mutate_fn(d):
        d["medications"][0]["dosage"] = "5 mg"
        d["medications"][0]["source_fact_ids"] = []

    after = _mutate(before, _mutate_fn)

    with pytest.raises(SimplifyError) as exc_info:
        _verify_correction_diff(before, after, corrections)
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


def test_correct_raises_on_diff_violation_rather_than_silently_falling_back():
    pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
    before = _base_care_plan()
    corrections = [Correction(op="correct", path="medications[0].dosage", value="5 mg")]

    def _mutate_fn(d):
        d["medications"][0]["dosage"] = "5 mg"
        d["medications"][1]["frequency"] = "three times daily as needed for pain"

    after_dict = copy.deepcopy(before.model_dump(mode="json"))
    _mutate_fn(after_dict)
    pipeline._generate_json = lambda *a, **k: after_dict

    with pytest.raises(SimplifyError) as exc_info:
        pipeline.correct(before, corrections, [], [], [])
    assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED
    # correct() itself never falls back to `before` -- no return value at all
    # on this path; the caller (06's iter_steps) owns the fallback (§4.8).
