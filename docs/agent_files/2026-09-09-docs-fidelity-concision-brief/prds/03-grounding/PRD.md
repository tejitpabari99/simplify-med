# PRD 03 — Grounding

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5 and §3.3).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Unit`, `Fact`, `FactCategory`), 02 (`list[Unit]` produced by `services.unitizer.unitize` / `resolve_units_from_job_doc`).
Depended on by: 04 (assemble-and-render, consumes `list[Fact]`; must call `models.ledger.quote_for(fact, units_by_id)` wherever it needs the evidence text, since `Fact.quote` does not exist — see §4.3/§9), 05 (review-and-correct, re-checks the ledger; same `quote_for()` dependency for its fidelity check), 06 (pipeline-orchestration, wires `CarePlanPipeline.ground` into `iter_steps` and owns the fatal-step handling this PRD specifies but does not implement).

## 1. Problem

The current pipeline has no evidence-linked extraction step at all — `structure_appointment_note` (`backend/care_plan/pipeline.py:132`) is handed already-twice-rewritten prose (via `simplify_language_with_term_plan` then `clarify_and_action`) and asked to both extract clinical content *and* satisfy forced-inference rules ("every medication must have a `why`") in the same pass, with nothing checking the result against the original note. The brief's inverted pipeline (§2.5, §3.1) replaces this with grounding-first: one LLM call reads the pristine, unitized original and emits a flat, evidence-linked `list[Fact]` — atomic clinical statements, each traceable to exactly one `Unit` by id, with a verbatim quote verified and then converted to a source-text pointer — before any rewriting or structuring happens. Nothing in the codebase does this today; `backend/models/ledger.py`'s `Fact` model (01) and `backend/services/unitizer.py`'s `list[Unit]` (02) exist as contracts with no producer.

This sub-project builds that producer: the grounding LLM call, its prompt (with the eight-category checklist carrying criteria and boundary rules — the direct fix for the contrast-dye misclassification bug, brief §1), the abbreviation-injection recall mitigation, and the three deterministic post-checks (unit exists, quote is verbatim, quote is informative) plus offset recovery that together catch fabricated or vacuous evidence with certainty, before any of it reaches 04's assembly step.

## 2. Goals

- A new method, `CarePlanPipeline.ground(units, abbreviations) -> list[Fact]`, that calls the LLM once with the full unit list and the deterministic abbreviation list, and returns a flat, category-tagged, evidence-linked ledger at clause granularity.
- A new prompt file, `backend/care_plan/prompts/ground.txt`, carrying the full eight-category checklist (criteria + boundary rule per category, faithfully reproduced from brief §3.3) as an explicit recall checklist, plus the abbreviation-expansion instruction.
- Three deterministic, LLM-free post-checks — cited unit exists; quote is a verbatim (whitespace/case-tolerant) substring of that unit's text; quote clears a minimum informativeness floor — applied to every fact before it leaves `ground()`, with one decided, justified policy for what happens to a fact that fails any of the three (§4.5).
- A deterministic offset-recovery algorithm that converts a verified quote into `Fact.char_start`/`char_end` — Python slice offsets into the cited `Unit.text` (§4.3). The ledger stores a pointer into source text, not a copy of it; `Fact` has no `quote` field. `models/ledger.py`'s `quote_for()` helper (01) rehydrates the text on demand for 04/05.
- A decided, justified failure mode for the grounding step as a whole (fatal vs. non-fatal), consistent with how `iter_steps` already distinguishes the two (06 wires the actual decision into `iter_steps`; this PRD specifies the contract `ground()` must expose for that wiring).
- Full test coverage: prompt-formatting, ledger-parsing/id-assignment, all three deterministic checks, and offset recovery — including the fabricated-quote case explicitly called out in the task.

## 3. Non-Goals

- No pipeline wiring. `ground()` is a new, standalone method; it is not called from `iter_steps`, `Constants.Pipeline.PIPELINE_STEPS` is not touched, and no progress-event step number is assigned to it here — all 06's.
- No deletion of `simplify_language.txt`, `clarify_and_action.txt`, or `structure_note.txt`, nor of `simplify_language_with_term_plan`, `clarify_and_action`, or `structure_appointment_note` — 04's job (assembly replaces the two prose passes and the structuring call; this PRD only adds grounding alongside them).
- No assembly logic — mapping `Fact` to `CarePlan` fields, plain-language rendering, `summary`/`summary_fact_ids`, `low_priority` assignment, `questions` generation, near-duplicate merging. All 04.
- No review/correction logic (fidelity correction, or checking that every output item's `source_fact_ids` cites real facts). 05.
- No changes to `models/ledger.py` (01) or `services/unitizer.py` (02) — both contracts are taken as given; see §9 for the one place this PRD had to reconcile wording between the task brief and 01's already-resolved schema. This PRD does introduce one small, shared-utility addition outside those two files — `utils/text_normalization.py` gains `normalize_with_offsets` (§4.3) — flagged here since it's the one file this PRD touches beyond `care_plan/pipeline.py` and its own prompt.
- No frontend changes; the ledger is never displayed (brief §3.10) and never reaches an API response (§5, §6).
- No OCR-ceiling, provenance, or unitization changes (02's territory).
- No new `ErrorCode` members — grounding failures are classified using two existing codes (§4.5), to keep this sub-project's footprint minimal; see §9 for the rejected alternative.

## 4. Architecture Decisions

### 4.1 New prompt file: `backend/care_plan/prompts/ground.txt`

Loaded at module import exactly like the other three prompts (`_PROMPTS_DIR / "ground.txt"`). Placeholders: `{schema}`, `{abbrev_block}`, `{units_block}` — same `.format()` pattern as `structure_note.txt`.

Full proposed text:

```
You are extracting atomic clinical facts from a numbered clinical note for a patient-facing care plan tool. Every fact you emit must be traceable to exactly one numbered line below.

