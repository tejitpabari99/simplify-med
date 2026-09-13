"""
term_detection.py - Deterministic term detection for the V1.1 simplify pipeline.

Uses the JSON jargon source files directly to detect:
  - AHRQ plain-language substitution candidates
  - Michigan medical dictionary terms to preserve + define
  - Local abbreviation expansions

Returns structured data for LLM prompt construction and post-processing.
"""

import logging
from pathlib import Path

from utils.jargon_db import (
    lookup_plain_language_terms,
    lookup_medical_terms,
    lookup_abbreviations,
    build_terms_glossary,
    get_source_name,
)
from utils.text_normalization import (
    contains_normalized_term,
    inflected_aliases,
    normalize_text,
)
from utils.llm import LLMClient
from utils.constants import Constants

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "care_plan" / "prompts"
_CURATE_PROMPT = (_PROMPTS_DIR / "curate_glossary.txt").read_text(encoding="utf-8")
_CURATION_PROPOSAL_HINT = 15   # model-facing hint, not enforced
_CURATION_TOTAL_BACKSTOP = 40  # code-enforced, covers kept + proposed_hits


def detect_terms(text: str) -> dict:
    """
    Run all three deterministic detectors against the input text.

    Returns:
        {
          "substitution_candidates": [{term, replacement, source, action, notes}],
          "preserve_and_define_terms": [{term, definition, source, action}],
          "abbreviations": [{term, expansion, source}],
        }
    """
    # Normalize once so all downstream detectors use identical matching rules.
    normalized_text = normalize_text(text)
    try:
        # Fail open: if one dataset lookup fails, keep the pipeline running.
        substitution_candidates = lookup_plain_language_terms(normalized_text)
    except Exception:
        logger.exception("term_detection: AHRQ lookup failed - continuing with empty list")
        substitution_candidates = []

    try:
        # Fail open: keep partial results from other detectors.
        preserve_and_define_terms = lookup_medical_terms(normalized_text)
    except Exception:
        logger.exception("term_detection: Michigan lookup failed - continuing with empty list")
        preserve_and_define_terms = []

    try:
        # Fail open: abbreviation misses should not block simplification.
        abbreviations = lookup_abbreviations(normalized_text)
    except Exception:
        logger.exception("term_detection: abbreviation lookup failed - continuing with empty list")
        abbreviations = []

    logger.info(
        "term_detection: found %d AHRQ | %d medical | %d abbrev",
        len(substitution_candidates),
        len(preserve_and_define_terms),
        len(abbreviations),
    )

    return {
        "substitution_candidates": substitution_candidates,
        "preserve_and_define_terms": preserve_and_define_terms,
        "abbreviations": abbreviations,
    }


def build_glossary_from_simplified_text(
    simplified_text: str,
    preserve_and_define_terms: list[dict],
) -> dict[str, dict]:
    """
    Re-detect Michigan medical terms in the final simplified text
    and build a compact glossary dict for the JSON output.

    This runs AFTER the LLM has rewritten the text, so the glossary
    only contains terms actually present in the output.

    Returns:
        {"multiple sclerosis": {"definition": "...", "source": "..."}, ...}
    """
    # Re-check against final output text so glossary contains only surviving terms.
    normalized_text = normalize_text(simplified_text)
    found_terms = []
    for term in preserve_and_define_terms:
        # Check the concrete matched variant first, then canonical inflections.
        lookup_aliases = [
            term.get("matched_term") or term["term"],
            *inflected_aliases(term["term"]),
        ]
        if any(
            # Normalize alias candidates to align with normalized output text.
            contains_normalized_term(normalized_text, normalize_text(alias))
            for alias in lookup_aliases
        ):
            found_terms.append(term)
    # Convert filtered hits into the compact keyed glossary structure.
    return build_terms_glossary(found_terms)


def _format_detected_terms_for_curation(detected_terms: list[dict]) -> str:
    """Format Michigan-dictionary hits as 'term: definition' lines for the
    curation prompt's DETECTED TERMS section (PRD 07 §4.3)."""
    if not detected_terms:
        return "(none detected)"
    return "\n".join(f"- {t['term']}: {t['definition']}" for t in detected_terms)


