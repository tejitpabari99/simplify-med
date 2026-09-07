"""Tests for utils/jargon_db.py — JSON-backed jargon lookup helpers."""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(PROJECT_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from utils.jargon_db import (
    lookup_plain_language_terms,
    lookup_medical_terms,
    lookup_abbreviations,
    build_terms_glossary,
)
from utils.text_normalization import normalize_text


class TestModuleLoad(unittest.TestCase):
    def test_imports_without_error(self):
        # If the module imported successfully, this trivially passes.
        import utils.jargon_db as jdb
        self.assertIsNotNone(jdb)


class TestLookupPlainLanguageTerms(unittest.TestCase):
    def test_known_term_absence_returns_hit(self):
        # "absence" is the first entry in ahrq_plain_language.json.
        normalized = normalize_text("The patient shows absence of fever")
        hits = lookup_plain_language_terms(normalized)
        terms = [h["term"] for h in hits]
        self.assertTrue(
            any("absence" in t.lower() for t in terms),
            f"Expected 'absence' hit, got: {terms}"
        )

    def test_hit_has_required_keys(self):
        normalized = normalize_text("absence of symptoms")
        hits = lookup_plain_language_terms(normalized)
        self.assertTrue(len(hits) > 0, "Expected at least one hit for 'absence'")
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertIn("term", hit)
                self.assertIn("replacement", hit)
                self.assertIn("source", hit)
                self.assertIn("action", hit)

    def test_empty_text_returns_empty_list(self):
        hits = lookup_plain_language_terms("")
        self.assertEqual(hits, [])

    def test_no_duplicate_terms(self):
        # The same canonical term should not appear twice.
        normalized = normalize_text("absence of absence")
        hits = lookup_plain_language_terms(normalized)
        seen = set()
        for hit in hits:
            self.assertNotIn(hit["term"], seen, f"Duplicate term '{hit['term']}' in hits")
            seen.add(hit["term"])


class TestLookupMedicalTerms(unittest.TestCase):
    def test_known_term_abatement_returns_hit(self):
        # "abatement" is in michigan_medical_dictionary.json with a definition.
        normalized = normalize_text("The abatement of symptoms was observed.")
        hits = lookup_medical_terms(normalized)
        terms = [h["term"] for h in hits]
        self.assertTrue(
            any("abatement" in t.lower() for t in terms),
            f"Expected 'abatement' hit, got: {terms}"
        )

    def test_hit_has_required_keys(self):
        normalized = normalize_text("abatement of pain was noted")
        hits = lookup_medical_terms(normalized)
        if not hits:
            self.skipTest("No hits for test term; check michigan_medical_dictionary.json")
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertIn("term", hit)
                self.assertIn("definition", hit)
                self.assertIn("source", hit)
                self.assertIn("action", hit)

    def test_empty_text_returns_empty_list(self):
        hits = lookup_medical_terms("")
        self.assertEqual(hits, [])


class TestLookupAbbreviations(unittest.TestCase):
    def test_bid_returns_expansion(self):
        # "bid" -> "twice a day" is the first entry in abbreviations.json.
        normalized = normalize_text("Take 500 mg bid with food")
        hits = lookup_abbreviations(normalized)
        abbrev_terms = {h["term"].lower() for h in hits}
        self.assertIn("bid", abbrev_terms, f"Expected 'bid' hit, got: {hits}")

    def test_hit_has_term_and_expansion(self):
        normalized = normalize_text("Take 500 mg bid with food")
        hits = lookup_abbreviations(normalized)
        for hit in hits:
            with self.subTest(hit=hit):
                self.assertIn("term", hit)
                self.assertIn("expansion", hit)
                self.assertIn("source", hit)

    def test_empty_text_returns_empty_list(self):
        hits = lookup_abbreviations("")
        self.assertEqual(hits, [])

    def test_no_abbreviation_text_returns_empty(self):
        normalized = normalize_text("the patient drinks water and rests")
        hits = lookup_abbreviations(normalized)
        self.assertEqual(hits, [])


class TestBuildTermsGlossary(unittest.TestCase):
    def test_builds_dict_from_hits(self):
        hits = [
            {"term": "Hypertension", "definition": "High blood pressure", "source": "test", "imgUrl": None, "altText": None},
        ]
        glossary = build_terms_glossary(hits)
        self.assertIn("Hypertension", glossary)
        self.assertEqual(glossary["Hypertension"]["definition"], "High blood pressure")

    def test_empty_hits_returns_empty_dict(self):
        self.assertEqual(build_terms_glossary([]), {})

    def test_last_write_wins_for_duplicates(self):
        hits = [
            {"term": "Stroke", "definition": "first def", "source": "src1", "imgUrl": None, "altText": None},
            {"term": "Stroke", "definition": "second def", "source": "src2", "imgUrl": None, "altText": None},
        ]
        glossary = build_terms_glossary(hits)
        self.assertEqual(glossary["Stroke"]["definition"], "second def")


if __name__ == "__main__":
    unittest.main()
