"""Tests for backend/utils/scoring_methods.py — per-method score extraction."""

import textstat

from utils.constants import Constants
from utils.scoring import score_text
from utils.scoring_methods import (
    compute_method_scores,
    score_cdc_cci,
    score_dale_chall,
    score_flesch_kincaid,
    score_pemat,
    score_sam,
    score_smog,
)

# Short text (< 30 sentences) used for SMOG insufficient-sample tests
SHORT_TEXT = "The patient has hypertension. Take your medication daily. Call your doctor if you have chest pain."

# Long enough text (30+ sentences) for SMOG to work — repeat SHORT_TEXT until we have > 30 sentences.
LONG_TEXT = (SHORT_TEXT + " ") * 15  # ~45 sentences


# ---------------------------------------------------------------------------
# score_smog
# ---------------------------------------------------------------------------

def test_short_text_insufficient_sample():
    result = score_smog(SHORT_TEXT)
    assert result["insufficient_sample"]
    assert result["score"] == 0
    assert result["grade"] == 0.0


def test_long_text_has_grade():
    result = score_smog(LONG_TEXT)
    assert not result["insufficient_sample"]
    assert "score" in result
    assert result["score"] >= 0
    assert result["score"] <= 100
    # grade should match textstat directly
    assert abs(result["grade"] - round(textstat.smog_index(LONG_TEXT), 1)) < 0.01


# ---------------------------------------------------------------------------
# score_flesch_kincaid
# ---------------------------------------------------------------------------

def test_flesch_kincaid_score_in_range():
    result = score_flesch_kincaid(SHORT_TEXT)
    assert "reading_ease" in result
    assert "grade_level" in result
    assert "score" in result
    assert result["score"] >= 0
    assert result["score"] <= 100


def test_score_equals_clamped_reading_ease():
    result = score_flesch_kincaid(SHORT_TEXT)
    expected = max(0, min(100, round(textstat.flesch_reading_ease(SHORT_TEXT))))
    assert result["score"] == expected


# ---------------------------------------------------------------------------
# score_dale_chall
# ---------------------------------------------------------------------------

def test_dale_chall_returns_expected_keys():
    result = score_dale_chall(SHORT_TEXT)
    assert "raw_score" in result
    assert "grade_range" in result
    assert "score" in result


def test_dale_chall_score_in_range():
    result = score_dale_chall(SHORT_TEXT)
    assert result["score"] >= 0
    assert result["score"] <= 100


# ---------------------------------------------------------------------------
# score_pemat
# ---------------------------------------------------------------------------

def _make_dims(score=70):
    return {
        "jargon_density": {"score": score},
        "sentence_complexity": {"score": score},
        "passive_voice": {"score": score},
        "numeracy_clarity": {"score": score},
        "structural_clarity": {"score": score},
        "actionability": {"score": score},
        "grade_level": {"score": score},
    }


def test_pemat_returns_expected_keys():
    result = score_pemat(_make_dims())
    assert "understandability" in result
    assert "actionability" in result
    assert "score" in result


def test_pemat_score_in_range():
    result = score_pemat(_make_dims(50))
    assert result["score"] >= 0
    assert result["score"] <= 100


# ---------------------------------------------------------------------------
# score_sam
# ---------------------------------------------------------------------------

def _make_sam_dims(score=70):
    return {
        "grade_level": {"score": score},
        "jargon_density": {"score": score},
        "sentence_complexity": {"score": score},
        "passive_voice": {"score": score},
        "structural_clarity": {"score": score},
        "actionability": {"score": score},
        "numeracy_clarity": {"score": score},
    }


def test_sam_returns_expected_keys():
    result = score_sam(_make_sam_dims())
    assert "content" in result
    assert "literacy_demand" in result
    assert "layout_typography" in result
    assert "score" in result


def test_sam_score_in_range():
    result = score_sam(_make_sam_dims(80))
    assert result["score"] >= 0
    assert result["score"] <= 100


# ---------------------------------------------------------------------------
# score_cdc_cci
# ---------------------------------------------------------------------------

def _make_cci_dims(actionability=70, numeracy=70):
    return {
        "actionability": {"score": actionability},
        "numeracy_clarity": {"score": numeracy},
        "grade_level": {"score": 70},
        "jargon_density": {"score": 70},
        "sentence_complexity": {"score": 70},
        "passive_voice": {"score": 70},
        "structural_clarity": {"score": 70},
    }


def test_all_items_met_when_high_scores():
    result = score_cdc_cci(_make_cci_dims(actionability=80, numeracy=80))
    assert result["main_message"] == 1
    assert result["behavioral_recommendations"] == 1
    assert result["numbers"] == 1
    assert result["call_to_action"] == 1
    assert result["score"] == 100


def test_no_items_met_when_low_scores():
    result = score_cdc_cci(_make_cci_dims(actionability=20, numeracy=20))
    assert result["main_message"] == 0
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# compute_method_scores
# ---------------------------------------------------------------------------

def test_returns_all_six_methods():
    full_score = score_text(LONG_TEXT)
    result = compute_method_scores(LONG_TEXT, full_score["dimensions"])
    expected_keys = set(Constants.Grading.GRADING_METHODS)
    assert set(result.keys()) == expected_keys


def test_each_method_has_score_in_range():
    full_score = score_text(SHORT_TEXT)
    result = compute_method_scores(SHORT_TEXT, full_score["dimensions"])
    for name, m in result.items():
        assert "score" in m, f"{name} missing 'score'"
        assert m["score"] >= 0, f"{name} score < 0"
        assert m["score"] <= 100, f"{name} score > 100"


def test_smog_insufficient_sample_for_short_text():
    full_score = score_text(SHORT_TEXT)
    result = compute_method_scores(SHORT_TEXT, full_score["dimensions"])
    assert result[Constants.Grading.GRADING_METHODS.SMOG]["insufficient_sample"]
    assert result[Constants.Grading.GRADING_METHODS.SMOG]["score"] == 0
