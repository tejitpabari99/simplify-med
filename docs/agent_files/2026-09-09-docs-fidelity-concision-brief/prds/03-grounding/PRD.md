# PRD 03 — Grounding

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5 and §3.3).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Unit`, `Fact`, `FactCategory`), 02 (`list[Unit]` produced by `services.unitizer.unitize` / `resolve_units_from_job_doc`).
Depended on by: 04 (assemble-and-render, consumes `list[Fact]`), 05 (review-and-correct, re-checks the ledger), 06 (pipeline-orchestration, wires `CarePlanPipeline.ground` into `iter_steps` and owns the fatal-step handling this PRD specifies but does not implement).

## 1. Problem

The current pipeline has no evidence-linked extraction step at all — `structure_appointment_note` (`backend/care_plan/pipeline.py:132`) is handed already-twice-rewritten prose (via `simplify_language_with_term_plan` then `clarify_and_action`) and asked to both extract clinical content *and* satisfy forced-inference rules ("every medication must have a `why`") in the same pass, with nothing checking the result against the original note. The brief's inverted pipeline (§2.5, §3.1) replaces this with grounding-first: one LLM call reads the pristine, unitized original and emits a flat, evidence-linked `list[Fact]` — atomic clinical statements, each traceable to exactly one `Unit` by id, with a verbatim quote — before any rewriting or structuring happens. Nothing in the codebase does this today; `backend/models/ledger.py`'s `Fact` model (01) and `backend/services/unitizer.py`'s `list[Unit]` (02) exist as contracts with no producer.

This sub-project builds that producer: the grounding LLM call, its prompt (with the eight-category checklist carrying criteria and boundary rules — the direct fix for the contrast-dye misclassification bug, brief §1), the abbreviation-injection recall mitigation, and the two deterministic post-checks that catch fabricated evidence with certainty, before any of it reaches 04's assembly step.

## 2. Goals

- A new method, `CarePlanPipeline.ground(units, abbreviations) -> list[Fact]`, that calls the LLM once with the full unit list and the deterministic abbreviation list, and returns a flat, category-tagged, evidence-linked ledger at clause granularity.
- A new prompt file, `backend/care_plan/prompts/ground.txt`, carrying the full eight-category checklist (criteria + boundary rule per category, faithfully reproduced from brief §3.3) as an explicit recall checklist, plus the abbreviation-expansion instruction.
- Two deterministic, LLM-free post-checks — cited unit exists; quote is a verbatim (whitespace/case-tolerant) substring of that unit's text — applied to every fact before it leaves `ground()`, with a decided, justified policy for what happens to a fact that fails either check.
- A decided, justified failure mode for the grounding step as a whole (fatal vs. non-fatal), consistent with how `iter_steps` already distinguishes the two (06 wires the actual decision into `iter_steps`; this PRD specifies the contract `ground()` must expose for that wiring).
- Full test coverage: prompt-formatting, ledger-parsing/id-assignment, and both deterministic checks — including the fabricated-quote case explicitly called out in the task.

## 3. Non-Goals

- No pipeline wiring. `ground()` is a new, standalone method; it is not called from `iter_steps`, `Constants.Pipeline.PIPELINE_STEPS` is not touched, and no progress-event step number is assigned to it here — all 06's.
- No deletion of `simplify_language.txt`, `clarify_and_action.txt`, or `structure_note.txt`, nor of `simplify_language_with_term_plan`, `clarify_and_action`, or `structure_appointment_note` — 04's job (assembly replaces the two prose passes and the structuring call; this PRD only adds grounding alongside them).
- No assembly logic — mapping `Fact` to `CarePlan` fields, plain-language rendering, `summary`/`summary_fact_ids`, `low_priority` assignment, `questions` generation, near-duplicate merging. All 04.
- No review/correction logic (coverage checking, fidelity correction). 05.
- No changes to `models/ledger.py` (01) or `services/unitizer.py` (02) — both contracts are taken as given; see §9 for the one place this PRD had to reconcile wording between the task brief and 01's already-resolved schema.
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
- `quote`/`text` are pulled apart explicitly in the prompt (quote = verbatim evidence for the deterministic check in §4.4; text = the clause content 04 will render), matching the brief's own distinction (§2.5: "a verbatim quote, and the fact's content at clause granularity") and 01's rationale for the two separate `Fact` fields.
- `low_priority` is deliberately absent from the checklist (brief §3.3: "a priority judgement made at assembly ... not a clinical type the grounder can see"), and the prompt says so explicitly rather than just omitting it, since an LLM checklist with a silently-missing bucket invites the model to invent one.

### 4.2 `backend/care_plan/pipeline.py` — imports and schema

New imports (added to the existing import block):

```python
from models.ledger import Fact, Unit
from utils.text_normalization import normalize_text
```

New prompt load (alongside the three existing `_PROMPTS_DIR / "*.txt"` reads):

```python
_GROUND_PROMPT = (_PROMPTS_DIR / "ground.txt").read_text(encoding="utf-8")
```

New schema constant, following the exact `_llm_schema(...)` pattern `_STRUCTURING_SCHEMA` already uses, but wrapped as a JSON array since grounding returns a flat list, not one object:

```python
_GROUNDING_SCHEMA = json.dumps(
    {"type": "array", "items": _llm_schema(Fact, exclude={"id"})},
    indent=2,
)
```

`id` is excluded from what the model is shown or asked to produce — see §4.3 for why, and §9 for how this maps onto `Fact.id` being `required` per 01's model.

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
    """Deterministic check (D): is `quote` a substring of `unit_text`,
    tolerant of whitespace/case/accent noise from OCR (PRD 03 §4.4)? Reuses
    utils.text_normalization.normalize_text (already used for term-detection
    matching) rather than inventing a second normalization scheme. A blank
    or whitespace-only quote never counts as a match -- "" is trivially a
    substring of everything in Python, but carries no evidence."""
    if not quote.strip():
        return False
    return normalize_text(quote) in normalize_text(unit_text)


def _verify_ledger(facts: list[Fact], units: list[Unit]) -> list[Fact]:
    """The two deterministic post-checks (brief §3.3), no LLM involved.
    Drops -- rather than fails the step for -- any fact that cites a
    nonexistent unit or whose quote cannot be verified verbatim; see PRD 03
    §4.4 for why drop-and-log is the chosen policy. Surviving facts are
    renumbered to a contiguous 1..N id sequence -- safe because nothing
    downstream has referenced these ids yet (this is the ledger's first
    construction), and it keeps the property Unit.id already has (PRD 02
    §4.2): ids are stable, contiguous, and gap-free."""
    units_by_id = {u.id: u for u in units}
    verified: list[Fact] = []
    for fact in facts:
        unit = units_by_id.get(fact.unit_id)
        if unit is None:
            logger.warning(
                "grounding: dropping fact citing unknown unit_id=%d (category=%s)",
                fact.unit_id, fact.category,
            )
            continue
        if not _is_verbatim_quote(fact.quote, unit.text):
            logger.warning(
                "grounding: dropping fact citing unit_id=%d -- quote not found "
                "verbatim in unit text (category=%s)", fact.unit_id, fact.category,
            )
            continue
        verified.append(fact)
    return [fact.model_copy(update={"id": i}) for i, fact in enumerate(verified, start=1)]
```

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

        facts: list[Fact] = []
        for idx, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise SimplifyError(
                    ErrorCode.PIPELINE_VALIDATION_FAILED,
                    detail=f"grounding item {idx} is not a JSON object",
                )
            try:
                facts.append(Fact.model_validate({**item, "id": idx}))
            except ValidationError as e:
                raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

        verified = _verify_ledger(facts, units)
        if not verified:
            raise SimplifyError(
                ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail="grounding produced zero verifiable facts",
            )
        return verified