Each numbered line is one unit of source text: "[<id>] <text>". Cite a unit ONLY by its integer id, exactly as printed in brackets. Do not invent an id that is not printed below. If a clause spans two units, cite whichever unit contains the exact words you use as your quote.

Return a JSON array. Each array element is ONE atomic clinical fact -- roughly one note clause. "Continue metoprolol 25 mg twice daily" is ONE fact, not four. Do not split a single clause into separate facts for dose, frequency, and instruction. Do not merge two different units' content into one fact.

Each fact has exactly these fields:
- category: exactly one of the eight categories in the checklist below.
- unit_id: the integer id (see brackets above) of the ONE unit your quote comes from.
- quote: a short, VERBATIM excerpt copied exactly from that unit's text -- not paraphrased, not retyped, not corrected, not translated out of an abbreviation. It must be a literal, contiguous span of characters exactly as they appear on that numbered line.
- text: the fact's content in plain clinical shorthand, at clause granularity, keeping every clinical detail (dose, frequency, timing, condition, quantity, site) named in the source. Unlike quote, text MAY expand an abbreviation using the list below.

CATEGORY CHECKLIST -- every fact gets exactly one category. Read the boundary rule before assigning a category; where two categories could plausibly apply, the boundary rule decides.

| Category | Criteria | Boundary rule |
|---|---|---|
| reason_for_visit | Why the patient presented -- complaint, symptom, or referral reason | Not the diagnosis. What they came WITH, not what was FOUND. |
| diagnosis | Conditions, findings and interpretations the clinician recorded | Includes imaging and lab findings stated as conclusions. Excludes the raw measurement, which belongs to the test. |
| medications | Substances the patient takes THEMSELVES, AT HOME | Anything administered DURING a test or procedure belongs to that item instead -- never to medications. Example: contrast dye given during a CT scan is a fact about the scan (category "tests" or "procedures"), never "medications". |
| tests | Diagnostic investigations -- labs, imaging, tracings | Covers both already-performed and newly-ordered tests. |
| procedures | Interventions performed ON the patient | Carries any substance administered during it (see the medications boundary rule above). |
| other | Instructions that are none of the above -- diet, activity, wound care, self-monitoring | If it names a date or an appointment, it is follow_up instead. |
| follow_up | A future appointment or contact, with timing | Not a general instruction. Must involve seeing or contacting someone. |
| warning_signs | Symptoms the note tells the patient to watch for | Must come with what to do, from the note. A side effect that is merely LISTED, with no instruction to act on it, is NOT a warning sign -- extract it as part of the medication's own fact instead. |

Extract every fact that fits one of these eight categories. There is no "other clinical content" catch-all here and no priority judgement to make -- if a statement genuinely fits none of the eight, do not extract it as a fact.

ABBREVIATIONS DETECTED IN THIS NOTE -- the source text below may use these; read them expanded, and use the expansion in `text` (never in `quote`, which must stay verbatim as printed):
{abbrev_block}

Do not fabricate a fact with no unit backing it. Do not invent a quote that only approximately matches its unit's text. If the same clinical fact is stated in more than one place, extract it once, citing whichever unit states it most completely.

Return JSON only -- an array matching this schema. No markdown, no commentary, no trailing explanation.
{schema}

NUMBERED SOURCE:
{units_block}

