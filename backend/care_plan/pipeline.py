"""
care_plan/pipeline.py - The care_plan pipeline.

Deterministic term detection (AHRQ + Michigan + abbreviations) via JSON,
followed by four sequential LLM steps that ground, assemble+render,
review, and correct the note into a typed CarePlan.

Steps:
  1. read_note (deterministic; OCR + unitization, outside this generator)
  2. detect_terms (deterministic)
  3. ground
  4. assemble_and_render
  5. review
  6. correct (+ the deterministic close: citation-existence check, glossary re-detect)
"""

import copy
import difflib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Generator

from pydantic import ValidationError

from models.pipeline_events import (
    StepEvent,
    PipelineRunResult,
    PipelineStepError,
)

WrapStepFn = Callable[[int, str, Callable[[], Any]], Any]

from models.base import JsonModel
from models.care_plan import CarePlan
from models.ledger import Fact, FactCategory, Unit
from models.review import Correction, CoverageEntry, ReviewResult
from utils.llm import LLMClient
from utils.term_detection import (
    build_glossary_from_care_plan,      # 07 — re-detect terms from the final care plan
    curate_glossary_terms,               # 07
    detect_terms,
    format_abbreviations_for_prompt,
    format_medical_terms_for_prompt,
    format_substitution_candidates_for_prompt,
)
from utils.constants import Constants
from utils.text_normalization import normalize_text, normalize_with_offsets
from errors import SimplifyError, ErrorCode

_STEP = Constants.Pipeline.PIPELINE_STEPS

logger = logging.getLogger(__name__)


def _llm_schema(model_cls, exclude: set[str]) -> dict:
    """Generate a JSON schema from model_cls with the given field names excluded."""
    schema = copy.deepcopy(model_cls.model_json_schema())
    props = schema.get("properties", {})
    for field in exclude:
        props.pop(field, None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r not in exclude]
    return schema


class _GroundedFactRaw(JsonModel):
    """Shape of one array element straight from the grounding LLM, before
    its quote is verified and converted to char_start/char_end offsets.
    Never constructed from anything but raw LLM JSON, never returned from
    ground(), never passed to 04 or 05 -- purely an intermediate parsing
    target local to this module (PRD 03 §4.2/§9). Its four fields are
    exactly Fact's LLM-facing fields; Fact itself additionally carries
    `id` (assigned by code, §4.4) and `char_start`/`char_end` (computed
    by code from `quote`, §4.3) in place of `quote`."""

    category: FactCategory
    unit_id: int
    quote: str
    text: str


_GROUNDING_SCHEMA = json.dumps(
    {"type": "array", "items": _llm_schema(_GroundedFactRaw, exclude=set())},
    indent=2,
)


def _format_units_for_prompt(units: list[Unit]) -> str:
    """Render the unit list as the grounding prompt's numbered source text.
    Consecutive units sharing the same (file, page) are grouped under one
    header for readability -- the model still cites only the bracketed
    integer id; file/page headers are context, never a citable handle
    (brief brainstorm.v1.md §3.2: file/page are recovered by lookup, not
    asked of the model)."""
    lines: list[str] = []
    current_key = None
    for unit in units:
        key = (unit.file, unit.page)
        if key != current_key:
            lines.append(f"=== {unit.file}, page {unit.page} ===")
            current_key = key
        lines.append(f"[{unit.id}] {unit.text}")
    return "\n".join(lines)


def _is_verbatim_quote(quote: str, unit_text: str) -> bool:
    """Deterministic check (D1): is `quote` a substring of `unit_text`,
    tolerant of whitespace/case/accent noise from OCR (PRD 03 §4.5)? Reuses
    utils.text_normalization.normalize_text (already used for term-detection
    matching) rather than inventing a second normalization scheme. A quote
    whose NORMALIZED form is empty never counts as a match -- "" is
    trivially a substring of everything in Python, but carries no evidence.
    This is checked against the normalized form, not merely the raw form
    (a raw whitespace-only quote isn't the only way to get there): a quote
    made entirely of characters normalize_text strips (symbols, CJK,
    Cyrillic, etc.) is non-blank but still normalizes to "", and would
    otherwise pass this check vacuously."""
    normalized_quote = normalize_text(quote)
    if not normalized_quote:
        return False
    return normalized_quote in normalize_text(unit_text)


# Quote informativeness floor (D2, PRD 03 §9 -- resolves the prior [OPEN]
# item). Named constants, not bare literals, so the thresholds are tunable
# without hunting through the check's body -- matching this module's own
# precedent of naming its tunable numbers (Constants.Llm.MAX_TOKENS_LONG_FORM,
# Constants.Llm.TEMPERATURE_JSON) rather than inlining them.
_QUOTE_MIN_LENGTH = 12
_QUOTE_LONG_WORD_MIN_LENGTH = 7


def _is_informative_quote(quote: str) -> bool:
    """Deterministic check (D2): does `quote` carry enough clinical content
    to be worth citing, independent of whether it's verbatim? A quote
    passes if ANY of the following holds: it contains a digit (a dose, a
    lab value, a date); it contains a word of
    _QUOTE_LONG_WORD_MIN_LENGTH-plus characters (long words carry clinical
    content -- "metoprolol", "discontinued"); or it is
    _QUOTE_MIN_LENGTH-plus characters long outright. A bare character-count
    floor alone would reject legitimately short evidence ("40 mg",
    "warfarin") -- neither has 12 characters, but both are exactly the
    kind of short, information-dense fragment grounding is supposed to
    cite. Digits and long words are what carry clinical content in short
    fragments; the length floor exists only to catch a short quote that has
    neither (e.g. a single common short word)."""
    if any(ch.isdigit() for ch in quote):
        return True
    if any(len(word) >= _QUOTE_LONG_WORD_MIN_LENGTH for word in quote.split()):
        return True
    return len(quote) >= _QUOTE_MIN_LENGTH