```

Notes:

- **`id` is assigned by the pipeline, never the LLM**, using the raw array's own position (`enumerate(raw, start=1)`) before validation, then reassigned again after `_verify_ledger` drops any facts (so the returned ledger's ids are always contiguous 1..N, matching `Unit.id`'s own contiguity guarantee from 02). This mirrors 02's own reasoning for why `Unit.id` is assigned deterministically by code rather than asked of a model: an LLM-assigned id risks duplicates or gaps that nothing else in the ledger can safely disambiguate, since `summary_fact_ids` (01) and 05's coverage check both address facts by this id.
- `Fact.model_validate({**item, "id": idx})` relies on `extra="forbid"` (`JsonModel`) to reject any unexpected key the model adds, and on the four required fields (`category`, `unit_id`, `quote`, `text`) being present — both already enforced by 01's `Fact` model with no changes needed here.
- The empty-ledger check (`if not verified: raise ...`) is deliberate and separate from the two per-fact checks — see §4.4 (next section) for the policy this belongs to.

### 4.5 Deterministic post-checks — policy decision (task item D)

**Decision: drop the offending fact, log it, and continue — do not fail the whole step for one bad citation. If the verified ledger ends up empty, that IS a fatal failure.**

Justification against the brief's "remove nothing" principle (§2.5, decision-log row 39): that principle protects genuine clinical content from being trimmed for concision or convenience — it is why `low_priority`, duplicate findings, and ungraded warning signs all survive to the output. A fact that fails either deterministic check is, by definition, *not* verified clinical content — it is either a citation to a unit that does not exist, or a quote that cannot be found in the unit it claims to come from. Keeping either in the ledger would propagate exactly the defect the brief opens with ("Nothing anywhere checks the output against the original note... a default is an affirmative claim the model never made"). Dropping only the offending fact — rather than failing the entire grounding step — mirrors the brief's own precedent for how invented content is handled downstream: 05's corrector `remove`s "an item with no support at all" (§2.5) rather than failing the job over it. Applying that same operation one step earlier, deterministically, before assembly ever sees the fact, is strictly better: it is applied with certainty (a substring check, not an LLM judgement call) and it means 04 never has to reason about evidence at all — every fact it receives has already been proven to point at something real.

The empty-ledger case is different in kind, not degree: it is not "one bad fact among many good ones," it is "grounding produced nothing usable at all." A `CarePlan` assembled from zero facts is not a degraded result, it is a fabricated-looking success — an empty document would sail through 04/05/06 rendering as "no information found" with a 200 response, which is a worse failure mode than an explicit pipeline error the retry/error UI already knows how to show. This is why `ground()` raises in that one case even though the per-fact policy is "drop and continue."

### 4.6 Failure behaviour and budgets (task item E)

**Grounding is fatal.** `ground()` itself does no try/except — it raises `SimplifyError` on invalid JSON shape, on a fact that fails Pydantic validation, or on a fully-empty verified ledger, and otherwise lets `LLMClient`'s own exceptions (`LLM_MAX_TOKENS`, `VertexAPIError`, etc.) propagate unchanged. The fatal/non-fatal decision itself is enforced by `iter_steps`'s wrapping (06's file), but this PRD specifies which side of that line grounding belongs on, and why, so 06 does not have to re-derive it:

Compare against the two existing patterns in `iter_steps` (`backend/care_plan/pipeline.py:177-234`):
- **Non-fatal** (`DETECT_TERMS`, `CLARIFY_AND_ACTION`): each has a defined, safe fallback — empty term lists, or falling back to the simplify step's own output — that lets the *next* step still run on reasonable input.
- **Fatal** (`SIMPLIFY_LANGUAGE`, `STRUCTURE_DOCUMENT`): no fallback exists because the step's output is exactly what the next step needs and nothing else can substitute for it.

Grounding has no fallback by construction: once the pipeline is inverted (brief §2.5), 04's assembly step consumes *only* the ledger — there is no whole-document prose passthrough left anywhere in the pipeline for it to fall back to (that passthrough is exactly what §2.5 deletes). If grounding fails, 04 has nothing to map into `CarePlan` fields; every downstream step (05's coverage check, 06's progress reporting) is defined in terms of the ledger existing. This is the same reasoning that already makes `STRUCTURE_DOCUMENT` fatal today, applied to the step that now plays that role first instead of last.

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

- `test_grounding_schema_is_a_json_array_of_fact_without_id` — `json.loads(pipeline_module._GROUNDING_SCHEMA)`; assert `["type"] == "array"`, `"id" not in schema["items"]["properties"]`, and `"category"`/`"unit_id"`/`"quote"`/`"text"` are all present in `schema["items"]["properties"]`.
- `test_ground_assigns_sequential_ids_from_array_position` — monkeypatch `_generate_json` to return a two-element list with no `id` key on either element; call `ground()` with two matching, verifiable units; assert the returned facts have `id == 1` and `id == 2` in order.
- `test_ground_rejects_non_list_llm_output` — `_generate_json` returns a `dict`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
- `test_ground_rejects_extra_key_on_fact` — one array element carries an unexpected key (e.g. `"importance"`, deliberately chosen since it's a field this exact bug pattern already invented once, per 01 §2's own history); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
- `test_ground_uses_long_form_token_budget_and_json_temperature` — capture kwargs like `test_structure_appointment_note_uses_long_form_token_budget` already does; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.

### 7.3 New file: `backend/tests/care_plan/test_pipeline_grounding.py`

Ledger-parsing and prompt-construction tests that need real `Unit`/`Fact` fixtures (not just schema shape):

- `test_format_units_for_prompt_groups_consecutive_same_page_units_under_one_header` — three units, all `(file="note.pdf", page=1)`; assert exactly one `"=== note.pdf, page 1 ==="` line and three bracketed `[id]` lines.
- `test_format_units_for_prompt_emits_new_header_on_page_change` — two units on page 1, one on page 2 of the same file; assert two header lines.
- `test_format_units_for_prompt_emits_new_header_on_file_change` — two different files; assert two header lines even if `page` is `1` for both.
- `test_ground_builds_prompt_with_abbreviations_and_units` — monkeypatch `self._generate_json` to capture the prompt string it's called with (not just return a canned value); assert the prompt contains the formatted abbreviation block and every unit's bracketed id.

Deterministic post-check tests (D) — the load-bearing ones for this sub-project, run entirely without any LLM mock, calling `_verify_ledger` / `_is_verbatim_quote` directly:

- `test_is_verbatim_quote_exact_match` — quote is an exact substring; `True`.
- `test_is_verbatim_quote_tolerates_whitespace_noise` — unit text has a double space (`"cont.  metoprolol"`), quote has a single space (`"cont. metoprolol"`); `True` — the OCR-tolerance case.
- `test_is_verbatim_quote_tolerates_case_difference` — quote differs only in case from the unit text; `True`.
- `test_is_verbatim_quote_rejects_fabricated_quote` — **the fabricated-quote case the task calls out explicitly.** Quote is plausible-sounding clinical text that does not appear anywhere in the unit's text (e.g. unit text is `"Pt to cont. metoprolol 25mg BID"`, quote is `"increase metoprolol to 50mg"`); `False`.
- `test_is_verbatim_quote_rejects_blank_quote` — quote is `""` or whitespace-only; `False` (guards the Python truism that `"" in x` is always `True`).
- `test_verify_ledger_drops_fact_citing_unknown_unit_id` — one `Fact` cites `unit_id=999` with no matching `Unit`; assert it is absent from the result and the surviving facts are unaffected.
- `test_verify_ledger_drops_fact_with_fabricated_quote` — end-to-end version of the fabricated-quote case through `_verify_ledger`: one good fact, one fact whose quote isn't in its cited unit; assert only the good one survives.
- `test_verify_ledger_renumbers_surviving_facts_contiguously` — three input facts (ids 1, 2, 3), the second is dropped (bad `unit_id`); assert the two survivors come back with ids `1` and `2`, not `1` and `3`.
- `test_verify_ledger_preserves_order_of_surviving_facts` — order of the input list is preserved (not sorted by category or anything else) among survivors.

`ground()`-level fatal-failure test:

- `test_ground_raises_when_verified_ledger_is_empty` — monkeypatch `_generate_json` to return facts that all fail verification (e.g. all cite nonexistent unit ids); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED` and a detail mentioning the ledger was empty. This is the test that proves §4.5's fatal-on-empty policy, distinct from the per-fact drop tests above (which prove the *non*-fatal, drop-and-continue path when at least one fact survives).

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes.** No automated test in this sub-project (or anywhere in this repo, per the brief's Non-Goals) checks clinical fidelity. Once 06 wires `ground()` into the live pipeline, run it via ngrok + pm2 (`SERVICE_MODE=combined`) against 2-3 real or realistic de-identified notes, specifically checking: (a) a contrast-dye-during-imaging sentence lands in `tests`/`procedures`, not `medications` — the bug this whole category table exists to fix; (b) a dense abbreviation line (e.g. `f/u cards 4/12`) produces a `text` field with the expansion while `quote` stays verbatim; (c) a realistic multi-page note does not hit `LLM_MAX_TOKENS` at the 65,536-token output budget. None of this is automatable without a real Vertex AI call and a judgement call on the output, which is why it's listed here rather than in §7.
- No new environment variables, credentials, or console configuration — this sub-project is prompt + pure Python only.

## 9. Open Questions & Decisions

- `[RESOLVED: the LLM never assigns Fact.id; the pipeline assigns it from raw JSON-array position before validation, then reassigns it again after _verify_ledger drops any facts, so the returned ledger's ids are always a contiguous 1..N sequence.]` — mirrors 02's identical reasoning for why `Unit.id` is code-assigned, not model-assigned; both ledgers' ids are addressed by later steps (`summary_fact_ids`, 05's coverage check) and can't tolerate model-introduced duplicates or gaps.
- `[RESOLVED: a fact that fails either deterministic check (D) is dropped and logged, not failed as a whole step — unless the entire verified ledger ends up empty, in which case ground() raises.]` — see §4.5 for the full argument: "remove nothing" protects verified content, and a failed check is proof of *unverified* content, not information being discarded for convenience.
- `[RESOLVED: the substring check (_is_verbatim_quote) reuses utils.text_normalization.normalize_text, accepting its existing behavior (lowercase, accent-stripping, non-ASCII character dropping, whitespace collapse) rather than writing a bespoke normalizer for this one check.]` — the task pointed at this module explicitly; reusing it keeps one normalization definition in the codebase instead of two subtly different ones. Case-insensitivity is an accepted, not fought-for, side effect — case is not clinically load-bearing content, and the check's job is fabrication detection, not typographic fidelity.
- `[RESOLVED: the grounding prompt's category value is the literal "diagnosis" (matching 01's already-resolved FactCategory Literal), not "diagnosis.details" as the task's own prose lists it.]` — 01's `models/ledger.py` (already settled, not re-opened here) spells the eight `FactCategory` values identically to `CarePlan`'s own top-level field names specifically so 04's category→field mapping is a direct lookup; `diagnosis.details` is where a `diagnosis`-tagged fact's content lands downstream, not the tag itself. This is the one place this PRD's instructions and an upstream PRD's already-resolved contract needed reconciling, per the task's own instruction to flag such cases rather than silently diverge.
- `[RESOLVED: a side effect mentioned in the note but with no accompanying instruction to act on it is captured inside its medication's own fact text (feeding the existing Medication.side_effects_to_watch field at assembly), not extracted as a separate warning_signs fact.]` — the brief's boundary rule for `warning_signs` says such content is *not* a warning sign but doesn't say where it goes; leaving it wholly unassigned would silently lose it, which the brief's "remove nothing" principle forbids. Tying it to an existing schema field (rather than inventing a new one) keeps this a routing decision, not a schema decision.
- `[RESOLVED: no new ErrorCode is added; grounding failures use the existing PIPELINE_VALIDATION_FAILED (malformed fact shape, empty verified ledger) and LLM_INVALID_JSON (non-array top-level response) codes.]` — alternative considered: a dedicated `GROUNDING_EMPTY_LEDGER` code for better observability. Rejected for this PRD to keep the footprint to "one new pipeline method, one new prompt," not "one new method plus a new error taxonomy entry"; trivial to add later if telemetry needs to distinguish the empty-ledger case from a generic validation failure.
- `[RESOLVED: this PRD resolves PRD 02's deferred item on what grounding does when a page produces an unusually large number of Units — nothing special. No chunking, batching, or per-unit cap is added. The full unit list goes into one prompt; MAX_TOKENS_LONG_FORM (65,536) bounds the output, and a resulting LLM_MAX_TOKENS error is treated as any other fatal grounding failure (§4.6).]` — introducing chunking would mean re-assembling a ledger's ids across multiple LLM calls, which is real complexity with no evidence yet that it's needed; simplest-thing-that-could-work, revisit if the manual smoke test (§8) actually hits the ceiling on a realistic document.
- `[OPEN]` — no minimum-length or minimum-informativeness constraint is placed on `quote`. A technically-verbatim but near-content-free quote (e.g. a single common word that happens to appear in the cited unit) would pass `_is_verbatim_quote` even though it's weak evidence for its `text`. The brief does not specify a minimum, and inventing an arbitrary character-count floor risks rejecting legitimately short but valid quotes (a single lab value, a single drug name) more often than it catches genuinely lazy extraction. Flagging rather than resolving because this is a product-judgement call, not one this PRD's contracts settle for me.
- `[DEFERRED: empirically measuring extraction recall on raw vs. pre-simplified text is out of scope for this PRD, per the brief's own Open Risks table (§5: "measure it from the grounding step's own output once built... If recall is the problem, feeding the abbreviation list into grounding is the designed mitigation") — the mitigation (§4.7) is built here; the measurement is explicitly a follow-up, not a gate.]`
