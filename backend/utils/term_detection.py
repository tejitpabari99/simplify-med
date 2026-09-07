"""
term_detection.py - Deterministic term detection for the V1.1 simplify pipeline.

Uses the JSON jargon source files directly to detect:
  - AHRQ plain-language substitution candidates
  - Michigan medical dictionary terms to preserve + define
  - Local abbreviation expansions

Returns structured data for LLM prompt construction and post-processing.
"""

import logging

from utils.jargon_db import (
    lookup_plain_language_terms,
    lookup_medical_terms,
    lookup_abbreviations,
    build_terms_glossary,
)
from utils.text_normalization import (
    contains_normalized_term,
    inflected_aliases,
    normalize_text,
)

logger = logging.getLogger(__name__)


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