def _locate_quote_offsets(quote: str, unit_text: str) -> tuple[int, int]:
    """Deterministically recover (char_start, char_end) -- Python slice
    offsets into `unit_text` -- for a `quote` already proven verbatim by
    `_is_verbatim_quote`. Must not be called on a (quote, unit_text) pair
    that hasn't already passed that check (see the AssertionError below).

    A naive `unit_text.find(quote)` is NOT sufficient: `_is_verbatim_quote`
    compares NORMALIZED strings (whitespace-collapsed, lowercased,
    accent-stripped -- utils.text_normalization.normalize_text), so a quote
    that legitimately passed that check can differ from `unit_text` in
    exactly those ways (OCR-doubled spaces collapsing to one, a case
    difference) and a raw, un-normalized `.find()` can come back -1 on a
    quote this function is guaranteed to be called with.

    Algorithm: normalize `unit_text` with
    `utils.text_normalization.normalize_with_offsets` (§4.2 imports; new
    function, see below), which returns the normalized string paired with
    a same-length list of raw-text (start, end) spans, one span per
    normalized character -- i.e. `spans[i]` is the `unit_text` slice that
    produced `normalized[i]`. Find the FIRST occurrence of
    `normalize_text(quote)` in that normalized string (`str.find`).
    `char_start` is `spans[match_start][0]`; `char_end` is
    `spans[match_start + len(normalized_quote) - 1][1]`.

    Edge cases (PRD 03 task's explicit callouts):
    - **Multiple occurrences of the same quote in one unit**: `str.find`
      returns the first. There is no principled way to prefer a later
      occurrence of literally the same normalized text -- both are equally
      valid evidence -- so "first" is simplest, deterministic, and stable
      across runs.
    - **Quote spanning normalized whitespace** (e.g. the raw text has a
      tab, a newline, or a run of several spaces where the quote has one):
      handled for free by the span-tracking design -- the single
      normalized space's span covers the ENTIRE raw whitespace run that
      collapsed into it (see `normalize_with_offsets` below), so any raw
      whitespace variation in the middle of a match is included in
      `unit_text[char_start:char_end]` by construction, not by a special
      case in this function.
    - **A raw, non-ASCII character inside the matched span that
      `normalize_text` drops entirely** (e.g. a stray degree sign):
      likewise handled for free -- `char_start`/`char_end` are the
      endpoints of the match, and everything raw between them, dropped
      characters included, is part of the Python slice by simple
      contiguity.

    Raises `AssertionError` if the normalized quote is not found -- this
    can only happen if `normalize_with_offsets` and `normalize_text` have
    drifted out of sync (see below for why that's structurally prevented,
    not just hoped for), since `_is_verbatim_quote` already proved the
    normalized quote is a substring of `normalize_text(unit_text)`. Also
    raises `AssertionError` if the normalized quote is empty -- `str.find`
    on an empty needle always returns 0 regardless of content, which would
    make `char_end` resolve to `spans[-1][1]` (the LAST span, not "one
    before a zero-length match") and silently return the entire unit's
    span; `_is_verbatim_quote` must already have rejected an empty-
    normalized quote before this function is ever called, so reaching this
    branch means that contract was violated."""
    normalized_unit, spans = normalize_with_offsets(unit_text)
    normalized_quote = normalize_text(quote)
    if not normalized_quote:
        raise AssertionError(
            "_locate_quote_offsets called with a quote that normalizes to "
            "the empty string -- caller must reject via _is_verbatim_quote "
            "before calling this function"
        )
    idx = normalized_unit.find(normalized_quote)
    if idx == -1:
        raise AssertionError(
            "quote passed the verbatim check but its normalized form was "
            "not found during offset recovery -- normalize_with_offsets "
            "and normalize_text have drifted apart"
        )
    char_start = spans[idx][0]
    char_end = spans[idx + len(normalized_quote) - 1][1]
    return char_start, char_end


def _verify_ledger(drafts: list[_GroundedFactRaw], units: list[Unit]) -> list[Fact]:
    """The three deterministic post-checks (D1/D2, brief §3.3 plus this
    PRD's §9 addition), no LLM involved. Drops -- rather than fails the
    step for -- any draft that cites a nonexistent unit, whose quote cannot
    be verified verbatim, or whose quote fails the informativeness floor;
    see §4.5 for why drop-and-log is the one policy governing all three.
    A draft that survives all three checks has its quote LOCATED (not
    copied) inside its unit's raw text (`_locate_quote_offsets`) and is
    turned into a `Fact` carrying `char_start`/`char_end` in place of
    `quote` -- the quote string itself never reaches the `Fact` model
    (PRD 01 §4.3, PRD 03 §9). Surviving facts are renumbered to a
    contiguous 1..N id sequence -- safe because nothing downstream has
    referenced these ids yet (this is the ledger's first construction),
    and it keeps the property Unit.id already has (PRD 02 §4.2): ids are
    stable, contiguous, and gap-free."""
    units_by_id = {u.id: u for u in units}
    verified: list[Fact] = []
    for draft in drafts:
        unit = units_by_id.get(draft.unit_id)
        if unit is None:
            logger.warning(
                "grounding: dropping fact citing unknown unit_id=%d (category=%s)",
                draft.unit_id, draft.category,
            )
            continue
        if not _is_verbatim_quote(draft.quote, unit.text):
            logger.warning(
                "grounding: dropping fact citing unit_id=%d -- quote not found "
                "verbatim in unit text (category=%s, extraction_method=%s)",
                draft.unit_id, draft.category, unit.extraction_method,
            )
            continue
        if not _is_informative_quote(draft.quote):
            logger.warning(
                "grounding: dropping fact citing unit_id=%d -- quote fails "
                "informativeness floor (category=%s, extraction_method=%s)",
                draft.unit_id, draft.category, unit.extraction_method,
            )
            continue
        char_start, char_end = _locate_quote_offsets(draft.quote, unit.text)
        verified.append(
            Fact(
                id=0,  # placeholder; real ids assigned below once drops are known
                category=draft.category,
                unit_id=draft.unit_id,
                char_start=char_start,
                char_end=char_end,
                text=draft.text,
            )
        )
    return [fact.model_copy(update={"id": i}) for i, fact in enumerate(verified, start=1)]


def _log_grounding_extraction_signal(facts: list[Fact], units_by_id: dict[int, Unit]) -> None:
    """One INFO-level, per-run aggregate of how many VERIFIED facts cite an
    OCR-extracted unit (PRD 12 SS4.8.2) -- log-only, mirrors 11's
    _log_coverage_summary in shape/placement (one aggregate call sitting
    next to the deterministic checks it summarizes, not inside them). No-op
    for an empty ledger -- ground() raises PIPELINE_VALIDATION_FAILED for
    that case immediately after this call anyway (SS4.5, unchanged), so
    logging a 0/0 aggregate right before a hard failure would be noise."""
    if not facts:
        return
    ocr = sum(1 for f in facts if units_by_id[f.unit_id].extraction_method == "ocr")
    total = len(facts)
    logger.info(
        "grounding: %d/%d verified facts cite an OCR-extracted unit",
        ocr, total,
        extra={"extraction_signal_facts": {
            "total": total,
            "ocr": ocr,
            "ocr_rate": ocr / total,
        }},
    )


_PROMPTS_DIR = Path(__file__).parent / "prompts"

_GROUND_PROMPT    = (_PROMPTS_DIR / "ground.txt").read_text(encoding="utf-8")
_ASSEMBLE_PROMPT = (_PROMPTS_DIR / "assemble_and_render.txt").read_text(encoding="utf-8")
_REVIEW_PROMPT = (_PROMPTS_DIR / "review.txt").read_text(encoding="utf-8")
_CORRECT_PROMPT = (_PROMPTS_DIR / "correct.txt").read_text(encoding="utf-8")
_STYLE_RULES = (_PROMPTS_DIR / "_style_rules.txt").read_text(encoding="utf-8")