JSON OUTPUT:
```

Design notes:

- The category table is reproduced **verbatim in structure** from brief §3.3 (criteria + boundary rule per row), with one substantive addition and one terminology reconciliation, both called out below and in §9: the `warning_signs` row adds "extract it as part of the medication's own fact instead" (the brief names the boundary but not where the excluded content goes — this ties it to the existing `Medication.side_effects_to_watch` field, so a listed-but-unactioned side effect isn't silently dropped, just filed as `medications`); and the `diagnosis` row's category value is spelled `diagnosis`, not `diagnosis.details` — see §9.
- `quote`/`text` are pulled apart explicitly in the prompt (quote = verbatim evidence for the deterministic checks in §4.3/§4.5; text = the clause content 04 will render), matching the brief's own distinction (§2.5: "a verbatim quote, and the fact's content at clause granularity") and 01's rationale for the two `_GroundedFactRaw`/`Fact` fields the LLM's evidence splits into (§4.2, §4.3).
- `low_priority` is deliberately absent from the checklist (brief §3.3: "a priority judgement made at assembly ... not a clinical type the grounder can see"), and the prompt says so explicitly rather than just omitting it, since an LLM checklist with a silently-missing bucket invites the model to invent one.
- **The prompt's `quote` instructions are unchanged even though `Fact` no longer stores a `quote` field.** The LLM still emits a verbatim excerpt because that is what makes fabrication mechanically detectable — a model that invents evidence cannot produce a real substring of the source. What changes is only what happens to that string after the substring check passes: code deterministically locates it inside the cited unit's text and records the location (`char_start`/`char_end`) instead of a copy of the text (§4.2, §4.3). The model is never asked to count characters or produce offsets — it cannot be trusted to, which is exactly why offsets are derived by code, never by the LLM.

### 4.2 `backend/care_plan/pipeline.py` — imports and schema

New imports (added to the existing import block):

```python
from models.base import JsonModel
from models.ledger import Fact, FactCategory, Unit
from utils.text_normalization import normalize_text, normalize_with_offsets
```

New prompt load (alongside the three existing `_PROMPTS_DIR / "*.txt"` reads):

```python
_GROUND_PROMPT = (_PROMPTS_DIR / "ground.txt").read_text(encoding="utf-8")
```

**New private model: `_GroundedFactRaw`.** Since 01's `Fact` now stores `char_start`/`char_end` instead of `quote` (§9), `Fact`'s own JSON schema no longer describes what the LLM is asked to produce: the model must still emit `quote`, and must never be asked for `char_start`/`char_end` (it cannot be trusted to count characters — that's code's job, §4.3). Reusing `Fact`'s schema via `_llm_schema(Fact, exclude={"id"})`, the way this PRD did before Fact's shape changed, would now either omit `quote` entirely (wrong — the model needs to know to produce it) or require inventing a bespoke `exclude`/`include` scheme just for this one call site. A small, module-private model that mirrors exactly the four fields the LLM is responsible for is simpler than either:

```python
class _GroundedFactRaw(JsonModel):
    """Shape of one array element straight from the grounding LLM, before
    its quote is verified and converted to char_start/char_end offsets.
    Never constructed from anything but raw LLM JSON, never returned from
    ground(), never passed to 04 or 05 -- purely an intermediate parsing
    target local to this module (PRD 03 SS4.2/SS9). Its four fields are
    exactly Fact's LLM-facing fields; Fact itself additionally carries
    `id` (assigned by code, SS4.4) and `char_start`/`char_end` (computed
    by code from `quote`, SS4.3) in place of `quote`."""

    category: FactCategory
    unit_id: int
    quote: str
    text: str
```

New schema constant, following the exact `_llm_schema(...)` pattern `_STRUCTURING_SCHEMA` already uses, but wrapped as a JSON array since grounding returns a flat list, not one object, and now built from `_GroundedFactRaw` rather than `Fact`:

```python
_GROUNDING_SCHEMA = json.dumps(
    {"type": "array", "items": _llm_schema(_GroundedFactRaw, exclude=set())},
    indent=2,
)
```

Nothing is excluded — every field on `_GroundedFactRaw` is exactly what the LLM should produce, unlike `_STRUCTURING_SCHEMA`'s exclusions (`terms`, `raw`) or this constant's own earlier form (before `Fact` dropped `quote`), which excluded `id`. `Fact.id` is still assigned by code, never the LLM — see §4.4 for where, now that there's no `id` key on the schema the model sees at all.

### 4.3 `backend/care_plan/pipeline.py` — helper functions

```python
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
```

### 4.3a `backend/utils/text_normalization.py` — `normalize_with_offsets` (new function)

Offset recovery (`_locate_quote_offsets` above) needs a version of `normalize_text` that also reports, for each character of its output, which raw-text characters produced it. This is a generalization of `normalize_text`, not a second normalization scheme — the two must never disagree on what the normalized string IS, only on whether position information comes with it. To make that guarantee structural rather than a hope enforced by a test, `normalize_text` is redefined in terms of the new function:

```python
def normalize_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Like normalize_text, but also returns, for each character of the
    normalized output, the (start, end) span of raw `text` indices
    (Python slice semantics) it was derived from -- `len(spans) ==
    len(normalized)` always. Used by grounding (PRD 03 §4.3) to recover
    char_start/char_end for a quote already proven verbatim by
    normalize_text-based comparison, when a naive `str.find` on the raw
    strings would miss a whitespace- or case-normalized match.

    Algorithm, in two passes:

    1. Per-character transliteration. For each raw character at index i,
       run it individually through the same transformation normalize_text
       already applies to the whole string -- NFKD decompose, ASCII-encode
       with errors="ignore", lowercase. Unicode's canonical/compatibility
       decomposition is memoryless (a character's decomposition never
       depends on its neighbors), so doing this one character at a time
       yields the same result as doing it to the whole string at once.
       This produces zero or more output characters per raw character
       (zero if the character is dropped entirely, e.g. a symbol with no
       ASCII equivalent; more than one only for the rare compatibility
       decomposition that expands into multiple ASCII characters, e.g. a
       ligature). Every emitted character is tagged with the raw span
       (i, i+1) of the single input character that produced it.

    2. Whitespace collapse, mirroring `" ".join(text.split())`: scan the
       tagged character list and replace each maximal run of
       whitespace-classified characters with a single " ", tagged with the
       span (first run member's start, last run member's end); drop
       leading and trailing whitespace runs entirely (no character
       emitted, matching `str.split()`'s own behavior).

    The result is character-identical to normalize_text(text) by
    construction (both passes implement exactly normalize_text's own
    documented steps -- decompose, ASCII-ignore, lowercase, whitespace
    collapse-and-strip), which is what test_normalize_with_offsets_matches_
    normalize_text (§7.3) checks across a corpus of representative inputs.
    """
    ...  # see algorithm above; not reproduced as runnable code here


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace."""
    return normalize_with_offsets(text)[0]
```

Redefining `normalize_text` as a thin wrapper (rather than keeping two parallel implementations that a test merely checks agree) means the two functions cannot drift apart by construction — there is exactly one normalization algorithm, exposed two ways. This is a small change to a shared utility file not owned by any single PRD; it's specified here because offset recovery is what needs it, and it does not alter `normalize_text`'s existing observable behavior (same inputs produce the same output string it already produces today — verified by the equivalence test in §7.3, which should be run against the existing `test_text_normalization.py` fixtures/cases to confirm zero behavior change for every existing caller of `normalize_text`, including `utils/term_detection.py`'s unrelated term-matching use).

### 4.4 `CarePlanPipeline.ground` — the method

```python
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
        content is dropped or condensed), same reasoning as
        structure_appointment_note's use of MAX_TOKENS_LONG_FORM.
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
                raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

        verified = _verify_ledger(drafts, units)
        if not verified:
            raise SimplifyError(
                ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail="grounding produced zero verifiable facts",
            )
        return verified