def curate_glossary_terms(
    source_text: str,
    detected_terms: list[dict],
    llm_client: LLMClient | None = None,
) -> list[dict]:
    """Filter + propose pass over the deterministically detected, stoplist-
    pruned Michigan terms (brief §3.8 step 2). Depends only on the raw
    source text and detect_terms' own output -- not on anything ground(),
    assemble_and_render(), review(), or correct() produce -- so 06 can
    submit it to a background thread immediately after detect_terms
    completes, in parallel with the rest of the pipeline. Must never raise:
    a curation failure falls back to the deterministic list untouched,
    the same fail-open posture every other detector in this module uses.

    Returns a list shaped identically to lookup_medical_terms() hits, so
    downstream code (build_glossary_from_care_plan, build_terms_glossary)
    treats curated and proposed entries exactly like deterministic ones.
    """
    try:
        client = llm_client or LLMClient()
        prompt = _CURATE_PROMPT.format(
            max_terms=_CURATION_PROPOSAL_HINT,
            detected_terms_block=_format_detected_terms_for_curation(detected_terms),
            source_text=source_text,
        )
        raw = client.generate_json(
            prompt, temperature=Constants.Llm.TEMPERATURE_JSON, max_tokens=Constants.Llm.MAX_TOKENS
        )
        if not isinstance(raw, dict):
            raise ValueError(f"expected dict, got {type(raw)}")
        drop = {str(d).strip().lower() for d in raw.get("drop", [])}
        propose = raw.get("propose", [])
    except Exception:
        logger.exception("curate_glossary_terms: curation call failed - keeping detected terms unfiltered")
        return detected_terms

    kept = [t for t in detected_terms if t["term"].strip().lower() not in drop]
    existing = {t["matched_term"].strip().lower() for t in kept}
    normalized_source = normalize_text(source_text)

    proposed_hits = []
    for item in propose:
        matched_term = str(item.get("matched_term", "")).strip()
        definition = str(item.get("definition", "")).strip()
        if not matched_term or not definition or matched_term.lower() in existing:
            continue
        # Deterministic guard: a proposed term must actually be a substring
        # of the note. A model that "proposes" a word not in the source
        # cannot have extracted it -- cannot be a real finding.
        if not contains_normalized_term(normalized_source, normalize_text(matched_term)):
            continue
        existing.add(matched_term.lower())
        proposed_hits.append({
            "term": matched_term,
            "matched_term": matched_term,
            "definition": definition,
            "source": get_source_name("llm_proposed"),
            "imgUrl": None,
            "altText": None,
            "action": "preserve_define",
        })

    combined = kept + proposed_hits
    if len(combined) > _CURATION_TOTAL_BACKSTOP:
        logger.warning(
            "curate_glossary_terms: truncating %d total terms to backstop %d",
            len(combined), _CURATION_TOTAL_BACKSTOP,
        )
        overflow = len(combined) - _CURATION_TOTAL_BACKSTOP
        proposed_hits = proposed_hits[: max(0, len(proposed_hits) - overflow)]
        combined = kept + proposed_hits
    return combined


def format_substitution_candidates_for_prompt(candidates: list[dict]) -> str:
    """Format AHRQ hits as a bulleted list for the LLM prompt."""
    if not candidates:
        return "(none detected)"
    lines = [
        # Keep format deterministic and brief for prompt-token control.
        f"- \"{candidate['term']}\" -> \"{candidate['replacement']}\""
        + (f"  ({candidate['notes']})" if candidate.get("notes") else "")
        for candidate in candidates[:40]
    ]
    return "\n".join(lines)


def format_medical_terms_for_prompt(terms: list[dict]) -> str:
    """Format Michigan medical terms as a list for the LLM prompt."""
    if not terms:
        return "(none detected)"
    # Cap list size to avoid overloading the instruction section.
    return "\n".join(f"- {term['term']}" for term in terms[:60])


def format_abbreviations_for_prompt(abbreviations: list[dict]) -> str:
    """Format abbreviation expansions as a list for the LLM prompt."""
    if not abbreviations:
        return "(none detected)"
    # Cap list size to keep prompt context focused on highest-value matches.
    return "\n".join(
        f"- \"{abbreviation['term']}\" -> \"{abbreviation['expansion']}\""
        for abbreviation in abbreviations[:30]
    )
