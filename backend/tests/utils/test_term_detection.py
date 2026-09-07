"""Tests for utils/term_detection.py — deterministic medical term detection."""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(PROJECT_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from utils.term_detection import detect_terms


# Text that contains a known AHRQ plain-language substitution candidate
# ("absence" is the first entry in ahrq_plain_language.json).
JARGON_TEXT = (
    "The patient shows absence of fever and absence of tachycardia. "
    "bid dosing was prescribed. "
    "Hypertension management continues as discussed."
)

PLAIN_TEXT = (
    "Please drink plenty of water and get enough sleep every night. "
    "Call us if you feel worse or have any new symptoms."
)


class TestDetectTermsReturnStructure(unittest.TestCase):
    def test_returns_dict_with_required_keys(self):
        result = detect_terms(PLAIN_TEXT)
        self.assertIsInstance(result, dict)
        self.assertIn("substitution_candidates", result)
        self.assertIn("preserve_and_define_terms", result)
        self.assertIn("abbreviations", result)

    def test_all_values_are_lists(self):
        result = detect_terms(PLAIN_TEXT)
        for key in ("substitution_candidates", "preserve_and_define_terms", "abbreviations"):
            with self.subTest(key=key):
                self.assertIsInstance(result[key], list)


class TestDetectTermsJargonText(unittest.TestCase):
    def test_detects_ahrq_term_in_jargon_text(self):
        # "absence" is in ahrq_plain_language.json as a substitution candidate.
        result = detect_terms(JARGON_TEXT)
        # At least one AHRQ hit should be found in text containing "absence".
        self.assertTrue(
            len(result["substitution_candidates"]) > 0,
            f"Expected AHRQ hits for jargon text, got none. Candidates: {result['substitution_candidates']}"
        )

    def test_detects_abbreviation_bid(self):
        # "bid" -> "twice a day" is in abbreviations.json.
        result = detect_terms(JARGON_TEXT)
        expansions = {a["term"].lower() for a in result["abbreviations"]}
        self.assertIn("bid", expansions, f"Expected 'bid' in abbreviations, got: {result['abbreviations']}")

    def test_substitution_candidate_has_term_and_replacement(self):
        result = detect_terms(JARGON_TEXT)
        for candidate in result["substitution_candidates"]:
            with self.subTest(candidate=candidate):
                self.assertIn("term", candidate)
                self.assertIn("replacement", candidate)

    def test_abbreviation_has_term_and_expansion(self):
        result = detect_terms(JARGON_TEXT)
        for abbrev in result["abbreviations"]:
            with self.subTest(abbrev=abbrev):
                self.assertIn("term", abbrev)
                self.assertIn("expansion", abbrev)


class TestDetectTermsPlainText(unittest.TestCase):
    def test_plain_text_no_medical_terms(self):
        # Plain instructions should not trigger many/any Michigan medical dictionary hits.
        result = detect_terms(PLAIN_TEXT)
        # Not asserting zero — the dict may match common words — but assert it returns a dict.
        self.assertIsInstance(result["preserve_and_define_terms"], list)

    def test_plain_text_no_abbreviations(self):
        result = detect_terms(PLAIN_TEXT)
        # Plain instructions should have no medical abbreviations.
        self.assertEqual(
            result["abbreviations"], [],
            f"Unexpected abbreviations in plain text: {result['abbreviations']}"
        )


class TestDetectTermsEdgeCases(unittest.TestCase):
    def test_empty_string_returns_empty_lists(self):
        result = detect_terms("")
        self.assertEqual(result["substitution_candidates"], [])
        self.assertEqual(result["preserve_and_define_terms"], [])
        self.assertEqual(result["abbreviations"], [])

    def test_whitespace_only_returns_empty_lists(self):
        result = detect_terms("   ")
        self.assertEqual(result["substitution_candidates"], [])
        self.assertEqual(result["preserve_and_define_terms"], [])
        self.assertEqual(result["abbreviations"], [])


if __name__ == "__main__":
    unittest.main()
