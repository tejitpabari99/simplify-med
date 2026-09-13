"""
care_plan/pipeline.py - The care_plan pipeline.

Deterministic term detection (AHRQ + Michigan + abbreviations) via JSON,
followed by three LLM steps that simplify, clarify, and structure the note
into a typed CarePlan.

Steps:
  1. detect_terms
  2. simplify_language
  3. clarify_and_action
  4. structure_document
  5. postprocess
"""

import copy
import json
import logging
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
from utils.llm import LLMClient
from utils.term_detection import (
    build_glossary_from_simplified_text,
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


_STRUCTURING_SCHEMA = json.dumps(
    _llm_schema(CarePlan, exclude={"terms", "raw", "note"}),
    indent=2,
)


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
    matching) rather than inventing a second normalization scheme. A blank
    or whitespace-only quote never counts as a match -- "" is trivially a
    substring of everything in Python, but carries no evidence."""
    if not quote.strip():
        return False
    return normalize_text(quote) in normalize_text(unit_text)


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
    normalized quote is a substring of `normalize_text(unit_text)`."""
    normalized_unit, spans = normalize_with_offsets(unit_text)
    normalized_quote = normalize_text(quote)
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
                "verbatim in unit text (category=%s)", draft.unit_id, draft.category,
            )
            continue
        if not _is_informative_quote(draft.quote):
            logger.warning(
                "grounding: dropping fact citing unit_id=%d -- quote fails "
                "informativeness floor (category=%s)", draft.unit_id, draft.category,
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


_PROMPTS_DIR = Path(__file__).parent / "prompts"

_SIMPLIFY_PROMPT  = (_PROMPTS_DIR / "simplify_language.txt").read_text(encoding="utf-8")
_CLARIFY_PROMPT   = (_PROMPTS_DIR / "clarify_and_action.txt").read_text(encoding="utf-8")
_STRUCTURE_PROMPT = (_PROMPTS_DIR / "structure_note.txt").read_text(encoding="utf-8")
_GROUND_PROMPT    = (_PROMPTS_DIR / "ground.txt").read_text(encoding="utf-8")


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

    def simplify_language_with_term_plan(
        self,
        text: str,
        substitution_candidates: list[dict],
        preserve_and_define_terms: list[dict],
        abbreviations: list[dict],
    ) -> str:
        # Pre-format deterministic term detections into compact prompt sections.
        sub_block = format_substitution_candidates_for_prompt(substitution_candidates)
        medical_block = format_medical_terms_for_prompt(preserve_and_define_terms)
        abbrev_block = format_abbreviations_for_prompt(abbreviations)

        prompt = _SIMPLIFY_PROMPT.format(
            sub_block=sub_block,
            medical_block=medical_block,
            abbrev_block=abbrev_block,
            text=text,
        )
        return self._generate_text(prompt, temperature=Constants.Llm.TEMPERATURE_TEXT, max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM)

    def clarify_and_action(self, text: str, abbreviations: list[dict] | None = None) -> str:
        abbreviation_section = ""
        if abbreviations:
            abbrev_list = "\n".join(
                f"- \"{a['term']}\" -> \"{a['expansion']}\""
                for a in abbreviations[:30]
            )
            abbreviation_section = (
                f"\nIf any of these abbreviations remain in the text, expand them:\n{abbrev_list}\n"
            )
        prompt = _CLARIFY_PROMPT.format(
            abbreviation_section=abbreviation_section,
            text=text,
        )
        return self._generate_text(prompt, temperature=Constants.Llm.TEMPERATURE_JSON, max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM)

    def structure_appointment_note(self, text: str) -> dict:
        # Long-form budget: this step emits the full structured care-plan JSON
        # (medications, tests, warning signs, etc. for the whole document), which
        # can easily exceed the default 8192-token cap on anything longer than a
        # short note. It is also the LAST LLM step, so hitting the cap here means
        # every earlier step already ran to completion before the user sees a
        # failure — use the same long-form budget as the other prose-generating
        # steps so a merely-longer (not actually huge) document doesn't fail late.
        prompt = _STRUCTURE_PROMPT.format(schema=_STRUCTURING_SCHEMA, text=text)
        raw = self._generate_json(prompt, temperature=Constants.Llm.TEMPERATURE_JSON, max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM)
        if not isinstance(raw, dict):
            raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")

        try:
            model = CarePlan.model_validate(raw)
        except ValidationError as e:
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

        return model.model_dump(mode="json", exclude={"terms", "raw"})

    def iter_steps(
        self,
        text: str,
        wrap_step: WrapStepFn | None = None,
    ) -> Generator[StepEvent | PipelineRunResult | PipelineStepError, None, None]:
        """
        Run the full pipeline, yielding step progress and the final result.

        Yields StepEvent(step, "active") before each step and StepEvent(step, "done")
        after each step. On success, yields a single PipelineRunResult. On an
        unrecoverable step failure, yields PipelineStepError and returns.

        Args:
            text:      Plain text to process.
            wrap_step: Optional hook called as wrap_step(step_num, label, fn) and
                       must return fn(). The adapter uses this to attach Markers,
                       SimplifyContext, and tracing spans without the pipeline importing
                       Flask or g. If None, steps are called directly.
        """

        def _call(step: int, label: str, fn: Callable[[], Any]) -> Any:
            if wrap_step is not None:
                return wrap_step(step, label, fn)
            return fn()

        # Step 2: term detection (deterministic, no LLM)
        yield StepEvent(step=_STEP.DETECT_TERMS.number, status="active", label=_STEP.DETECT_TERMS.label)
        try:
            term_data = _call(
                _STEP.DETECT_TERMS.number, _STEP.DETECT_TERMS.label,
                lambda: detect_terms(text),
            )
        except Exception:
            logger.exception("pipeline: term detection failed — continuing with empty terms")
            term_data = {
                "substitution_candidates": [],
                "preserve_and_define_terms": [],
                "abbreviations": [],
            }
        yield StepEvent(step=_STEP.DETECT_TERMS.number, status="done", label=_STEP.DETECT_TERMS.label)

        # Step 3: simplify language
        yield StepEvent(step=_STEP.SIMPLIFY_LANGUAGE.number, status="active", label=_STEP.SIMPLIFY_LANGUAGE.label)
        try:
            simplified = _call(
                _STEP.SIMPLIFY_LANGUAGE.number, _STEP.SIMPLIFY_LANGUAGE.label,
                lambda: self.simplify_language_with_term_plan(
                    text,
                    term_data["substitution_candidates"],
                    term_data["preserve_and_define_terms"],
                    term_data["abbreviations"],
                ),
            )
        except Exception as exc:
            logger.exception("pipeline: simplification failed")
            yield PipelineStepError(step=_STEP.SIMPLIFY_LANGUAGE.number, exc=exc)
            return
        yield StepEvent(step=_STEP.SIMPLIFY_LANGUAGE.number, status="done", label=_STEP.SIMPLIFY_LANGUAGE.label)

        # Step 4: clarify and action
        yield StepEvent(step=_STEP.CLARIFY_AND_ACTION.number, status="active", label=_STEP.CLARIFY_AND_ACTION.label)
        try:
            clarified = _call(
                _STEP.CLARIFY_AND_ACTION.number, _STEP.CLARIFY_AND_ACTION.label,
                lambda: self.clarify_and_action(simplified, term_data["abbreviations"]),
            )
        except Exception:
            logger.exception("pipeline: clarify step failed — using simplified text")
            clarified = simplified   # non-fatal: fall back to simplified
        yield StepEvent(step=_STEP.CLARIFY_AND_ACTION.number, status="done", label=_STEP.CLARIFY_AND_ACTION.label)

        # Step 5: structure appointment note
        yield StepEvent(step=_STEP.STRUCTURE_DOCUMENT.number, status="active", label=_STEP.STRUCTURE_DOCUMENT.label)
        try:
            structured = _call(
                _STEP.STRUCTURE_DOCUMENT.number, _STEP.STRUCTURE_DOCUMENT.label,
                lambda: self.structure_appointment_note(clarified),
            )
        except Exception as exc:
            logger.exception("pipeline: structuring failed")
            yield PipelineStepError(step=_STEP.STRUCTURE_DOCUMENT.number, exc=exc)
            return
        yield StepEvent(step=_STEP.STRUCTURE_DOCUMENT.number, status="done", label=_STEP.STRUCTURE_DOCUMENT.label)

        terms_glossary = build_glossary_from_simplified_text(
            clarified, term_data["preserve_and_define_terms"]
        )
        # Stop-gap: the CarePlan schema no longer has a `raw` field (PRD 01
        # removed it and rejects unknown fields), so it can't be included
        # here. PRD 06 will rewire this function; until then we still keep
        # the `text`/`simplified`/`clarified` locals since they're used
        # below in the yielded PipelineRunResult.
        result = {
            **structured,
            "terms": terms_glossary,
        }
        care_plan = CarePlan.from_pipeline_result(result)
        if not isinstance(care_plan, CarePlan):
            raise TypeError(f"Expected CarePlan, got {type(care_plan).__name__}")

        yield PipelineRunResult(
            care_plan=care_plan,
            term_data=term_data,
            simplified=simplified,
            clarified=clarified,
            raw_text=text,
        )

    def run(self, text: str) -> CarePlan:
        """Run the full pipeline without instrumentation. Used in tests and batch pre-checks."""
        for event in self.iter_steps(text):
            if isinstance(event, PipelineRunResult):
                return event.care_plan
            if isinstance(event, PipelineStepError):
                raise event.exc
        raise RuntimeError("iter_steps completed without yielding a result")