```

Notes:

- **`_GroundedFactRaw` carries no `id`**, so there's no placeholder-id step before validation the way an earlier form of this method (when `Fact` itself was the parse target) needed one — `Fact.model_validate({**item, "id": idx})`'s `idx` existed only to satisfy `Fact.id`'s required-ness before verification, and `_GroundedFactRaw` simply has no such field to satisfy. **`Fact.id` is assigned once, entirely inside `_verify_ledger`**, from the surviving list's own position (`enumerate(verified, start=1)`, §4.3) — never by the LLM, never provisionally. This still mirrors 02's reasoning for why `Unit.id` is assigned deterministically by code rather than asked of a model: an LLM-assigned id risks duplicates or gaps that nothing else in the ledger can safely disambiguate, since `summary_fact_ids`/`source_fact_ids` (01) and 05's citation-soundness check both address facts by this id.
- `_GroundedFactRaw.model_validate(item)` relies on `extra="forbid"` (`JsonModel`) to reject any unexpected key the model adds, and on its four required fields (`category`, `unit_id`, `quote`, `text`) being present — enforced by the model defined in §4.2 with no changes needed here. This is the same strictness posture `Fact.model_validate` provided before Change A, just against the LLM-facing shape instead of the storage shape.
- The empty-ledger check (`if not verified: raise ...`) is deliberate and separate from the three per-fact checks — see §4.5 (next section) for the policy this belongs to.

### 4.5 Deterministic post-checks — policy decision (task item D)

**Decision: drop the offending fact, log it, and continue — do not fail the whole step for one bad citation, one unverifiable quote, or one uninformative quote. If the verified ledger ends up empty, that IS a fatal failure.**

This one policy governs all three deterministic checks alike — unit-exists, quote-is-verbatim, and quote-clears-the-informativeness-floor (§4.3's `_is_informative_quote`, resolving the prior `[OPEN]` item, §9) — not a separate policy per check. A fact that fails any of the three is treated identically: it is dropped from the ledger and logged, and grounding continues with whatever survives.

Justification against the brief's "remove nothing" principle (§2.5, decision-log row 39): that principle protects genuine clinical content from being trimmed for concision or convenience — it is why `low_priority`, duplicate findings, and ungraded warning signs all survive to the output. A fact that fails any of the three deterministic checks is, by definition, *not* verified, informative clinical content — it is a citation to a unit that does not exist, a quote that cannot be found in the unit it claims to come from, or a quote too thin to be worth citing (a single common short word, carrying no dose, name, or other clinically load-bearing content). Keeping any of these in the ledger would propagate exactly the defect the brief opens with ("Nothing anywhere checks the output against the original note... a default is an affirmative claim the model never made"). Dropping only the offending fact — rather than failing the entire grounding step — mirrors the brief's own precedent for how invented content is handled downstream: 05's corrector `remove`s "an item with no support at all" (§2.5) rather than failing the job over it. Applying that same operation one step earlier, deterministically, before assembly ever sees the fact, is strictly better: it is applied with certainty (substring and character checks, not an LLM judgement call) and it means 04 never has to reason about evidence at all — every fact it receives has already been proven to point at something real and worth citing.

The empty-ledger case is different in kind, not degree: it is not "one bad fact among many good ones," it is "grounding produced nothing usable at all." A `CarePlan` assembled from zero facts is not a degraded result, it is a fabricated-looking success — an empty document would sail through 04/05/06 rendering as "no information found" with a 200 response, which is a worse failure mode than an explicit pipeline error the retry/error UI already knows how to show. This is why `ground()` raises in that one case even though the per-fact policy is "drop and continue."

### 4.6 Failure behaviour and budgets (task item E)

**Grounding is fatal.** `ground()` itself does no try/except — it raises `SimplifyError` on invalid JSON shape, on a draft that fails Pydantic validation, or on a fully-empty verified ledger, and otherwise lets `LLMClient`'s own exceptions (`LLM_MAX_TOKENS`, `VertexAPIError`, etc.) propagate unchanged. The fatal/non-fatal decision itself is enforced by `iter_steps`'s wrapping (06's file), but this PRD specifies which side of that line grounding belongs on, and why, so 06 does not have to re-derive it:

Compare against the two existing patterns in `iter_steps` (`backend/care_plan/pipeline.py:177-234`):
- **Non-fatal** (`DETECT_TERMS`, `CLARIFY_AND_ACTION`): each has a defined, safe fallback — empty term lists, or falling back to the simplify step's own output — that lets the *next* step still run on reasonable input.
- **Fatal** (`SIMPLIFY_LANGUAGE`, `STRUCTURE_DOCUMENT`): no fallback exists because the step's output is exactly what the next step needs and nothing else can substitute for it.

Grounding has no fallback by construction: once the pipeline is inverted (brief §2.5), 04's assembly step consumes *only* the ledger — there is no whole-document prose passthrough left anywhere in the pipeline for it to fall back to (that passthrough is exactly what §2.5 deletes). If grounding fails, 04 has nothing to map into `CarePlan` fields; every downstream step (05's citation-soundness check, 06's progress reporting) is defined in terms of the ledger existing. This is the same reasoning that already makes `STRUCTURE_DOCUMENT` fatal today, applied to the step that now plays that role first instead of last.

**Budgets:** `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536), not the default `MAX_TOKENS` (8,192) — grounding's output scales with total document length (every clause becomes one array element, each carrying `category` + `unit_id` + `quote` + `text`), and unlike the old pipeline's `structure_appointment_note`, grounding is not preceded by any content-reducing rewrite, so its output is plausibly the single largest JSON payload in the whole pipeline. `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2), matching every other structured-JSON-output call in this file (`structure_appointment_note`, `clarify_and_action`) rather than `TEMPERATURE_TEXT` (0.3), which is reserved for prose generation.

### 4.7 Abbreviation injection (task item C)

`ground()` calls the already-existing `format_abbreviations_for_prompt` (`utils/term_detection.py:131`) exactly as `simplify_language_with_term_plan` and `clarify_and_action` already do — no new formatting function, no new cap. That function already caps at 30 entries and renders `- "term" -> "expansion"` lines, which is what `{abbrev_block}` in `ground.txt` expects. The list is the deterministic output of `detect_terms(text)["abbreviations"]` (`utils/term_detection.py::detect_terms`), computed once, upstream of grounding, exactly as it already is for the two prose steps.

This is deliberately the *smaller* design decision here: the recall-mitigation value (brief §2.5: "the deterministic abbreviation list is fed into grounding specifically to help it read dense abbreviated source") comes from *where* it's injected (into the one step that reads raw, unrewritten source — see brief §3.3) far more than from any new capping strategy. Reusing the existing 30-entry cap keeps this sub-project's footprint to "one new call site for an existing function," matching how 03 is meant to compose with the deterministic term-detection output it's handed (task: "the deterministic term-detection output" is an *input* to 03, not something 03 recomputes or reshapes).

## 5. API Change Summary

**None.** `ground()`'s output, `list[Fact]`, never reaches an API response — like `Unit` (02) and `SourceSpan` (02), a `Fact` is pipeline-internal only (brief §3.10: "The evidence ledger is NOT displayed"). `ground()` is not yet called from anywhere (06 wires it into `iter_steps`), so no route, job doc shape, or `CarePlanInternal`/`output_data` field changes as a result of this PRD landing.

## 6. Frontend Change Summary

**N/A.** No frontend file is touched, and none needs to be — the ledger this PRD produces is never rendered and never leaves the backend process, consistent with 01's and 02's identical N/A sections.

## 7. Testing

All new/changed tests live under `backend/tests/care_plan/`, following the five existing files' conventions (direct construction via `CarePlanPipeline.__new__(CarePlanPipeline)` plus monkeypatched `_generate_json`, exactly as `test_pipeline_schema.py`'s existing tests already do for `structure_appointment_note`).

### 7.1 `backend/tests/care_plan/test_pipeline_prompts.py` — additions

- `test_ground_prompt_is_non_empty_string` — mirrors the three existing smoke tests.
- `test_ground_prompt_accepts_all_keys` — `.format(schema="{}", abbrev_block="abbr", units_block="[1] text")`; assert all three substitutions appear.
- `test_ground_prompt_raises_on_missing_key` — omit `units_block`; assert `KeyError`.
- `test_ground_prompt_contains_contrast_dye_boundary_rule` — regression guard tying the prompt text directly to the bug it exists to prevent: assert the literal substring `"contrast dye"` (or the row's exact wording) appears in `_GROUND_PROMPT`, so a future prompt edit can't silently drop the one boundary rule the whole sub-project is justified by.
- `test_ground_prompt_lists_all_eight_categories` — assert each of `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs` appears in `_GROUND_PROMPT`, and that `low_priority` does not.

### 7.2 `backend/tests/care_plan/test_pipeline_schema.py` — additions

- `test_grounding_schema_is_a_json_array_of_grounded_fact_raw` — `json.loads(pipeline_module._GROUNDING_SCHEMA)`; assert `["type"] == "array"`, and `"category"`/`"unit_id"`/`"quote"`/`"text"` are all present in `schema["items"]["properties"]`. Also assert `"id"`, `"char_start"`, and `"char_end"` are **not** present — the model is never shown or asked for any of the three, since `id` is code-assigned (§4.4) and `char_start`/`char_end` are computed from the verified `quote` after the LLM call returns (§4.3), not part of `_GroundedFactRaw` at all.
- `test_ground_assigns_sequential_ids_from_array_position` — monkeypatch `_generate_json` to return a two-element list, each matching `_GroundedFactRaw`'s exact shape (`category`/`unit_id`/`quote`/`text`, no `id` key — `_GroundedFactRaw` has no such field to omit-or-include); call `ground()` with two matching, verifiable units whose text contains each element's quote; assert the returned facts have `id == 1` and `id == 2` in order. (Ids are now assigned once, from the *surviving* list's position inside `_verify_ledger` — §4.4's notes — rather than from a pre-verification placeholder; the observable end-to-end behavior this test checks is unchanged.)
- `test_ground_rejects_non_list_llm_output` — `_generate_json` returns a `dict`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
- `test_ground_rejects_extra_key_on_fact` — one array element carries an unexpected key (e.g. `"importance"`, deliberately chosen since it's a field this exact bug pattern already invented once, per 01 §2's own history); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`. Now exercises `_GroundedFactRaw.model_validate`'s `extra="forbid"` rather than `Fact`'s, but the assertion (rejected with the same error code) is unchanged.
- `test_ground_uses_long_form_token_budget_and_json_temperature` — capture kwargs like `test_structure_appointment_note_uses_long_form_token_budget` already does; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.

