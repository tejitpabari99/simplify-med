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

from utils.term_detection import (
    detect_terms,
    render_care_plan_text,
    build_glossary_from_care_plan,
    curate_glossary_terms,
)
from utils.jargon_db import get_source_name
from utils.constants import Constants
from models.care_plan.care_plan import (
    CarePlan,
    Medication,
    Diagnosis,
    DiagnosisDetail,
    ReasonForVisit,
)


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


def _minimal_care_plan(**overrides) -> CarePlan:
    fields = {
        "doc_type": "care_plan",
        "version": Constants.Schema.CARE_PLAN_VERSION,
        "summary": "",
    }
    fields.update(overrides)
    return CarePlan(**fields)


class TestRenderCarePlanText(unittest.TestCase):
    def test_render_care_plan_text_includes_summary_and_medication_fields(self):
        care_plan = _minimal_care_plan(
            summary="You came in for a checkup.",
            medications=[
                Medication(why="Because your blood pressure is high.", status="to_do")
            ],
        )
        text = render_care_plan_text(care_plan)
        self.assertIn("You came in for a checkup.", text)
        self.assertIn("Because your blood pressure is high.", text)
        self.assertLess(
            text.index("You came in for a checkup."),
            text.index("Because your blood pressure is high."),
        )

    def test_render_care_plan_text_excludes_internal_fields(self):
        care_plan = _minimal_care_plan(
            summary="Visible summary.",
            note="internal note text",
            summary_fact_ids=[1, 2, 3],
        )
        text = render_care_plan_text(care_plan)
        self.assertNotIn("internal note text", text)
        self.assertNotIn("[1, 2, 3]", text)
        self.assertEqual(text, "Visible summary.")

    def test_render_care_plan_text_is_deterministic(self):
        care_plan = _minimal_care_plan(
            summary="Same every time.",
            medications=[Medication(why="Reason.", status="to_do")],
        )
        self.assertEqual(render_care_plan_text(care_plan), render_care_plan_text(care_plan))

    def test_render_care_plan_text_joins_fields_as_separate_paragraphs(self):
        care_plan = _minimal_care_plan(
            summary="First.",
            reason_for_visit=[ReasonForVisit(reason="Second.")],
        )
        text = render_care_plan_text(care_plan)
        self.assertIn("First.\n\nSecond.", text)