_ASSEMBLE_SCHEMA = json.dumps(
    _llm_schema(CarePlan, exclude={"terms", "note"}),
    indent=2,
)

_REVIEW_SCHEMA = json.dumps(_llm_schema(ReviewResult, exclude=set()), indent=2)


# JSON path addressing scheme shared by review() and correct() (PRD 05 §4.2) --
# the machine-readable contract between the two LLM calls and their respective
# deterministic post-validation layers.
_PATH_SEGMENT_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)(\[(\d+)\])?")


def _resolve_path(root: dict, path: str) -> tuple[bool, Any]:
    """Walk `path` into `root` (a CarePlan.model_dump(mode="json") dict).
    Returns (found, value); found=False for an out-of-range index or an
    unknown field name -- the caller treats that as an invalid path to
    drop, never as a crash (PRD 05 §4.5)."""
    node: Any = root
    for segment in path.split("."):
        m = _PATH_SEGMENT_RE.fullmatch(segment)
        if not m:
            return False, None
        name, _, idx = m.groups()
        if not isinstance(node, dict) or name not in node:
            return False, None
        node = node[name]
        if idx is not None:
            i = int(idx)
            if not isinstance(node, list) or i >= len(node):
                return False, None
            node = node[i]
    return True, node

_FACT_CATEGORY_ORDER = (
    "reason_for_visit", "diagnosis", "medications", "tests",
    "procedures", "other", "follow_up", "warning_signs",
)


def _format_facts_for_prompt(facts: list[Fact]) -> str:
    """Render the ledger as the assembly prompt's fact list, grouped by
    category in the same fixed order as the MAPPING table in the prompt
    (PRD 04 §4.1), so the model sees its own checklist already partially
    applied -- mirrors _format_units_for_prompt's grouping (PRD 03 §4.3)."""
    by_category: dict[str, list[Fact]] = {}
    for fact in facts:
        by_category.setdefault(fact.category, []).append(fact)
    lines: list[str] = []
    for category in _FACT_CATEGORY_ORDER:
        for fact in by_category.get(category, []):
            lines.append(f"[{fact.id}] {category}: {fact.text}")
    return "\n".join(lines)


_ITEM_LIST_FIELDS = ("medications", "tests", "procedures", "other", "follow_up", "warning_signs")

# Content-richness floor (PRD 04 §9, resolving the prior [DEFERRED] item) --
# reuses 03's _is_informative_quote / _QUOTE_MIN_LENGTH /
# _QUOTE_LONG_WORD_MIN_LENGTH (PRD 03 §4.3) verbatim. Both already live in
# this same module (backend/care_plan/pipeline.py), so this is a same-file
# call, not an import -- 04 does not define a parallel set of constants.
_RICHNESS_CHECKS: tuple[tuple[str, str], ...] = (
    ("reason_for_visit", "description"),
    ("medications", "why"),
    ("tests", "why"),
    ("tests", "description"),
    ("procedures", "why"),
    ("other", "why"),
    ("other", "description"),
)


def _log_thin_fields(model: CarePlan) -> None:
    """Logs (never mutates or drops) a why/description field that fails
    03's _is_informative_quote floor (PRD 04 §9). Observability only: unlike
    NOT STATED, there is no fallback value to substitute for a field the
    model DID fill in, and dropping an otherwise-backed item over one thin
    field would remove genuine content the brief's "remove nothing"
    principle protects. "Not stated in your note." (25 chars) always clears
    the length rule on its own, so the sentinel is never flagged here."""
    for field, attr in _RICHNESS_CHECKS:
        for index, item in enumerate(getattr(model, field)):
            value = getattr(item, attr, "")
            if value and not _is_informative_quote(value):
                logger.warning(
                    "assemble_and_render: thin %s[%d].%s field (length=%d) -- "
                    "below the content-richness floor; not corrected or "
                    "dropped, logged for prompt-quality review",
                    field, index, attr, len(value),
                )
    for index, detail in enumerate(model.diagnosis.details):
        if detail.description and not _is_informative_quote(detail.description):
            logger.warning(
                "assemble_and_render: thin diagnosis.details[%d].description "
                "field (length=%d) -- below the content-richness floor",
                index, len(detail.description),
            )


def _verify_assembly(model: CarePlan, facts: list[Fact]) -> CarePlan:
    """Three deterministic, LLM-free guards on the assembled CarePlan (PRD 04
    §4.5), plus one LLM-free observability pass (content-richness, above).
    None of the three guards is fatal -- each corrects, filters, or drops in
    place and logs, matching 03's drop-and-continue policy for a fact that
    fails a per-item check (PRD 03 §4.5): a model deviation on one field, or
    one unbacked item, is not a reason to fail the whole step."""
    _log_thin_fields(model)
    updates: dict = {}

    if len(model.questions) > 3:
        logger.warning(
            "assemble_and_render: truncating %d questions to 3", len(model.questions)
        )
        updates["questions"] = model.questions[:3]

    valid_ids = {fact.id for fact in facts}

    bad_summary_ids = [i for i in model.summary_fact_ids if i not in valid_ids]
    if bad_summary_ids:
        logger.warning(
            "assemble_and_render: dropping summary_fact_ids not present in the "
            "ledger: %s", bad_summary_ids,
        )
        updates["summary_fact_ids"] = [i for i in model.summary_fact_ids if i in valid_ids]

    for field in _ITEM_LIST_FIELDS:
        items = getattr(model, field)
        kept = []
        changed = False
        for item in items:
            cited = [i for i in item.source_fact_ids if i in valid_ids]
            if not cited:
                logger.warning(
                    "assemble_and_render: dropping unbacked %s item -- "
                    "source_fact_ids=%r cited nothing in the ledger",
                    field, item.source_fact_ids,
                )
                changed = True
                continue
            if len(cited) != len(item.source_fact_ids):
                logger.warning(
                    "assemble_and_render: dropping hallucinated source_fact_ids "
                    "on a %s item: %s", field,
                    [i for i in item.source_fact_ids if i not in valid_ids],
                )
                item = item.model_copy(update={"source_fact_ids": cited})
                changed = True
            kept.append(item)
        if changed:
            updates[field] = kept

    result = model.model_copy(update=updates) if updates else model
    _check_numeric_parity(result, facts)   # PRD 10 R3 -- log-only, never mutates `result`
    return result


_UNIT_WORD_MAX_LENGTH = 15  # reasoned, not calibrated (PRD 10 §4.2): long enough
# for the longest realistic compound lab unit (mmol/L, mIU/mL), short enough
# that it can't silently swallow the start of the next clinical word if a
# unit is missing.