### 7.3 New file: `backend/tests/care_plan/test_pipeline_grounding.py`

Ledger-parsing and prompt-construction tests that need real `Unit`/`Fact` fixtures (not just schema shape):

- `test_format_units_for_prompt_groups_consecutive_same_page_units_under_one_header` — three units, all `(file="note.pdf", page=1)`; assert exactly one `"=== note.pdf, page 1 ==="` line and three bracketed `[id]` lines.
- `test_format_units_for_prompt_emits_new_header_on_page_change` — two units on page 1, one on page 2 of the same file; assert two header lines.
- `test_format_units_for_prompt_emits_new_header_on_file_change` — two different files; assert two header lines even if `page` is `1` for both.
- `test_ground_builds_prompt_with_abbreviations_and_units` — monkeypatch `self._generate_json` to capture the prompt string it's called with (not just return a canned value); assert the prompt contains the formatted abbreviation block and every unit's bracketed id.

Deterministic post-check tests (D1: unit exists / verbatim; D2: informativeness) — the load-bearing ones for this sub-project, run entirely without any LLM mock, calling `_verify_ledger` / `_is_verbatim_quote` / `_is_informative_quote` / `_locate_quote_offsets` directly. `_verify_ledger` now takes `list[_GroundedFactRaw]` and returns `list[Fact]`; every `test_verify_ledger_*` case below constructs `_GroundedFactRaw` inputs, not `Fact` inputs.