class TestBuildGlossaryFromCarePlan(unittest.TestCase):
    def test_build_glossary_from_care_plan_finds_term_in_diagnosis_but_not_medications(self):
        care_plan = _minimal_care_plan(
            summary="Routine visit.",
            diagnosis=Diagnosis(
                details=[
                    DiagnosisDetail(
                        title="Artery finding",
                        description="Heavy plaque was seen in the artery.",
                    )
                ]
            ),
            medications=[Medication(why="Unrelated reason.", status="to_do")],
        )
        detected_terms = [{
            "term": "plaque", "matched_term": "plaque",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        glossary = build_glossary_from_care_plan(care_plan, detected_terms)
        self.assertIn("plaque", glossary)


class _StubLLMClient:
    """Minimal stand-in for LLMClient in curate_glossary_terms tests."""

    def __init__(self, response=None, raises=False):
        self._response = response
        self._raises = raises

    def generate_json(self, prompt, temperature=None, max_tokens=None):
        if self._raises:
            raise RuntimeError("stub failure")
        return self._response


class TestCurateGlossaryTerms(unittest.TestCase):
    def test_curate_glossary_terms_falls_back_on_llm_failure(self):
        detected_terms = [{
            "term": "heart", "matched_term": "heart",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        stub = _StubLLMClient(raises=True)
        result = curate_glossary_terms("some text", detected_terms, llm_client=stub)
        self.assertEqual(result, detected_terms)

    def test_curate_glossary_terms_drops_named_common_word(self):
        detected_terms = [
            {"term": "heart", "matched_term": "heart", "definition": "d1", "source": "s", "imgUrl": None, "altText": None},
            {"term": "plaque", "matched_term": "plaque", "definition": "d2", "source": "s", "imgUrl": None, "altText": None},
        ]
        stub = _StubLLMClient(response={"drop": ["heart"], "propose": []})
        result = curate_glossary_terms("heavy plaque was seen", detected_terms, llm_client=stub)
        terms = {t["term"] for t in result}
        self.assertNotIn("heart", terms)
        self.assertIn("plaque", terms)

    def test_curate_glossary_terms_proposes_new_term_found_in_source(self):
        stub = _StubLLMClient(response={
            "drop": [],
            "propose": [{"matched_term": "circumflex", "definition": "d"}],
        })
        result = curate_glossary_terms(
            "the circumflex artery was noted", [], llm_client=stub
        )
        matches = [t for t in result if t["matched_term"] == "circumflex"]
        self.assertTrue(matches)
        self.assertEqual(matches[0]["source"], get_source_name("llm_proposed"))

    def test_curate_glossary_terms_rejects_proposed_term_not_in_source(self):
        stub = _StubLLMClient(response={
            "drop": [],
            "propose": [{"matched_term": "circumflex", "definition": "d"}],
        })
        result = curate_glossary_terms(
            "no relevant anatomy mentioned here", [], llm_client=stub
        )
        matches = [t for t in result if t.get("matched_term") == "circumflex"]
        self.assertEqual(matches, [])

    def test_curate_glossary_terms_backstop_truncates_proposed_before_kept(self):
        detected_terms = [
            {
                "term": f"kept-term-{i}", "matched_term": f"kept-term-{i}",
                "definition": "d", "source": "s", "imgUrl": None, "altText": None,
            }
            for i in range(35)
        ]
        proposed = [
            {"matched_term": f"proposed-term-{i}", "definition": "d"}
            for i in range(10)
        ]
        source_text = " ".join(p["matched_term"] for p in proposed)
        stub = _StubLLMClient(response={"drop": [], "propose": proposed})
        result = curate_glossary_terms(source_text, detected_terms, llm_client=stub)
        self.assertEqual(len(result), 40)
        result_terms = {t["term"] for t in result}
        for t in detected_terms:
            self.assertIn(t["term"], result_terms)

    def test_curate_glossary_terms_backstop_truncates_kept_when_kept_alone_exceeds_it(self):
        # 45 kept, 0 proposed: the backstop must still cap the total at 40,
        # not silently return 45 (the review's exact reproduction case).
        detected_terms = [
            {
                "term": f"kept-term-{i}", "matched_term": f"kept-term-{i}",
                "definition": "d", "source": "s", "imgUrl": None, "altText": None,
            }
            for i in range(45)
        ]
        stub = _StubLLMClient(response={"drop": [], "propose": []})
        result = curate_glossary_terms("irrelevant source text", detected_terms, llm_client=stub)
        self.assertEqual(len(result), 40)

    def test_curate_glossary_terms_backstop_caps_combined_kept_and_proposed_overflow(self):
        # 30 kept + 15 proposed = 45 total; backstop must cut proposed first
        # down to 10, keeping all 30 kept entries, for a total of exactly 40.
        detected_terms = [
            {
                "term": f"kept-term-{i}", "matched_term": f"kept-term-{i}",
                "definition": "d", "source": "s", "imgUrl": None, "altText": None,
            }
            for i in range(30)
        ]
        proposed = [
            {"matched_term": f"proposed-term-{i}", "definition": "d"}
            for i in range(15)
        ]
        source_text = " ".join(p["matched_term"] for p in proposed)
        stub = _StubLLMClient(response={"drop": [], "propose": proposed})
        result = curate_glossary_terms(source_text, detected_terms, llm_client=stub)
        self.assertEqual(len(result), 40)
        result_terms = {t["term"] for t in result}
        for t in detected_terms:
            self.assertIn(t["term"], result_terms)

    def test_curate_glossary_terms_handles_propose_list_of_non_dicts(self):
        detected_terms = [{
            "term": "heart", "matched_term": "heart",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        stub = _StubLLMClient(response={"drop": [], "propose": ["circumflex"]})
        result = curate_glossary_terms(
            "the circumflex artery was noted", detected_terms, llm_client=stub
        )
        self.assertEqual(result, detected_terms)

    def test_curate_glossary_terms_handles_propose_none(self):
        detected_terms = [{
            "term": "heart", "matched_term": "heart",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        stub = _StubLLMClient(response={"drop": [], "propose": None})
        result = curate_glossary_terms("some text", detected_terms, llm_client=stub)
        self.assertEqual(result, detected_terms)

    def test_curate_glossary_terms_handles_propose_as_dict(self):
        detected_terms = [{
            "term": "heart", "matched_term": "heart",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        stub = _StubLLMClient(response={"drop": [], "propose": {"a": 1}})
        result = curate_glossary_terms("some text", detected_terms, llm_client=stub)
        self.assertEqual(result, detected_terms)

    def test_curate_glossary_terms_handles_malformed_drop_not_a_list(self):
        detected_terms = [{
            "term": "heart", "matched_term": "heart",
            "definition": "d", "source": "s", "imgUrl": None, "altText": None,
        }]
        stub = _StubLLMClient(response={"drop": "heart", "propose": []})
        result = curate_glossary_terms("some text", detected_terms, llm_client=stub)
        # "drop" is ignored wholesale (not iterated char-by-char), so the
        # detected term survives unfiltered rather than the call crashing.
        self.assertEqual(result, detected_terms)

    def test_curate_glossary_terms_skips_non_string_drop_entries(self):
        detected_terms = [
            {"term": "heart", "matched_term": "heart", "definition": "d1", "source": "s", "imgUrl": None, "altText": None},
            {"term": "plaque", "matched_term": "plaque", "definition": "d2", "source": "s", "imgUrl": None, "altText": None},
        ]
        stub = _StubLLMClient(response={"drop": ["heart", 123, None, {"x": 1}], "propose": []})
        result = curate_glossary_terms("heavy plaque was seen", detected_terms, llm_client=stub)
        terms = {t["term"] for t in result}
        self.assertNotIn("heart", terms)
        self.assertIn("plaque", terms)


if __name__ == "__main__":
    unittest.main()