_UNIT_WORD_RE = rf"%|[A-Za-z][A-Za-z%/]{{0,{_UNIT_WORD_MAX_LENGTH - 1}}}"

# Reasoned, not calibrated (PRD 10 review): a closed vocabulary of clinical
# units/counts, used only to decide whether a slash pair ("4/12") is a bare
# date or a unit-bearing ratio (_BARE_DATE_RE) and to keep an arbitrary
# following word (a drug or person name) out of the numeric-parity log
# (_check_numeric_parity). Deliberately not the same thing as _UNIT_WORD_RE,
# which stays a permissive shape-only match for the tokenizer itself.
_KNOWN_UNIT_WORDS: frozenset[str] = frozenset({
    "%", "mg", "mcg", "µg", "ug", "g", "gm", "kg", "lb", "lbs", "oz",
    "ml", "l", "dl", "cc", "unit", "units", "iu", "meq", "mmol", "mmhg",
    "bpm", "mg/dl", "mmol/l", "g/dl", "mg/kg", "mcg/kg", "miu/ml", "u/l",
    "tablet", "tablets", "tab", "tabs", "pill", "pills", "capsule",
    "capsules", "cap", "caps", "puff", "puffs", "drop", "drops", "spray",
    "sprays", "patch", "patches", "cup", "cups", "tsp", "tbsp",
    "teaspoon", "teaspoons", "tablespoon", "tablespoons", "dose", "doses",
    "inch", "inches", "cm", "mm", "hour", "hours", "hr", "hrs", "minute",
    "minutes", "min", "day", "days", "week", "weeks", "month", "months",
    "year", "years",
})

_NUMBER_TOKEN_RE = re.compile(
    r"""
    (?P<num>
        \d{1,3}(?:,\d{3})+(?:\.\d+)?        # 1,000 or 1,000.5
      | \d+/\d+                             # fraction OR ratio/date shape: 1/2, 158/96, 4/12
      | \d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?   # range: 5-10, 5.5-10.2
      | \d+(?:\.\d+)?                       # plain integer or decimal
    )
    [ ]?
    (?P<unit>""" + _UNIT_WORD_RE + r""")?
    """,
    re.VERBOSE,
)


def _normalize_number(raw: str) -> str:
    """Canonicalize one bare number's own digits -- leading zeros, thousands
    separators, and a trailing decimal zero are formatting, not value, per
    the same principle assemble_and_render.txt's own worked example applies
    to unit spacing ("25mg" -> "25 mg" is a style change). Called on each
    component of a range/fraction separately, never on the whole thing."""
    raw = raw.replace(",", "")
    if "." in raw:
        integer_part, _, frac_part = raw.partition(".")
        frac_part = frac_part.rstrip("0")
        integer_part = integer_part.lstrip("0") or "0"
        return f"{integer_part}.{frac_part}" if frac_part else integer_part
    return raw.lstrip("0") or "0"


_TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

