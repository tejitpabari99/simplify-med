"""Tests for utils/scoring.py — Patient Accessibility Score engine."""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(PROJECT_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from utils.scoring import score_text, _grade_to_score, WEIGHTS

# A rich enough medical paragraph so textstat has reliable sample size.
MEDICAL_TEXT = (
    "The patient was diagnosed with hypertension and type 2 diabetes mellitus. "
    "She was prescribed metformin 500 mg twice daily and lisinopril 10 mg once daily. "
    "Please take your medications as directed by your physician. "
    "Follow up with your primary care provider in four weeks. "
    "Monitor your blood glucose levels and report any hypoglycemia. "
    "Avoid excessive sodium intake to manage your blood pressure effectively. "
    "Contact the clinic if you experience chest pain, shortness of breath, or dizziness."
)

EXPECTED_DIMENSION_KEYS = {
    "grade_level",
    "jargon_density",
    "sentence_complexity",
    "passive_voice",
    "actionability",
    "numeracy_clarity",
    "structural_clarity",
}


class TestScoreTextReturnStructure(unittest.TestCase):
    def test_returns_dict_for_valid_text(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIsInstance(result, dict)

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(score_text(""))

    def test_returns_none_for_whitespace_only(self):
        self.assertIsNone(score_text("   \n  "))

    def test_composite_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("composite", result)

    def test_composite_in_range(self):
        result = score_text(MEDICAL_TEXT)
        self.assertGreaterEqual(result["composite"], 0)
        self.assertLessEqual(result["composite"], 100)

    def test_label_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("label", result)
        self.assertIn(result["label"], ("Patient-friendly", "Moderate", "Hard to read"))

    def test_word_count_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("word_count", result)
        self.assertGreater(result["word_count"], 0)

    def test_grade_estimate_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("grade_estimate", result)

    def test_dimensions_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("dimensions", result)

    def test_all_dimension_keys_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertEqual(EXPECTED_DIMENSION_KEYS, set(result["dimensions"].keys()))

    def test_each_dimension_has_score_and_raw(self):
        result = score_text(MEDICAL_TEXT)
        for key, dim in result["dimensions"].items():
            with self.subTest(dimension=key):
                self.assertIn("score", dim)
                self.assertIn("raw", dim)

    def test_each_dimension_score_in_range(self):
        result = score_text(MEDICAL_TEXT)
        for key, dim in result["dimensions"].items():
            with self.subTest(dimension=key):
                s = dim["score"]
                self.assertGreaterEqual(s, 0, f"Dimension '{key}' score {s} < 0")
                self.assertLessEqual(s, 100, f"Dimension '{key}' score {s} > 100")

    def test_research_basis_key_present(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIn("research_basis", result)
        self.assertEqual(set(result["research_basis"].keys()), EXPECTED_DIMENSION_KEYS)

    def test_low_confidence_set_for_very_short_text(self):
        # A single-sentence text has fewer than 3 sentences => low_confidence.
        short_text = "Take your medication."
        result = score_text(short_text)
        if result is not None:
            self.assertTrue(result.get("low_confidence"))

    def test_no_low_confidence_for_long_text(self):
        result = score_text(MEDICAL_TEXT)
        self.assertIsNotNone(result)
        # MEDICAL_TEXT has 7 sentences and well over 30 words.
        self.assertIsNot(result.get("low_confidence"), True)


class TestGradeToScore(unittest.TestCase):
    def test_grade_4_returns_100(self):
        self.assertEqual(_grade_to_score(4.0), 100)

    def test_grade_16_returns_0(self):
        self.assertEqual(_grade_to_score(16.0), 0)

    def test_grade_10_midpoint(self):
        # linear: (16 - 10) / 12 * 100 = 50
        self.assertEqual(_grade_to_score(10.0), 50)

    def test_grade_below_4_clamped_to_100(self):
        self.assertEqual(_grade_to_score(0.0), 100)

    def test_grade_above_16_clamped_to_0(self):
        self.assertEqual(_grade_to_score(20.0), 0)


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=9, msg=f"Weights sum {total} != 1.0")

    def test_all_dimension_keys_have_weights(self):
        self.assertEqual(set(WEIGHTS.keys()), EXPECTED_DIMENSION_KEYS)


def test_score_text_safe_returns_dict_on_success():
    from unittest.mock import patch
    from utils.scoring import score_text_safe
    with patch("utils.scoring.score_text", return_value={"score": 5}):
        result = score_text_safe("some text", "before")
    assert result == {"score": 5}


def test_score_text_safe_returns_none_on_exception():
    from unittest.mock import patch
    from utils.scoring import score_text_safe
    with patch("utils.scoring.score_text", side_effect=RuntimeError("fail")):
        result = score_text_safe("some text", "before")
    assert result is None


if __name__ == "__main__":
    unittest.main()
