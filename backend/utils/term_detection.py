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
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from models.care_plan.care_plan import CarePlan

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


def render_care_plan_text(care_plan: "CarePlan") -> str:
    """Every patient-visible text field on a CarePlan, concatenated in the
    eight-card frontend's top-to-bottom order (brief §3.10), one field
    value per paragraph (blank-line separated) so paragraph/sentence-
    boundary-sensitive consumers -- utils/scoring.py:186's paragraph split
    and its ^-anchored MULTILINE regexes -- don't merge unrelated fields
    into one run-on unit.

    Two consumers: (1) build_glossary_from_care_plan below, re-detecting
    against the FINAL corrected output (brief §3.7); (2) 06's "after"
    readability score over that final rendered output (brief §2.5; the gap
    PRD 04 §9 flags, closed here).

    Excludes: doc_type/version (schema plumbing), status/severity/urgency
    (typed enums, not free text), note (internal, zero frontend consumers),
    summary_fact_ids (ints), and terms itself (built FROM this text).
    """
    parts: list[str] = []

    def add(value) -> None:
        if value:
            parts.append(value)

    add(care_plan.summary)
    for r in care_plan.reason_for_visit:
        add(r.reason); add(r.description)
    add(care_plan.diagnosis.changed_since_last_visit)
    for d in care_plan.diagnosis.details:
        add(d.title); add(d.plain_name); add(d.description); add(d.what_it_means_for_you)
    for m in care_plan.medications:
        add(m.title); add(m.plain_name); add(m.why); add(m.dosage)
        add(m.frequency); add(m.timing); add(m.duration)
        add(m.instructions); add(m.side_effects_to_watch); add(m.change)
    for t in care_plan.tests:
        add(t.title); add(t.plain_name); add(t.why); add(t.description); add(t.preparation)
    for p in care_plan.procedures:
        add(p.title); add(p.plain_name); add(p.why); add(p.what_to_expect); add(p.timeframe)
    for o in care_plan.other:
        add(o.title); add(o.why)
        for step in o.steps:
            add(step)
        add(o.description); add(o.frequency); add(o.duration)
    for f in care_plan.follow_up:
        add(f.description); add(f.time_frame)
    for w in care_plan.warning_signs:
        add(w.symptom); add(w.what_it_might_mean); add(w.what_to_do); add(w.related_to)
    for q in care_plan.questions:
        add(q)
    for item in care_plan.low_priority:
        add(item)

    return "\n\n".join(parts)


def build_glossary_from_care_plan(
    care_plan: "CarePlan",
    detected_terms: list[dict],
) -> dict[str, dict]:
    """Re-detect terms against the FINAL corrected CarePlan (brief §3.7 /
    §3.8 step 3). `detected_terms` is curate_glossary_terms' output
    (curated + proposed), not the raw deterministic hits -- curation has
    already finished on its background thread by the time correct() (05)
    returns, well before this runs."""
    normalized_text = normalize_text(render_care_plan_text(care_plan))
    found_terms = []
    for term in detected_terms:
        lookup_aliases = [term.get("matched_term") or term["term"], *inflected_aliases(term["term"])]
        if any(contains_normalized_term(normalized_text, normalize_text(alias)) for alias in lookup_aliases):
            found_terms.append(term)
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

    The entire body below the LLM call is defensive on purpose: the model's
    JSON can be well-formed (a dict) but wrong-shaped in ways a plain
    isinstance(raw, dict) check doesn't catch -- "propose" not a list,
    "drop" not a list, individual propose items not dicts, etc. Every one
    of those is validated and downgraded to "ignore this piece" rather than
    left to raise, and the whole function is additionally wrapped so any
    other, unanticipated failure still falls back to the deterministic
    list untouched -- this function must never raise.
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

        drop_raw = raw.get("drop", [])
        if not isinstance(drop_raw, list):
            logger.warning(
                "curate_glossary_terms: 'drop' was not a list (got %s) - ignoring",
                type(drop_raw).__name__,
            )
            drop_raw = []
        drop = set()
        skipped_drop = 0
        for d in drop_raw:
            if isinstance(d, str):
                drop.add(d.strip().lower())
            else:
                skipped_drop += 1
        if skipped_drop:
            logger.warning(
                "curate_glossary_terms: skipped %d malformed 'drop' entries", skipped_drop
            )

        propose_raw = raw.get("propose", [])
        if not isinstance(propose_raw, list):
            logger.warning(
                "curate_glossary_terms: 'propose' was not a list (got %s) - ignoring",
                type(propose_raw).__name__,
            )
            propose_raw = []

        kept = [t for t in detected_terms if t["term"].strip().lower() not in drop]
        existing = {t["matched_term"].strip().lower() for t in kept}
        normalized_source = normalize_text(source_text)

        proposed_hits = []
        skipped_propose = 0
        for item in propose_raw:
            if not isinstance(item, dict):
                skipped_propose += 1
                continue
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
        if skipped_propose:
            logger.warning(
                "curate_glossary_terms: skipped %d malformed 'propose' entries", skipped_propose
            )

        combined = kept + proposed_hits
        if len(combined) > _CURATION_TOTAL_BACKSTOP:
            logger.warning(
                "curate_glossary_terms: truncating %d total terms to backstop %d",
                len(combined), _CURATION_TOTAL_BACKSTOP,
            )
            overflow = len(combined) - _CURATION_TOTAL_BACKSTOP
            # Cut proposed_hits first -- entries that survived both the
            # dictionary lookup and the LLM's own drop-filter are higher-
            # confidence than a raw proposal (PRD 07 SS4.3). Only trim
            # kept's tail if proposed_hits alone can't absorb the overflow,
            # so the backstop is a true total cap on kept + proposed_hits,
            # never a no-op when kept alone already exceeds it.
            trim_from_proposed = min(overflow, len(proposed_hits))
            if trim_from_proposed:
                proposed_hits = proposed_hits[:-trim_from_proposed]
            remaining_overflow = overflow - trim_from_proposed
            if remaining_overflow:
                kept = kept[: len(kept) - remaining_overflow]
            combined = kept + proposed_hits
        return combined
    except Exception:
        logger.exception("curate_glossary_terms: curation call failed - keeping detected terms unfiltered")
        return detected_terms


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