# A slash pair is a unit-bearing ratio, not a bare date, only when followed
# by a *known* unit word -- not just any word (PRD 10 review: the original
# `[A-Za-z%]` lookahead matched literally any following word, so "4/12 with
# cardiology" was misread as unit-bearing and never excluded as a date).
# "%" needs no trailing \b (it isn't a word character); every other known
# unit word must end at one, so "4/120mg" doesn't count "mg0" as "mg".
_bare_date_alpha_units = sorted((w for w in _KNOWN_UNIT_WORDS if w != "%"), key=len, reverse=True)
_BARE_DATE_UNIT_LOOKAHEAD = (
    r"(?:%|(?:" + "|".join(re.escape(w) for w in _bare_date_alpha_units) + r")\b)"
)
_BARE_DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b(?![ \t]*" + _BARE_DATE_UNIT_LOOKAHEAD + r")",
    re.IGNORECASE,
)
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
)
_WRITTEN_DATE_RE = re.compile(
    r"\b(?:" + "|".join(_MONTH_NAMES) + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _excluded_spans(text: str) -> list[tuple[int, int]]:
    """Date/time-shaped spans, dropped from BOTH sides of every numeric-
    parity comparison (PRD 10 §4.2's disclosed blind spot -- see there for
    why). _BARE_DATE_RE's negative lookahead is what lets a unit-bearing
    slash pair ("158/96 mmHg", "1/2 tablet") fall through untouched --
    only a slash pair followed by a *known* unit word (_KNOWN_UNIT_WORDS),
    not just any following word, is kept; every other slash pair is excluded
    as a bare date. Any number token merely overlapping one of these spans
    is dropped, not just one fully contained in it -- a trailing "AM"/"PM"/
    word captured as that token's unit could otherwise leak the minutes out
    of a time-of-day span."""
    spans = [m.span() for m in _TIME_OF_DAY_RE.finditer(text)]
    spans += [m.span() for m in _BARE_DATE_RE.finditer(text)]
    spans += [m.span() for m in _WRITTEN_DATE_RE.finditer(text)]
    return spans


def _extract_number_tokens(text: str) -> set[tuple[str, str]]:
    """Tokenize every number-with-optional-unit out of `text` into a set of
    (normalized_number, normalized_unit) pairs; unit is "" when none is
    attached. Excludes date/time-shaped spans entirely (see above); a number
    token merely overlapping such a span is dropped, not just one fully
    contained in it."""
    excluded = _excluded_spans(text)
    tokens: set[tuple[str, str]] = set()
    for m in _NUMBER_TOKEN_RE.finditer(text):
        if any(m.start() < e and m.end() > s for s, e in excluded):
            continue
        num, unit = m.group("num"), (m.group("unit") or "").lower()
        if "/" in num:
            num_norm = "/".join(_normalize_number(p) for p in num.split("/"))
        elif "-" in num:
            num_norm = "-".join(_normalize_number(p.strip()) for p in num.split("-"))
        else:
            num_norm = _normalize_number(num)
        tokens.add((num_norm, unit))
    return tokens


_NUMERIC_PARITY_FIELDS: dict[str, tuple[str, ...]] = {
    "medications": ("title", "plain_name", "why", "dosage", "frequency",
                     "timing", "duration", "instructions",
                     "side_effects_to_watch", "change"),
    "tests": ("title", "plain_name", "why", "description", "preparation"),
    "procedures": ("title", "plain_name", "why", "what_to_expect", "timeframe"),
    "other": ("title", "why", "description", "frequency", "duration"),  # steps[] handled separately
    "follow_up": ("time_frame", "description"),
    "warning_signs": ("symptom", "what_it_might_mean", "what_to_do", "related_to"),
}


def _check_numeric_parity(model: CarePlan, facts: list[Fact]) -> None:
    """R3 (PRD 10 §4.3/§4.4): log-only, model-free check that every number
    a rendered field states was present in at least one fact the item
    cites. Never mutates or drops anything -- unlike the citation-existence
    guards above it, a numeric mismatch has no safe deterministic repair
    (which side is right is exactly the judgement call this check cannot
    make), so logging is this PRD's entire, LOCKED contract."""
    facts_by_id = {f.id: f for f in facts}
    mismatches = 0

    def _backing_tokens(fact_ids: list[int]) -> set[tuple[str, str]]:
        tokens: set[tuple[str, str]] = set()
        for fid in fact_ids:
            fact = facts_by_id.get(fid)
            if fact is not None:
                tokens |= _extract_number_tokens(fact.text)
        return tokens

    def _check_field(field: str, index: int | str, attr: str, value: str,
                      backing: set[tuple[str, str]], num_cited: int) -> int:
        if not value:
            return 0
        backing_numbers = {num for num, _unit in backing}
        found = 0
        for num, unit in _extract_number_tokens(value):
            if (num, unit) in backing:
                continue
            found += 1
            if num in backing_numbers:
                # PHI/PII guard (PRD 10 review): `unit` is whatever word the
                # tokenizer found after the number -- for an unrecognized
                # word that can be a drug or person name, not a unit at all.
                # Only log it when it's a known unit (or empty).
                safe_unit = unit if unit == "" or unit in _KNOWN_UNIT_WORDS else "<non-unit word>"
                logger.warning(
                    "assemble_and_render: numeric parity -- %s[%s].%s has a "
                    "value matching a cited fact's number but with a "
                    "different or missing unit (unit=%r)",
                    field, index, attr, safe_unit,
                )
            else:
                logger.warning(
                    "assemble_and_render: numeric parity -- %s[%s].%s "
                    "contains a number not found in any of its %d cited "
                    "fact(s)", field, index, attr, num_cited,
                )
        return found

    for field, attrs in _NUMERIC_PARITY_FIELDS.items():
        for index, item in enumerate(getattr(model, field)):
            backing = _backing_tokens(item.source_fact_ids)
            num_cited = len(item.source_fact_ids)
            for attr in attrs:
                mismatches += _check_field(field, index, attr, getattr(item, attr, ""), backing, num_cited)
            if field == "other":
                for step_idx, step in enumerate(item.steps):
                    mismatches += _check_field(field, index, f"steps[{step_idx}]", step, backing, num_cited)

    if model.summary:
        mismatches += _check_field("summary", "-", "summary", model.summary,
                                    _backing_tokens(model.summary_fact_ids),
                                    len(model.summary_fact_ids))

    if mismatches:
        logger.warning(
            "assemble_and_render: numeric parity check flagged %d mismatch(es) "
            "in this care plan", mismatches,
        )


_WHY_PATH_RE = re.compile(r"^(medications|tests|procedures|other)\[\d+\]\.why$")


def _targets_removed_item(path: str, removed_items: set[str]) -> bool:
    """True if `path` names one of the `removed_items` paths itself, or a
    field nested (at any depth) under one -- i.e. a `correct`/`not_stated`
    targeting a field of an item some other correction already `remove`s
    (PRD 05 §4.5's contradiction guard: remove wins).

    Removed-item paths are full dotted prefixes, not necessarily a single
    top-level `array[N]` segment -- `diagnosis.details[0]` is as valid a
    removed item as `medications[0]`. A path is "under" a removed item
    only when it continues with a `.` or `[` boundary right after the
    removed prefix (`diagnosis.details[1]` must NOT match a removed
    `diagnosis.details[10]`, nor vice versa -- plain prefix matching
    would conflate them)."""
    return any(
        path == removed or path.startswith(removed + ".") or path.startswith(removed + "[")
        for removed in removed_items
    )


def _sanitize_review_result(result: ReviewResult, care_plan: CarePlan, facts: list[Fact]) -> ReviewResult:
    """Deterministic post-validation of a reviewer's raw output (PRD 05
    §4.5): drop-and-log, never fail the step, mirroring 03's per-fact
    policy. Drops a correction whose path doesn't resolve against
    `care_plan`, a `not_stated` outside the four scoped `why` fields, or a
    `correct` with no value; lets `remove` win over a `correct`/`not_stated`
    targeting the same array item; and fills in a `present=False` coverage
    entry for any ledger fact the reviewer's coverage walk omitted, dropping
    any coverage entry citing a fact_id not in the ledger."""
    plan_dict = care_plan.model_dump(mode="json")
    clean: list[Correction] = []
    for c in result.corrections:
        found, _ = _resolve_path(plan_dict, c.path)
        if not found:
            logger.warning("review: dropping correction with unresolvable path %r", c.path)
            continue
        if c.op == "not_stated" and not _WHY_PATH_RE.match(c.path):
            logger.warning("review: dropping not_stated outside the four why fields: %r", c.path)
            continue
        if c.op == "correct" and not c.value:
            logger.warning("review: dropping correct with no value: %r", c.path)
            continue
        clean.append(c)
    # remove wins over correct/not_stated on the same array item (contradiction guard)
    removed_items = {c.path for c in clean if c.op == "remove"}
    clean = [c for c in clean if c.op == "remove" or not _targets_removed_item(c.path, removed_items)]

    fact_ids = {f.id for f in facts}
    coverage = [e for e in result.coverage if e.fact_id in fact_ids]
    missing = fact_ids - {e.fact_id for e in coverage}
    if missing:
        logger.warning("review: coverage omitted %d fact id(s); treating as not-present", len(missing))
        coverage += [CoverageEntry(fact_id=i, present=False) for i in missing]

    return result.model_copy(update={"corrections": clean, "coverage": coverage})


def _format_corrections_for_prompt(corrections: list[Correction]) -> str:
    """Render each correction as one JSON line for the correct.txt prompt's
    CORRECTIONS block (PRD 05 §4.6). No PRD-cited exact text -- any correct,
    readable one-line-per-correction JSON rendering satisfies this."""
    lines = []
    for c in corrections:
        obj = {"op": c.op, "path": c.path}
        if c.value is not None:
            obj["value"] = c.value
        lines.append(json.dumps(obj))
    return "\n".join(lines)


# The corrector-diff check (PRD 05 §4.6) -- the brief's named mitigation for
# the corrector's soft spot: assert nothing outside the named corrections
# (plus a bounded PII sweep) changed.
_PII_ELIGIBLE_FIELDS = {
    "summary", "why", "description", "what_it_means_for_you", "instructions",
    "what_to_expect", "what_it_might_mean", "related_to",
    "changed_since_last_visit", "side_effects_to_watch", "preparation",
    "steps", "questions", "low_priority",
}
_MAX_PII_TOKEN_DELTA = 4


def _looks_like_pii_substitution(old: str, new: str) -> bool:
    """True if old->new plausibly represents ONLY a name/facility swap.
    Word-level SequenceMatcher opcodes; count non-'equal' tokens on either
    side. A targeted "Doctor Alok Singh" -> "your doctor" swap stays under
    the threshold; a resummarized sentence does not."""
    old_w, new_w = old.split(), new.split()
    ops = difflib.SequenceMatcher(a=old_w, b=new_w).get_opcodes()
    changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops if tag != "equal")
    return changed <= _MAX_PII_TOKEN_DELTA