- `test_is_verbatim_quote_exact_match` — quote is an exact substring; `True`.
- `test_is_verbatim_quote_tolerates_whitespace_noise` — unit text has a double space (`"cont.  metoprolol"`), quote has a single space (`"cont. metoprolol"`); `True` — the OCR-tolerance case.
- `test_is_verbatim_quote_tolerates_case_difference` — quote differs only in case from the unit text; `True`.
- `test_is_verbatim_quote_rejects_fabricated_quote` — **the fabricated-quote case the task calls out explicitly.** Quote is plausible-sounding clinical text that does not appear anywhere in the unit's text (e.g. unit text is `"Pt to cont. metoprolol 25mg BID"`, quote is `"increase metoprolol to 50mg"`); `False`.
- `test_is_verbatim_quote_rejects_blank_quote` — quote is `""` or whitespace-only; `False` (guards the Python truism that `"" in x` is always `True`).

Quote informativeness floor tests (D2, §4.3, §9 — resolves the prior `[OPEN]` item):

- `test_is_informative_quote_accepts_short_numeric_quote` — quote `"40 mg"` (5 chars, well under `_QUOTE_MIN_LENGTH`, no word ≥ `_QUOTE_LONG_WORD_MIN_LENGTH`); `True` via the digit rule. This is the exact case the floor exists not to reject.
- `test_is_informative_quote_accepts_short_drug_name` — quote `"warfarin"` (8 chars, under `_QUOTE_MIN_LENGTH`, no digit); `True` via the long-word rule (`"warfarin"` is 8 ≥ `_QUOTE_LONG_WORD_MIN_LENGTH`).
- `test_is_informative_quote_rejects_short_common_word` — quote `"with"` (4 chars, no digit, no word ≥ 7 chars, under 12 chars); `False` — the case the floor exists to catch.
- `test_is_informative_quote_boundary_at_min_length` — quote exactly `_QUOTE_MIN_LENGTH` characters long, containing no digit and no word ≥ `_QUOTE_LONG_WORD_MIN_LENGTH` (e.g. `"see doctor  "`-style 12-char phrase built from short words only — pick a fixture with no word ≥ 7 chars so only the length rule is exercised); `True`. A quote one character shorter under the same construction; `False`. Pins the boundary exactly at the named constant rather than a hardcoded literal in the test.

Offset-recovery tests (§4.3, new for this PRD):

