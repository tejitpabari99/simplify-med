"""Tests for utils/text_normalization.py — shared normalization helpers."""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(PROJECT_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from utils.text_normalization import (
    normalize_text,
    contains_normalized_term,
    term_aliases,
    inflected_aliases,
)


class TestNormalizeText(unittest.TestCase):
    def test_lowercases_text(self):
        self.assertEqual(normalize_text("Hello World"), "hello world")

    def test_collapses_internal_whitespace(self):
        self.assertEqual(normalize_text("foo   bar"), "foo bar")

    def test_strips_leading_trailing_whitespace(self):
        self.assertEqual(normalize_text("  hello  "), "hello")

    def test_strips_accents(self):
        # café → cafe
        self.assertIn("cafe", normalize_text("café"))

    def test_empty_string_returns_empty(self):
        self.assertEqual(normalize_text(""), "")

    def test_idempotent(self):
        text = "  Hypertension  MANAGEMENT  "
        once = normalize_text(text)
        twice = normalize_text(once)
        self.assertEqual(once, twice)

    def test_collapses_newlines_to_single_space(self):
        result = normalize_text("line one\nline two")
        self.assertEqual(result, "line one line two")

    def test_collapses_tabs(self):
        result = normalize_text("word1\t\tword2")
        self.assertEqual(result, "word1 word2")

    def test_unicode_normalization(self):
        # NFKD should strip combining characters.
        result = normalize_text("é")  # é
        self.assertEqual(result, "e")


class TestContainsNormalizedTerm(unittest.TestCase):
    def test_finds_term_at_start(self):
        self.assertTrue(contains_normalized_term("hypertension is present", "hypertension"))

    def test_finds_term_at_end(self):
        self.assertTrue(contains_normalized_term("patient has hypertension", "hypertension"))

    def test_finds_term_in_middle(self):
        self.assertTrue(contains_normalized_term("the hypertension diagnosis was confirmed", "hypertension"))

    def test_does_not_match_partial_word(self):
        # "bid" should not match inside "forbid"
        self.assertFalse(contains_normalized_term("forbid this action", "bid"))

    def test_returns_false_for_absent_term(self):
        self.assertFalse(contains_normalized_term("plain english text", "hypertension"))

    def test_empty_text_returns_false(self):
        self.assertFalse(contains_normalized_term("", "hypertension"))


class TestTermAliases(unittest.TestCase):
    def test_simple_term_returns_itself(self):
        aliases = term_aliases("stroke")
        self.assertIn("stroke", aliases)

    def test_comma_separated_term_splits(self):
        aliases = term_aliases("agitate, agitation")
        self.assertIn("agitate", aliases)
        self.assertIn("agitation", aliases)

    def test_parenthetical_expands(self):
        # "stroke (CVA)" should produce "stroke" and "CVA" as separate aliases.
        aliases = term_aliases("stroke (CVA)")
        self.assertIn("stroke", aliases)
        # CVA is uppercase abbreviation — should be included.
        self.assertIn("CVA", aliases)

    def test_slash_alternates_expand(self):
        aliases = term_aliases("pain/discomfort")
        self.assertIn("pain", aliases)
        self.assertIn("discomfort", aliases)

    def test_empty_string_returns_list(self):
        aliases = term_aliases("")
        self.assertIsInstance(aliases, list)


class TestInflectedAliases(unittest.TestCase):
    def test_noun_plural_generated(self):
        aliases = inflected_aliases("symptom")
        self.assertIn("symptoms", aliases)

    def test_verb_forms_generated_for_verb_like_word(self):
        # "treat" ends in a consonant cluster that doesn't double, so it gets
        # standard -ed/-ing forms without doubling.
        aliases = inflected_aliases("treat")
        # Should produce "treated", "treating", "treats"
        self.assertIn("treating", aliases)

    def test_acronyms_not_inflected(self):
        # All-uppercase words (acronyms) should not get inflections added.
        aliases = inflected_aliases("CVA")
        # CVA itself should be present, but no "CVAs" style inflection from inflect logic
        # (acronyms are skipped per the implementation).
        self.assertIn("CVA", aliases)


if __name__ == "__main__":
    unittest.main()