def _split_array_path(path: str) -> tuple[str, int]:
    """"warning_signs[3]" -> ("warning_signs", 3); "diagnosis.details[0]" ->
    ("diagnosis.details", 0) -- the dotted array path (at whatever nesting
    depth `path` addresses -- anything `_resolve_path` accepts, per PRD 05
    §4.2 rule 1) paired with the removed index. Used only by the diff check
    to convert a `remove` correction's path into this pair (PRD 05 §4.6).
    Splits on the LAST "." so a dotted prefix (if any) is preserved rather
    than discarded -- fixes a prior bug where this only handled an
    undotted, top-level array path and crashed with AttributeError on
    anything dotted. Raises SimplifyError (PIPELINE_VALIDATION_FAILED),
    rather than crashing, if `path`'s last segment carries no `[N]` index --
    a malformed `remove` target the reviewer's vocabulary (§4.2 rule 3)
    never legitimately produces (every `remove` but "summary", which is
    special-cased by the caller before this is ever called, must name an
    array item), but that a corrupted/adversarial correction list could."""
    head, _, last = path.rpartition(".")
    m = _PATH_SEGMENT_RE.fullmatch(last)
    if not m or m.group(3) is None:
        raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED,
            detail=f"remove correction does not address an array item: {path!r}")
    array_path = f"{head}.{m.group(1)}" if head else m.group(1)
    return array_path, int(m.group(3))


def _diff_item(before_v, after_v, path: str, named: set[str], removed_by_array: dict[str, set[int]]) -> None:
    """Recursively compare one node of the CarePlan tree at `path` (a dict,
    a list, or a scalar leaf), raising on any change that is neither a
    named correction target, a bounded PII swap on a `_PII_ELIGIBLE_FIELDS`
    leaf, nor accounted for by a `remove` correction's effect on the array
    at `path` (PRD 05 §4.2, §4.6). Recurses through dicts and lists
    uniformly at ANY nesting depth -- every path `_resolve_path` can
    address (`medications[N].dosage`, `diagnosis.details[N].description`,
    `other[N].steps[M]`, ...) is matched exactly at its own leaf, never
    only one dict level deep, so a sibling leaf elsewhere in the same
    nested list is still caught. Containers (dicts/lists) are always
    recursed into structurally -- never shortcut on outer equality -- so a
    `remove` expected somewhere further down (e.g. `diagnosis.details`
    unchanged in length because the corrector silently ignored the
    correction) is still caught even when an ancestor container happens to
    compare equal overall; the equality shortcut only applies at an actual
    scalar leaf, where no removal bookkeeping ever applies."""
    if isinstance(before_v, list) and isinstance(after_v, list):
        removed = removed_by_array.get(path, set())
        expected_survivors = [i for i in range(len(before_v)) if i not in removed]
        if len(after_v) != len(expected_survivors):
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail=f"{path}: expected {len(expected_survivors)} items after correction, got {len(after_v)}")
        for k, orig_idx in enumerate(expected_survivors):
            _diff_item(before_v[orig_idx], after_v[k], f"{path}[{orig_idx}]", named, removed_by_array)
        return
    if isinstance(before_v, dict) and isinstance(after_v, dict):
        for key, bv in before_v.items():
            _diff_item(bv, after_v[key], f"{path}.{key}", named, removed_by_array)
        return
    if before_v == after_v:
        return
    if path in named:
        return
    field_name = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if isinstance(before_v, str) and isinstance(after_v, str) and \
       field_name in _PII_ELIGIBLE_FIELDS and _looks_like_pii_substitution(before_v, after_v):
        return
    raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED,
        detail=f"corrector changed unnamed, non-PII field: {path}")


def _verify_correction_diff(before: CarePlan, after: CarePlan, corrections: list[Correction]) -> None:
    """The corrector-diff check (PRD 05 §4.6): position-based, not content-
    aligned -- correct.txt requires order preservation, so a `remove`
    correction's effect on an array's length is accounted for by tracking
    which original indices survive, rather than by re-aligning content.
    `removed_by_array` is keyed by the full dotted array path at whatever
    depth a `remove` correction addresses (`"warning_signs"`, but also
    `"diagnosis.details"` -- PRD 05 §4.2 rule 1's paths are not restricted
    to one dict level), so `_diff_item`'s survivor accounting applies
    uniformly at every nesting depth, not just at the top level. Raises
    SimplifyError(PIPELINE_VALIDATION_FAILED) on any violation; the caller
    (06's iter_steps) is the one that falls back to the pre-correction
    care_plan (§4.8) -- this function never falls back itself."""
    before_d, after_d = before.model_dump(mode="json"), after.model_dump(mode="json")
    named = {c.path for c in corrections}
    removed_by_array: dict[str, set[int]] = {}   # e.g. "warning_signs" -> {1, 3}
    for c in corrections:
        if c.op == "remove" and c.path != "summary":
            arr, idx = _split_array_path(c.path)
            removed_by_array.setdefault(arr, set()).add(idx)

    for field in CarePlan.model_fields:
        _diff_item(before_d[field], after_d[field], field, named, removed_by_array)


def _validation_error_detail(e: ValidationError) -> str:
    """PHI-free detail string for a Pydantic ValidationError on LLM
    structured output. `str(e)` (and its `.msg`/`.input_value` fields)
    embeds the actual invalid value pydantic rejected -- for these four
    call sites that value is patient-derived clinical text pulled
    straight from the LLM's structured response, so it must never reach
    `SimplifyError.detail` (which flows into Firestore `error_data.details`,
    a field the frontend's live listener reads). Uses only each error's
    `loc` (the field path) and `type` (the validator name) -- structural
    metadata about *where* validation failed, never the value itself."""
    return "; ".join(
        f"{'.'.join(map(str, err['loc']))}: {err['type']}" for err in e.errors()
    )