- `test_locate_quote_offsets_exact_match` — quote is an exact substring of `unit_text`; assert `unit_text[char_start:char_end] == quote`.
- `test_locate_quote_offsets_recovers_full_span_across_whitespace_noise` — unit text has a double space or a tab where the quote (already known to pass `_is_verbatim_quote`) has a single space; assert the recovered `(char_start, char_end)` slice of the RAW `unit_text` reproduces the raw double-space/tab form, not the quote's own normalized spacing — proving offsets point at source text, not at a re-normalized copy.
- `test_locate_quote_offsets_recovers_span_despite_case_difference` — quote differs only in case; assert the recovered raw slice matches `unit_text`'s own casing (not the quote's).
- `test_locate_quote_offsets_uses_first_occurrence_when_quote_repeats` — unit text contains the same (normalized) quote text twice; assert the recovered offsets point at the first occurrence, not the second.
- `test_normalize_with_offsets_matches_normalize_text` — property/equivalence test: for a representative set of inputs (reuse `test_text_normalization.py`'s existing fixtures/cases — accented characters, mixed case, runs of whitespace, leading/trailing whitespace, a dropped non-ASCII symbol), assert `normalize_with_offsets(text)[0] == normalize_text(text)` and `len(normalize_with_offsets(text)[1]) == len(normalize_with_offsets(text)[0])`. This is the test that makes the "cannot drift apart" claim in §4.3a a checked property, not just a design intention.

`_verify_ledger`-level tests (now operating on `_GroundedFactRaw` drafts, producing `Fact`s with `char_start`/`char_end`):

- `test_verify_ledger_drops_fact_citing_unknown_unit_id` — one draft cites `unit_id=999` with no matching `Unit`; assert it is absent from the result and the surviving facts are unaffected.
- `test_verify_ledger_drops_fact_with_fabricated_quote` — end-to-end version of the fabricated-quote case through `_verify_ledger`: one good draft, one draft whose quote isn't in its cited unit; assert only the good one survives.
- `test_verify_ledger_drops_fact_failing_informativeness_floor` — one draft whose quote is verbatim but fails `_is_informative_quote` (e.g. `"with"`), one good draft; assert only the good one survives — proves the third check is wired into `_verify_ledger`'s policy, not just unit-tested in isolation.
- `test_verify_ledger_populates_char_start_and_char_end_from_quote` — one surviving draft; assert the resulting `Fact.char_start`/`Fact.char_end` are present, are `int`, and `unit.text[fact.char_start:fact.char_end]` recovers the draft's quote (module-tolerant — i.e. `normalize_text` of the slice equals `normalize_text` of the quote), and assert the resulting `Fact` object has no `quote` attribute at all (`hasattr(fact, "quote") is False`, or equivalently that `Fact.model_fields` doesn't include `"quote"` — a static, not per-instance, guarantee, but worth asserting here too as a regression guard).
- `test_verify_ledger_renumbers_surviving_facts_contiguously` — three input drafts, the second is dropped (bad `unit_id`); assert the two survivors come back with ids `1` and `2`, not `1` and `3`.
- `test_verify_ledger_preserves_order_of_surviving_facts` — order of the input list is preserved (not sorted by category or anything else) among survivors.

`ground()`-level fatal-failure test:

- `test_ground_raises_when_verified_ledger_is_empty` — monkeypatch `_generate_json` to return facts that all fail verification (e.g. all cite nonexistent unit ids); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED` and a detail mentioning the ledger was empty. This is the test that proves §4.5's fatal-on-empty policy, distinct from the per-fact drop tests above (which prove the *non*-fatal, drop-and-continue path when at least one fact survives).

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes.** No automated test in this sub-project (or anywhere in this repo, per the brief's Non-Goals) checks clinical fidelity. Once 06 wires `ground()` into the live pipeline, run it via ngrok + pm2 (`SERVICE_MODE=combined`) against 2-3 real or realistic de-identified notes, specifically checking: (a) a contrast-dye-during-imaging sentence lands in `tests`/`procedures`, not `medications` — the bug this whole category table exists to fix; (b) a dense abbreviation line (e.g. `f/u cards 4/12`) produces a `text` field with the expansion while `quote` stays verbatim; (c) a realistic multi-page note does not hit `LLM_MAX_TOKENS` at the 65,536-token output budget. None of this is automatable without a real Vertex AI call and a judgement call on the output, which is why it's listed here rather than in §7.
- No new environment variables, credentials, or console configuration — this sub-project is prompt + pure Python only.

## 9. Open Questions & Decisions

- `[RESOLVED: the LLM never assigns Fact.id; the pipeline assigns it once, inside _verify_ledger, from the surviving list's own position, so the returned ledger's ids are always a contiguous 1..N sequence.]` — mirrors 02's identical reasoning for why `Unit.id` is code-assigned, not model-assigned; both ledgers' ids are addressed by later steps (`summary_fact_ids`/`source_fact_ids`, 05's citation-soundness check) and can't tolerate model-introduced duplicates or gaps.
- `[RESOLVED: a fact that fails any of the three deterministic checks (unit exists, quote is verbatim, quote is informative) is dropped and logged, not failed as a whole step — unless the entire verified ledger ends up empty, in which case ground() raises.]` — see §4.5 for the full argument: "remove nothing" protects verified, informative content, and a failed check is proof of *unverified or vacuous* content, not information being discarded for convenience.
- `[RESOLVED: Fact stores char_start/char_end (Python slice offsets into the cited Unit.text) instead of a quote string. The LLM's own quote field is unchanged — it still emits a verbatim excerpt, still gets substring-verified — but the string itself is never copied onto Fact. Code deterministically locates the verified quote inside the unit's text (_locate_quote_offsets, §4.3) and records only the location.]` — the source text a job run operates on is deterministic and unchanging for that run (units are recomputed by the pure function `unitize(input_text, input_provenance)`, 02), so a pointer into it is sufficient and a copy is redundant; storing both would duplicate patient source text inside the ledger for no benefit. The model still has to produce a verbatim quote because that's what makes fabrication mechanically detectable (a model that invents evidence cannot produce a real substring) — only what happens to the string *after* verification changes. `models/ledger.py`'s new `quote_for(fact, units_by_id)` helper (01 §4.3) rehydrates the quote on demand for 04's assembly prompt and 05's corrector; both must call it wherever they previously would have read `Fact.quote`, since that field no longer exists.
- `[RESOLVED: a quote passes the informativeness floor if it contains a digit, OR contains a word of _QUOTE_LONG_WORD_MIN_LENGTH (7) or more characters, OR is _QUOTE_MIN_LENGTH (12) or more characters long outright; otherwise it is dropped by the same drop-and-log policy that already governs the unit-exists and verbatim checks (§4.5).]` — a bare character-count floor would reject legitimately short evidence ("40 mg", "warfarin" — neither reaches 12 characters), while a digit or a long word is what actually carries clinical content in a short fragment; the length floor exists only to catch a short quote with neither. This resolves the item previously left `[OPEN]` in this PRD: the earlier concern (an arbitrary character floor would over-reject short valid quotes) is answered by making digits/long-words first-class passes rather than raising the bare length floor, so the two named constants (`_QUOTE_MIN_LENGTH`, `_QUOTE_LONG_WORD_MIN_LENGTH`) are tunable independently if real notes later show either threshold miscalibrated.
- `[RESOLVED: grounding's (and the whole pipeline's) evidence contract is soundness, not completeness. The checkable property is: every care-plan item cites at least one fact (source_fact_ids, 01), and every cited fact id exists in the ledger. A ledger fact that no item cites is not an error — it is a fact the assembly LLM (04) legitimately judged did not belong in a patient-facing report. Coverage in the old "does every fact appear in the output" sense is no longer checked anywhere.]` — this is a project-wide inversion (01 §9 states the same contract and owns `source_fact_ids`'s schema/stripping consequences; 04/05 implement the checks against it). Recorded here because this PRD's own text previously implied the old direction in two places, now corrected: the Non-Goals list (§3) now says "checking that every output item's `source_fact_ids` cites real facts" rather than "coverage checking," and `Fact.id`'s original rationale (removed above) no longer cites "does this fact appear in the output" as its justification. The tradeoff, stated once here per the task: omission is no longer mechanically detectable and becomes a prompt-quality concern for 04's assembly prompt (whether the AHRQ-guided selection is reasonable); fabrication remains mechanically detectable by this PRD's three deterministic checks regardless of which direction coverage runs.
- `[RESOLVED: the substring check (_is_verbatim_quote) reuses utils.text_normalization.normalize_text, accepting its existing behavior (lowercase, accent-stripping, non-ASCII character dropping, whitespace collapse) rather than writing a bespoke normalizer for this one check.]` — the task pointed at this module explicitly; reusing it keeps one normalization definition in the codebase instead of two subtly different ones. Case-insensitivity is an accepted, not fought-for, side effect — case is not clinically load-bearing content, and the check's job is fabrication detection, not typographic fidelity.
- `[RESOLVED: the grounding prompt's category value is the literal "diagnosis" (matching 01's already-resolved FactCategory Literal), not "diagnosis.details" as the task's own prose lists it.]` — 01's `models/ledger.py` (already settled, not re-opened here) spells the eight `FactCategory` values identically to `CarePlan`'s own top-level field names specifically so 04's category→field mapping is a direct lookup; `diagnosis.details` is where a `diagnosis`-tagged fact's content lands downstream, not the tag itself. This is the one place this PRD's instructions and an upstream PRD's already-resolved contract needed reconciling, per the task's own instruction to flag such cases rather than silently diverge.
- `[RESOLVED: a side effect mentioned in the note but with no accompanying instruction to act on it is captured inside its medication's own fact text (feeding the existing Medication.side_effects_to_watch field at assembly), not extracted as a separate warning_signs fact.]` — the brief's boundary rule for `warning_signs` says such content is *not* a warning sign but doesn't say where it goes; leaving it wholly unassigned would silently lose it, which the brief's "remove nothing" principle forbids. Tying it to an existing schema field (rather than inventing a new one) keeps this a routing decision, not a schema decision.
- `[RESOLVED: no new ErrorCode is added; grounding failures use the existing PIPELINE_VALIDATION_FAILED (malformed fact shape, empty verified ledger) and LLM_INVALID_JSON (non-array top-level response) codes.]` — alternative considered: a dedicated `GROUNDING_EMPTY_LEDGER` code for better observability. Rejected for this PRD to keep the footprint to "one new pipeline method, one new prompt," not "one new method plus a new error taxonomy entry"; trivial to add later if telemetry needs to distinguish the empty-ledger case from a generic validation failure.
- `[RESOLVED: this PRD resolves PRD 02's deferred item on what grounding does when a page produces an unusually large number of Units — nothing special. No chunking, batching, or per-unit cap is added. The full unit list goes into one prompt; MAX_TOKENS_LONG_FORM (65,536) bounds the output, and a resulting LLM_MAX_TOKENS error is treated as any other fatal grounding failure (§4.6).]` — introducing chunking would mean re-assembling a ledger's ids across multiple LLM calls, which is real complexity with no evidence yet that it's needed; simplest-thing-that-could-work, revisit if the manual smoke test (§8) actually hits the ceiling on a realistic document.
- `[DEFERRED: empirically measuring extraction recall on raw vs. pre-simplified text is out of scope for this PRD, per the brief's own Open Risks table (§5: "measure it from the grounding step's own output once built... If recall is the problem, feeding the abbreviation list into grounding is the designed mitigation") — the mitigation (§4.7) is built here; the measurement is explicitly a follow-up, not a gate.]`