class CarePlanPipeline:
    """Care plan pipeline with deterministic term detection."""

    def __init__(self):
        self._llm = LLMClient()

    def _generate_text(
        self,
        prompt: str,
        temperature: float = Constants.Llm.TEMPERATURE_TEXT,
        max_tokens: int = Constants.Llm.MAX_TOKENS,
    ) -> str:
        # Delegate to shared LLM client.
        return self._llm.generate_text(prompt, temperature=temperature, max_tokens=max_tokens)

    def _generate_json(
        self,
        prompt: str,
        temperature: float = Constants.Llm.TEMPERATURE_JSON,
        max_tokens: int = Constants.Llm.MAX_TOKENS,
    ) -> dict | list:
        # Delegate to shared LLM client (includes fence-stripping and JSON parsing).
        return self._llm.generate_json(prompt, temperature=temperature, max_tokens=max_tokens)

    def ground(self, units: list[Unit], abbreviations: list[dict]) -> list[Fact]:
        """Grounding: the LLM call that extracts an evidence-linked ledger of
        atomic facts from the deterministic unit list, before any rewriting
        or structuring happens (brief §2.5, §3.3). Raises SimplifyError on
        any unrecoverable failure -- this method does not catch its own
        exceptions; iter_steps' fatal-step wrapping is 06's to wire (PRD 03
        §4.5).

        Long-form token budget: grounding output size scales with the
        number of facts in the whole document (potentially the largest
        single LLM output in the pipeline, now that it runs before any
        content is dropped or condensed), so it uses MAX_TOKENS_LONG_FORM.
        """
        abbrev_block = format_abbreviations_for_prompt(abbreviations)
        units_block = _format_units_for_prompt(units)
        prompt = _GROUND_PROMPT.format(
            schema=_GROUNDING_SCHEMA,
            abbrev_block=abbrev_block,
            units_block=units_block,
        )
        raw = self._generate_json(
            prompt,
            temperature=Constants.Llm.TEMPERATURE_JSON,
            max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM,
        )
        if not isinstance(raw, list):
            raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected list, got {type(raw)}")

        drafts: list[_GroundedFactRaw] = []
        for idx, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise SimplifyError(
                    ErrorCode.PIPELINE_VALIDATION_FAILED,
                    detail=f"grounding item {idx} is not a JSON object",
                )
            try:
                drafts.append(_GroundedFactRaw.model_validate(item))
            except ValidationError as e:
                raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=_validation_error_detail(e), original=e)

        verified = _verify_ledger(drafts, units)
        _log_grounding_extraction_signal(verified, {u.id: u for u in units})
        if not verified:
            raise SimplifyError(
                ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail="grounding produced zero verifiable facts",
            )
        return verified

    def assemble_and_render(
        self,
        facts: list[Fact],
        substitution_candidates: list[dict],
        preserve_and_define_terms: list[dict],
        abbreviations: list[dict],
    ) -> CarePlan:
        """Assembly + render: the single LLM call that maps the verified
        fact ledger into a typed CarePlan, splitting and plain-language-
        rendering each field (brief §2.5, §3.4). It replaces the former
        multi-stage whole-document rewriting flow.

        Raises SimplifyError on any unrecoverable failure -- this method
        does not catch its own exceptions; iter_steps' fatal-step wrapping
        is 06's to wire (PRD 04 §4.5).
        """
        if not facts:
            raise SimplifyError(
                ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail="assemble_and_render received an empty fact ledger",
            )

        prompt = _ASSEMBLE_PROMPT.format(
            schema=_ASSEMBLE_SCHEMA,
            facts_block=_format_facts_for_prompt(facts),
            style_rules=_STYLE_RULES,
            sub_block=format_substitution_candidates_for_prompt(substitution_candidates),
            medical_block=format_medical_terms_for_prompt(preserve_and_define_terms),
            abbrev_block=format_abbreviations_for_prompt(abbreviations),
        )
        raw = self._generate_json(
            prompt,
            temperature=Constants.Llm.TEMPERATURE_JSON,
            max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM,
        )
        if not isinstance(raw, dict):
            raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")

        try:
            model = CarePlan.model_validate(raw)
        except ValidationError as e:
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=_validation_error_detail(e), original=e)

        return _verify_assembly(model, facts)

    def review(self, facts: list[Fact], care_plan: CarePlan) -> ReviewResult:
        """Review: one LLM call producing field-level corrections and a
        per-fact coverage walk (brief §3.5). Never mutates care_plan. Raises
        SimplifyError on unrecoverable failure -- iter_steps' non-fatal
        wrapping is 06's to wire (PRD 05 §4.8: review is non-fatal)."""
        prompt = _REVIEW_PROMPT.format(
            schema=_REVIEW_SCHEMA,
            facts_block=_format_facts_for_prompt(facts),   # reuses 04's helper (PRD 04 §4.3)
            care_plan_block=json.dumps(care_plan.model_dump(mode="json"), indent=2),
        )
        raw = self._generate_json(
            prompt,
            temperature=Constants.Llm.TEMPERATURE_JSON,
            max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM,
        )
        if not isinstance(raw, dict):
            raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")
        try:
            result = ReviewResult.model_validate(raw)
        except ValidationError as e:
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=_validation_error_detail(e), original=e)

        return _sanitize_review_result(result, care_plan, facts)

    def correct(
        self,
        care_plan: CarePlan,
        corrections: list[Correction],
        substitution_candidates: list[dict],
        preserve_and_define_terms: list[dict],
        abbreviations: list[dict],
    ) -> CarePlan:
        """Correct: applies exactly the named corrections plus a PII sweep
        (brief §3.6). Raises SimplifyError on any failure, INCLUDING a diff-
        check rejection -- correct() itself never "falls back"; the caller
        (06's iter_steps) is the one that catches this and substitutes
        `care_plan` unmodified (PRD 05 §4.8: correct is non-fatal)."""
        if not corrections:
            return care_plan

        prompt = _CORRECT_PROMPT.format(
            corrections_block=_format_corrections_for_prompt(corrections),
            style_rules=_STYLE_RULES,
            care_plan_block=json.dumps(care_plan.model_dump(mode="json"), indent=2),
            schema=_ASSEMBLE_SCHEMA,   # correct() returns a full CarePlan, same shape as assemble's output (PRD 04 §4.3)
        )
        raw = self._generate_json(
            prompt,
            temperature=Constants.Llm.TEMPERATURE_JSON,
            max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM,
        )
        if not isinstance(raw, dict):
            raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")
        try:
            corrected = CarePlan.model_validate(raw)
        except ValidationError as e:
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=_validation_error_detail(e), original=e)

        _verify_correction_diff(care_plan, corrected, corrections)   # raises on violation
        return corrected

    def iter_steps(
        self,
        text: str,
        units: list[Unit],
        wrap_step: WrapStepFn | None = None,
    ) -> Generator[StepEvent | PipelineRunResult | PipelineStepError, None, None]:
        """
        Run the full pipeline, yielding step progress and the final result.

        Yields StepEvent(step, "active") before each step and StepEvent(step, "done")
        after each step. On success, yields a single PipelineRunResult. On an
        unrecoverable step failure, yields PipelineStepError and returns.

        Args:
            text:      Plain text to process (still needed for deterministic term
                       detection, glossary curation's "propose" job, and grounding's
                       abbreviation block).
            units:     The deterministic, per-line evidence units ground() cites into.
            wrap_step: Optional hook called as wrap_step(step_num, label, fn) and
                       must return fn(). The adapter uses this to attach Markers,
                       SimplifyContext, and tracing spans without the pipeline importing
                       Flask or g. If None, steps are called directly.
        """

        def _call(step: int, label: str, fn: Callable[[], Any]) -> Any:
            if wrap_step is not None:
                return wrap_step(step, label, fn)
            return fn()

        # Step 2: term detection (deterministic, no LLM) — unchanged.
        yield StepEvent(step=_STEP.DETECT_TERMS.number, status="active", label=_STEP.DETECT_TERMS.label)
        try:
            term_data = _call(_STEP.DETECT_TERMS.number, _STEP.DETECT_TERMS.label, lambda: detect_terms(text))
        except Exception:
            logger.exception("pipeline: term detection failed — continuing with empty terms")
            term_data = {"substitution_candidates": [], "preserve_and_define_terms": [], "abbreviations": []}
        yield StepEvent(step=_STEP.DETECT_TERMS.number, status="done", label=_STEP.DETECT_TERMS.label)

        # Glossary curation starts here, on ITS OWN background thread, running
        # alongside everything below (brief §3.1/§3.8) — see PRD §4.3 for why the
        # LLMClient is constructed eagerly, on THIS thread, before submit().
        try:
            glossary_llm = LLMClient()
        except Exception:
            logger.exception("pipeline: could not construct glossary-curation LLM client")
            glossary_llm = None
        glossary_executor = ThreadPoolExecutor(max_workers=1)
        glossary_future = glossary_executor.submit(
            curate_glossary_terms, text, term_data["preserve_and_define_terms"], glossary_llm,
        )

        try:
            # Step 3: grounding (LLM, FATAL — no fallback exists, PRD 03 §4.6)
            yield StepEvent(step=_STEP.GROUND.number, status="active", label=_STEP.GROUND.label)
            try:
                facts = _call(_STEP.GROUND.number, _STEP.GROUND.label,
                               lambda: self.ground(units, term_data["abbreviations"]))
            except Exception as exc:
                logger.exception("pipeline: grounding failed")
                yield PipelineStepError(step=_STEP.GROUND.number, exc=exc)
                return
            yield StepEvent(step=_STEP.GROUND.number, status="done", label=_STEP.GROUND.label)

            # Step 4: assemble + render (LLM, FATAL — PRD 04 §4.5)
            yield StepEvent(step=_STEP.ASSEMBLE_AND_RENDER.number, status="active", label=_STEP.ASSEMBLE_AND_RENDER.label)
            try:
                care_plan = _call(
                    _STEP.ASSEMBLE_AND_RENDER.number, _STEP.ASSEMBLE_AND_RENDER.label,
                    lambda: self.assemble_and_render(
                        facts, term_data["substitution_candidates"],
                        term_data["preserve_and_define_terms"], term_data["abbreviations"],
                    ),
                )
            except Exception as exc:
                logger.exception("pipeline: assemble_and_render failed")
                yield PipelineStepError(step=_STEP.ASSEMBLE_AND_RENDER.number, exc=exc)
                return
            yield StepEvent(step=_STEP.ASSEMBLE_AND_RENDER.number, status="done", label=_STEP.ASSEMBLE_AND_RENDER.label)

            # Step 5: review (LLM, NON-FATAL — PRD 05 §4.8: a fidelity nit must
            # never cost the user their whole result)
            yield StepEvent(step=_STEP.REVIEW.number, status="active", label=_STEP.REVIEW.label)
            try:
                review_result = _call(_STEP.REVIEW.number, _STEP.REVIEW.label,
                                       lambda: self.review(facts, care_plan))
            except Exception:
                logger.exception("pipeline: review failed — skipping correction, shipping assembly's output")
                review_result = None
            yield StepEvent(step=_STEP.REVIEW.number, status="done", label=_STEP.REVIEW.label)

            # Step 6: correct (LLM, NON-FATAL) + the deterministic close.
            # Bundled under one progress-bar step deliberately (PRD §4.1) — none of
            # what happens here is something a patient needs itemized.
            yield StepEvent(step=_STEP.CORRECT.number, status="active", label=_STEP.CORRECT.label)
            if review_result and review_result.corrections:
                try:
                    care_plan = _call(
                        _STEP.CORRECT.number, _STEP.CORRECT.label,
                        lambda: self.correct(
                            care_plan, review_result.corrections,
                            term_data["substitution_candidates"],
                            term_data["preserve_and_define_terms"], term_data["abbreviations"],
                        ),
                    )
                except Exception:
                    logger.exception("pipeline: correct failed or was rejected by the diff check — "
                                      "falling back to the pre-correction care plan")
                    # care_plan is left exactly as assemble_and_render returned it.

            # Deterministic close (PRD §4.10): glossary re-detection is the only
            # step left here. The citation-existence check that used to need
            # ordering against it — the direct replacement for the deleted
            # close_coverage — is already enforced by 04, inline inside
            # assemble_and_render, before review()/correct() even run (PRD 04
            # §4.4). There is no separate call for iter_steps to make.
            try:
                curated_terms = glossary_future.result(
                    timeout=Constants.Deadlines.GLOSSARY_CURATION_TIMEOUT_S
                )
            except Exception:
                logger.exception("pipeline: glossary curation did not finish in time — using uncurated terms")
                curated_terms = term_data["preserve_and_define_terms"]

            glossary = build_glossary_from_care_plan(care_plan, curated_terms)
            care_plan = care_plan.model_copy(update={"terms": glossary})

            yield StepEvent(step=_STEP.CORRECT.number, status="done", label=_STEP.CORRECT.label)
        finally:
            # Always runs — early `return` on a fatal step, an exception
            # propagating out, or normal completion all hit this. wait=False:
            # if curation is still running past its own timeout above, let it
            # finish in the background rather than block job completion on it
            # a second time (PRD §4.3).
            glossary_executor.shutdown(wait=False)

        yield PipelineRunResult(care_plan=care_plan, term_data=term_data, raw_text=text)

    def run(self, text: str, units: list[Unit]) -> CarePlan:
        """Run the full pipeline without instrumentation. Used in tests and batch pre-checks."""
        for event in self.iter_steps(text, units):
            if isinstance(event, PipelineRunResult):
                return event.care_plan
            if isinstance(event, PipelineStepError):
                raise event.exc
        raise RuntimeError("iter_steps completed without yielding a result")
