# PRD 04 — Assemble and Render

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5, §3.1, §3.4).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Fact`, `FactCategory`; `backend/models/care_plan/care_plan.py` — target `CarePlan` shape), 03 (`CarePlanPipeline.ground(...) -> list[Fact]`, the ledger this PRD's call consumes).
Depended on by: 05 (review-and-correct, re-checks this step's output against the same ledger), 06 (pipeline-orchestration, wires `assemble_and_render` into `iter_steps` and renumbers `PIPELINE_STEPS`), 08 (frontend, renders this step's output — contract in §6).

## 1. Problem

Once grounding (03) exists, the pipeline still has three LLM steps standing between the ledger and a patient-facing result — `simplify_language_with_term_plan`, `clarify_and_action`, `structure_appointment_note` (`backend/care_plan/pipeline.py:96-150`) — and all three still operate on whole-document prose, the exact mechanism the brief's inversion (§2.5) was built to eliminate. `structure_appointment_note` in particular is handed prose that has already been rewritten twice and is then told, in the same rule list, to "use only information found in the source" (rule 1) and to invent a reason for every medication, an urgency for every warning sign, and exactly three questions (rules 4, 5, 9, 10) — the direct cause of the fabrication defect (brief §1). None of the three prompts' genuinely useful content rules (active voice, "you", verb-first actions, no fabricated numbers, PII scrubbing) is wrong; they are simply attached to the wrong architecture — three whole-document rewrites instead of one bounded, per-field render over already-verified facts.

This sub-project deletes all three steps and their prompts and replaces them with one method, `assemble_and_render`, and one prompt, that does exactly the four jobs the brief assigns to this stage (§3.4): map each fact to a care-plan item, split its content into typed fields, render each field in plain language as a bounded value transformation, and write `summary` from the assembled whole. Everything downstream — 05's review, 06's wiring, 08's rendering — depends on this step emitting a `CarePlan` that never had to invent anything, because every fact it started from was already verified against the original note by 03's deterministic checks.

## 2. Goals

- One new method, `CarePlanPipeline.assemble_and_render(facts, substitution_candidates, preserve_and_define_terms, abbreviations) -> CarePlan`, replacing the three deleted methods' combined responsibility with a single LLM call over the verified fact ledger.
- One new prompt file, `backend/care_plan/prompts/assemble_and_render.txt`, carrying: the category→field mapping, the content rules salvaged from all three deleted prompts, the extended PII rule, the required-`status` rule with its default, the "not stated" sentinel and its exact scope, the near-duplicate merge rule with a worked example, the `low_priority` definition, and the `questions` cap with no minimum.
- Deletion of `simplify_language_with_term_plan`, `clarify_and_action`, `structure_appointment_note` and their three prompt files, with every reference to them removed from `backend/care_plan/pipeline.py`'s schema/prompt-loading preamble.
- Two deterministic, LLM-free post-checks on the model's output, applied inside `assemble_and_render` itself: `questions` truncated to 3 if the model overshoots; `summary_fact_ids` filtered to ids that actually exist in the input ledger.
- A decided failure classification (fatal, no fallback) and token/temperature budget, consistent with how `iter_steps` already separates fatal from non-fatal steps.
- Full test coverage, with named attention to the four areas the task calls out: category→field mapping, "not stated" rendering, merge-preserves-variants, and the questions cap.

## 3. Non-Goals

- No pipeline wiring. `assemble_and_render` is a new, standalone method on `CarePlanPipeline`; it is not called from `iter_steps`, `Constants.Pipeline.PIPELINE_STEPS` is not touched, and no progress-event step number is assigned to it here. **This creates a known, accepted transient breakage**: `iter_steps` (today's code) still calls `self.simplify_language_with_term_plan(...)`, `self.clarify_and_action(...)`, `self.structure_appointment_note(...)` by name; once this PRD deletes those methods, `CarePlanPipeline.run()`/`iter_steps()` raises `AttributeError` on any real invocation until 06 rewires `iter_steps` to call `ground()` (03) then `assemble_and_render()` (this PRD) instead. This is identical in kind to 01's `routes/worker.py:198` `.pop("raw", None)` becoming dead code once `raw` was deleted — a sequencing consequence of a decomposition where "pipeline wiring" is deliberately one sub-project's job, not every sub-project's. Nothing is deployed between sub-projects (global constraint: never push to `main`, never deploy), so the transient state is confined to feature-branch commits, not production. See §9.
- No review or correction logic — checking the output against the ledger, applying named corrections, the second PII pass. All 05.
- No changes to `models/ledger.py` (01) or to `ground()`/`ground.txt` (03) — the ledger this PRD consumes is taken as given.
- No changes to `backend/models/care_plan/care_plan.py` — the target schema is 01's, already settled; this PRD does not add, rename, or re-type any `CarePlan` field. Where this PRD's needs and the settled schema don't perfectly line up, that's flagged in §9, not silently patched here.
- No frontend changes. `CarePlanView.tsx` and every other `.tsx` file are 08's.
- No glossary curation logic (07). This PRD does not call `build_glossary_from_simplified_text` and does not decide what replaces it now that there is no more "simplified/clarified" prose string to re-detect terms against — flagged as an interface gap for 06/07 in §9, not solved here.
- No new `ErrorCode` members — reuses `LLM_INVALID_JSON` and `PIPELINE_VALIDATION_FAILED`, exactly as 03 does for `ground()`, to keep this sub-project's footprint to "one method, one prompt."

## 4. Architecture Decisions

### 4.1 New prompt file: `backend/care_plan/prompts/assemble_and_render.txt`

Loaded at module import like the other prompts. Placeholders: `{schema}`, `{facts_block}`, `{sub_block}`, `{medical_block}`, `{abbrev_block}`.

Full proposed text:

```
You are assembling a plain-language care plan for a patient, using ONLY the facts listed below. Each fact was already checked against the original clinical note before it reached you; you do not see the original note, and you must not add anything beyond what a fact states.

Do these four things, in this order, and nothing else:
1. Map each fact to a care-plan item of its category (see MAPPING). Facts are already at clause granularity, so this is close to a one-to-one map -- most facts become exactly one item.
2. Split each item's fact content into that item's typed fields.
3. Render every field in plain language (see LANGUAGE RULES) -- a bounded rewrite of a few words at a time, e.g. "metoprolol 25mg BID" becomes "metoprolol 25 mg twice a day." Never rewrite a fact's meaning, only its wording.
4. Write `summary` from the assembled whole, and list the ids of every fact it draws from in `summary_fact_ids`.

FACTS (id, category, content):
{facts_block}

MAPPING -- a fact's category decides which care-plan array it becomes an item in:
- reason_for_visit -> reason_for_visit[] (reason: a few words; description: one plain-language sentence)
- diagnosis -> diagnosis.details[] (title, plain_name, description, what_it_means_for_you; set severity ONLY if the fact itself states a severity judgement -- otherwise leave it null, never guess). If any diagnosis fact states something changed since the last visit, put that in diagnosis.changed_since_last_visit; otherwise leave it "".
- medications -> medications[] (why, dosage, frequency, timing, duration, instructions, side_effects_to_watch, change, status)
- tests -> tests[] (why, description, preparation, status)
- procedures -> procedures[] (why, what_to_expect, timeframe, status)
- other -> other[] (why, steps[], description, frequency, duration, status)
- follow_up -> follow_up[] (time_frame, description, status)
- warning_signs -> warning_signs[] (what_it_might_mean, what_to_do, urgency, related_to). Set urgency ONLY if the fact states or clearly implies one of emergency / call_doctor / monitor / normal_side_effect -- otherwise leave it null, never guess between them.

A medications fact whose content is a side effect that is merely listed, with no instruction to act on it, belongs in that medication's own side_effects_to_watch field -- never split out as a separate warning_signs item.

STATUS -- every medications, tests, procedures, other, and follow_up item requires status: "to_do" or "done". Never omit it and never leave it null. Use "done" if the fact states or clearly implies the item is already complete. If genuinely unclear, default to "to_do": telling a patient to do something already done costs one phone call; telling them a pending action is complete is a missed follow-up.

NOT STATED -- if a medications, tests, procedures, or other item's `why` is not given by its fact, set why to exactly this sentence: "Not stated in your note." Do not invent a reason, and do not leave the field silently empty -- a blank field reads as an oversight; this sentence makes the gap visible and gives the patient a concrete question to ask.

MERGE -- if two or more facts describe the identical underlying clinical fact (the same finding or instruction, stated more than once, possibly with different specific details), merge them into ONE item. Preserve every differing detail explicitly in the merged wording -- never drop one to shorten the sentence. Example: plaque reported separately in the left and right coronary arteries merges to "heavy plaque in your left and right heart arteries," NEVER to "heavy plaque in your heart arteries." Do not merge facts that are merely related; only merge facts that say the same thing.

LOW PRIORITY -- after mapping, move an item into low_priority (as one short line, not a full item) only if it is a normal result, a routine finding, or an administrative detail: no action for the patient, and no diagnosis or plan they would want in the main sections. This is a narrow reclassification. When in doubt, leave the item in its real section.

QUESTIONS -- write at most three questions a patient might reasonably ask their care team about this visit. Write none if the facts already answer everything a reader would ask -- there is no minimum. Interrogative form only. A question must not assert or presuppose any clinical fact, diagnosis, or judgement that is not already stated in the facts above; it may only ask about a genuine gap or next step.

PII -- replace every person's name and every facility's name with a generic form: a clinician's name becomes "your doctor" (or "your surgeon" / "your cardiologist" / etc. if the fact itself names that specialty); a hospital or clinic name becomes "the hospital" or "the clinic." Example: "Doctor Alok Singh" becomes "your doctor." This is the one case where you do not preserve a fact's exact wording -- a generic form loses the patient no clinical information. The patient's own name, date of birth, address, and insurance details must never appear either.

LANGUAGE RULES -- apply to every field you write:
- Active voice. Address the patient as "you."
- One idea per sentence. Keep sentences under about 20 words.
- Expand every abbreviation. Never print "BID", "HTN", "f/u", or similar -- use the plain words.
- Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number.
- Never add urgency, prognosis, or medical advice beyond what a fact states.
- Start every patient action (in medications, tests, procedures, other, follow_up) with a clear verb: Take / Call / Schedule / Ask / Bring / Watch / Avoid / Continue / Stop.
- Use these plain-language swaps where they fit naturally; do not force one that reads unnaturally:
{sub_block}
- Keep these medical terms exactly as written. Do NOT define them inline -- they are explained separately in the app's glossary:
{medical_block}
- Expand these abbreviations if any fact still contains them:
{abbrev_block}

Return JSON only, matching this schema. No markdown, no commentary.
{schema}

JSON OUTPUT:
```

Design notes:

- **Salvage map from the three deleted prompts**, so nothing valuable is lost (task item C): active voice / "you" (`simplify_language.txt` rules 5-6, `clarify_and_action.txt` rule 2) → LANGUAGE RULES; one-idea-per-sentence / under-20-words (`simplify_language.txt` rule 4, `structure_note.txt` rule 8) → LANGUAGE RULES; expand abbreviations (`simplify_language.txt`'s `{abbrev_block}`) → LANGUAGE RULES + `{abbrev_block}`; no fabricated/converted numbers (`clarify_and_action.txt` rule 4) → LANGUAGE RULES; no added urgency (`clarify_and_action.txt` rule 5) → LANGUAGE RULES; no new medical advice (`clarify_and_action.txt` rule 6) → LANGUAGE RULES; verb-first actions (`clarify_and_action.txt` rule 3) → LANGUAGE RULES; PII (`simplify_language.txt` rule 7, patient-only) → PII, extended per task item E to clinician/facility names. **Deliberately NOT salvaged**: `structure_note.txt` rules 4/5/9/10 (forced-inference — a reason for every medication, an urgency for every warning sign, exactly 3 sentences, exactly 3 questions) and rule 1 ("use only information found in the source," which those same rules then contradicted) — these are the bug, replaced here by NOT STATED, the MAPPING table's explicit nullable-urgency instruction, and QUESTIONS' no-minimum rule.
- **`why` scope for "not stated"**: the four models with a `why` field are `Medication`, `Test`, `Procedure`, `OtherInstruction` (verified against `backend/models/care_plan/care_plan.py`); `FollowUp` has no `why` field and `WarningSign`'s analogous field (`what_it_might_mean`) is supplementary interpretation, not the specific "reason a fabricating model used to invent content" the brief's decision-log row 34 names. Scoping the sentinel to exactly these four fields — rather than every optional string field — keeps the signal meaningful: a blanket "not stated" on every empty field would clutter output that is already meant to be concise (brief §1, "verbose and imprecise") and would dilute the one case (`why`) the brief specifically calls out.
- **`facts_block`** is produced by a new helper, `_format_facts_for_prompt` (§4.3), grouped by category in a fixed order so the model sees its own MAPPING checklist already partially applied — mirrors `_format_units_for_prompt`'s grouping approach from 03 (PRD 03 §4.3).
- `low_priority`'s definition is reproduced near-verbatim from brief §3.9/decision-log row 64 ("normal results, routine findings, administrative detail... one short line per entry") with the brief's explicit "promote UP, don't delete" instinct rendered as "when in doubt, leave it in its real section."

### 4.2 `backend/care_plan/pipeline.py` — deletions

| Symbol | Location (current) | Action |
|---|---|---|
| `simplify_language_with_term_plan` | `pipeline.py:96-114` | **delete method** |
| `clarify_and_action` | `pipeline.py:116-130` | **delete method** |
| `structure_appointment_note` | `pipeline.py:132-150` | **delete method** |
| `_SIMPLIFY_PROMPT` | `pipeline.py:67` | **delete** load line |
| `_CLARIFY_PROMPT` | `pipeline.py:68` | **delete** load line |
| `_STRUCTURE_PROMPT` | `pipeline.py:69` | **delete** load line |
| `_STRUCTURING_SCHEMA` | `pipeline.py:60-63` | **delete** constant |
| `backend/care_plan/prompts/simplify_language.txt` | file | **delete** |
| `backend/care_plan/prompts/clarify_and_action.txt` | file | **delete** |
| `backend/care_plan/prompts/structure_note.txt` | file | **delete** |

Module docstring (`pipeline.py:1-14`) currently reads "three LLM steps that simplify, clarify, and structure the note into a typed CarePlan" with a numbered `Steps: 1-5` list. Update the prose sentence to describe the new shape ("one grounding step extracts evidence-linked facts; one assembly step renders them into a typed CarePlan") since it is now factually wrong about what this file contains — leaving a false docstring is not the same kind of harmless-dead-reference as `routes/worker.py`'s `.pop("raw", None)` (§3). Leave the numbered `Steps:` list itself alone; renumbering it against the real `PIPELINE_STEPS` enum is 06's job (touches step numbering, explicitly out of scope here).

### 4.3 `backend/care_plan/pipeline.py` — additions

New prompt load (alongside 03's `_GROUND_PROMPT` load, assuming 03 has already landed):

```python
_ASSEMBLE_PROMPT = (_PROMPTS_DIR / "assemble_and_render.txt").read_text(encoding="utf-8")
```

New schema constant, following the exact pattern `_STRUCTURING_SCHEMA` used, minus `raw` (deleted by 01 — nothing to exclude) and minus `terms` (this call never produces a glossary) and `note` (unused, matching the old exclude set's precedent):

```python
_ASSEMBLE_SCHEMA = json.dumps(
    _llm_schema(CarePlan, exclude={"terms", "note"}),
    indent=2,
)
```

New helper, alongside 03's `_format_units_for_prompt`:

```python
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
```

### 4.4 `CarePlanPipeline.assemble_and_render` — the method

```python
    def assemble_and_render(
        self,
        facts: list[Fact],
        substitution_candidates: list[dict],
        preserve_and_define_terms: list[dict],
        abbreviations: list[dict],
    ) -> CarePlan:
        """Assembly + render: the single LLM call that maps the verified
        fact ledger into a typed CarePlan, splitting and plain-language-
        rendering each field (brief §2.5, §3.4). Replaces
        simplify_language_with_term_plan + clarify_and_action +
        structure_appointment_note -- no whole-document rewrite exists
        anywhere in the pipeline after this PRD lands.

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
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

        return _verify_assembly(model, facts)
```

New deterministic post-check helper, alongside 03's `_verify_ledger`:

```python
def _verify_assembly(model: CarePlan, facts: list[Fact]) -> CarePlan:
    """Two deterministic, LLM-free guards on the assembled CarePlan (PRD 04
    §4.5). Neither failure is fatal -- both are corrected in place and
    logged, matching 03's drop-and-continue policy for a fact that fails a
    per-item check (PRD 03 §4.5): a model deviation on one field is not a
    reason to fail the whole step."""
    updates: dict = {}

    if len(model.questions) > 3:
        logger.warning(
            "assemble_and_render: truncating %d questions to 3", len(model.questions)
        )
        updates["questions"] = model.questions[:3]

    valid_ids = {fact.id for fact in facts}
    bad_ids = [i for i in model.summary_fact_ids if i not in valid_ids]
    if bad_ids:
        logger.warning(
            "assemble_and_render: dropping summary_fact_ids not present in the "
            "ledger: %s", bad_ids,
        )
        updates["summary_fact_ids"] = [i for i in model.summary_fact_ids if i in valid_ids]

    return model.model_copy(update=updates) if updates else model
```

Notes:

- **Return type is `CarePlan`, not a `dict`.** The old `structure_appointment_note` returned `.model_dump(mode="json", exclude={"terms", "raw"})` because `iter_steps` merged that dict with a separately-computed `terms_glossary` and a `raw` artifact dict (`pipeline.py:239-247`) before constructing the final `CarePlan` via `.from_pipeline_result(result)`. `raw` no longer exists (01) and this PRD does not own how `terms` gets attached (07/06's territory) — returning the typed model directly is the more honest contract: 06 receives a real `CarePlan` and only needs `care_plan.model_copy(update={"terms": glossary})` before wrapping it into `PipelineRunResult`, rather than re-parsing a dict. See §9 for the interface note this implies for 06/07.
- **`summary_fact_ids` verification is a citation check, free and certain** — exactly the same shape of guard as 03's "cited unit id must exist" check (PRD 03 §4.4), applied one step later to a different id space (`Fact.id` instead of `Unit.id`). It costs nothing and catches a hallucinated citation before 05 has to reason about it.
- **`questions` truncation, not rejection.** The prompt already instructs "at most three, no minimum"; the code-level cap is a backstop against a model that miscounts, not the primary enforcement mechanism (that's the prompt). Truncating rather than failing the step avoids discarding an otherwise-good `CarePlan` over a cosmetic overshoot on the one field that is explicitly the pipeline's "genuinely generative" surface (brief §2.5) and therefore most prone to venturing outside instructions.

### 4.5 Failure behaviour and budgets (task item K)

Compare against `iter_steps`'s two existing patterns (`pipeline.py:177-234`, current code):
- **Non-fatal** (`DETECT_TERMS`, `CLARIFY_AND_ACTION`): each has a defined, safe fallback that lets the next step still run — empty term lists, or falling back to the simplify step's own output.
- **Fatal** (`SIMPLIFY_LANGUAGE`, `STRUCTURE_DOCUMENT`): no fallback exists because the step's output is exactly what the next step needs.

**`assemble_and_render` is fatal**, for the same reason `STRUCTURE_DOCUMENT` was and `ground()` now is (PRD 03 §4.6): it is the only source of the typed `CarePlan` that 05 (review), 06 (progress reporting, persistence) and 08 (rendering) all depend on, and — after this PRD lands — there is no whole-document prose left anywhere in the pipeline for it to fall back to. `assemble_and_render` itself does no try/except beyond the two deterministic post-checks in §4.4 (which correct in place rather than raise); it raises `SimplifyError` on non-dict LLM output, on a `CarePlan` that fails Pydantic validation, or on an empty input ledger, and otherwise lets `LLMClient`'s own exceptions propagate unchanged. `iter_steps`'s actual fatal-wrapping of the call is 06's to write; this PRD only specifies which side of the line it belongs on.

**Budgets**: `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536), `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2). The old `structure_appointment_note` used the long-form budget because it emitted the whole structured care plan (`pipeline.py:133-139`'s own comment: "this step emits the full structured care-plan JSON... can easily exceed the default 8192-token cap"). `assemble_and_render` emits the same whole structured care plan, now with field-level plain-language rendering folded into the same call rather than done by two earlier prose passes — its output is at least as large as the old structuring step's, plausibly larger, since no prior rewrite has already condensed the source. `TEMPERATURE_JSON` matches every other structured-JSON-output call in this file (`ground()`, the old `structure_appointment_note`), not `TEMPERATURE_TEXT`, which is reserved for the free-text `_generate_text` path this method does not use.

### 4.6 Content-rule provenance table (task item C, cross-check)

| Rule | Source | Where it lands in `assemble_and_render.txt` |
|---|---|---|
| Active voice; address patient as "you" | `simplify_language.txt` #5-6; `clarify_and_action.txt` #2 | LANGUAGE RULES |
| One idea/sentence, <20 words | `simplify_language.txt` #4; `structure_note.txt` #8 | LANGUAGE RULES |
| Expand abbreviations | `simplify_language.txt` `{abbrev_block}` | LANGUAGE RULES + `{abbrev_block}` |
| No fabricated numbers; no vague→exact conversion | `clarify_and_action.txt` #4 | LANGUAGE RULES |
| No added urgency | `clarify_and_action.txt` #5 | LANGUAGE RULES |
| No new medical advice | `clarify_and_action.txt` #6 | LANGUAGE RULES |
| Verb-first patient actions | `clarify_and_action.txt` #3 | LANGUAGE RULES |
| PII (patient only) → extended to clinician/facility | `simplify_language.txt` #7 | PII |
| Forced reason/urgency/exact-count rules | `structure_note.txt` #4, #5, #9, #10 | **deleted, not salvaged** — replaced by NOT STATED, nullable urgency, no-minimum QUESTIONS |

## 5. API Change Summary

No schema shape changes — 01 already owns and has settled `CarePlanInternal`'s shape. This PRD changes what *values* the pipeline produces within that already-settled shape, which downstream consumers (05, 06, 08) need to know about even though no field is added, removed, or re-typed:

| Behavior | Before | After this PRD |
|---|---|---|
| `medications[].why` / `tests[].why` / `procedures[].why` / `other[].why` when the note doesn't state a reason | fabricated by the model (brief §1) | literal string `"Not stated in your note."` |
| `warning_signs[].urgency` | always a non-null guess (old schema default `"monitor"`) | `null` unless a fact states or implies one of the four values |
| `*.status` | field did not exist | always present, `"to_do"` or `"done"`, never null |
| `questions` | always exactly 3 (old prompt rule 10) | 0-3, most often not 3 |
| Person/facility names | patient PII only scrubbed; clinician/hospital names could leak (brief §1's "Doctor Alok Singh" example) | patient, clinician, and facility names all replaced with generic forms |
| Near-duplicate findings | repeated once per anatomical site (brief §1) | merged into one item, with every variant preserved in the wording |
| `summary_fact_ids` | field did not exist | populated, filtered to real ledger ids (§4.4) |

## 6. Frontend Change Summary

**No new fields for 08 to add** — the contract is 01's §6, unchanged by this PRD. What 08 needs from this PRD is the *content contract* those fields now carry:

- A `why` (or equivalent) field may literally read `"Not stated in your note."` — 08 should render it exactly like any other string value in that field, with no special-case styling or its own fallback text layered on top (a double "not stated" would be worse than the backend's single sentence).
- `questions` may be `[]`. `CarePlanView.tsx:284`'s existing `result.questions?.length > 0 &&` guard already handles this correctly — confirmed no change needed there.
- `warning_signs[].urgency` may be `null` — 01 §6 already flagged this (`URGENCY_ORDER`/`URGENCY_COLORS`/`URGENCY_LABELS` need a null-safe path); this PRD is the reason the value can now genuinely be null in practice, not just in the schema.
- Merged near-duplicate items mean 08 should expect *fewer* rows in e.g. `diagnosis.details`, each potentially longer (multiple sites/values named in one sentence) — no rendering change required, since these are still just strings, but a UI review pass (out of scope here) may find truncation/line-wrap assumptions tuned for shorter single-finding text now worth re-checking.
- `CarePlan.terms` comes back `{}` from `assemble_and_render` itself (§4.4) — unchanged from today's behavior, since the old `structure_appointment_note` never populated `terms` either (`iter_steps` filled it in afterward). No 08 impact.

## 7. Testing

All new/changed tests live under `backend/tests/care_plan/`, following the five existing files' conventions (direct construction via `CarePlanPipeline.__new__(CarePlanPipeline)` plus monkeypatched `_generate_json`).

### 7.1 `backend/tests/care_plan/test_pipeline_structure.py` — rewrite

Current file asserts the three old prompt files exist and nothing about deletion. Replace `test_pipeline_is_flattened_to_a_single_non_versioned_module`'s prompt-file assertions:

```python
prompts_dir = BACKEND_DIR / "care_plan" / "prompts"
assert not (prompts_dir / "simplify_language.txt").exists()
assert not (prompts_dir / "clarify_and_action.txt").exists()
assert not (prompts_dir / "structure_note.txt").exists()
assert (prompts_dir / "assemble_and_render.txt").is_file()
```

Everything else in the file (no `v1`/`v1_1`/`v1_2` packages, no `ABC`, no `SimplifyPipeline`, `test_old_simplify_folder_is_gone`) is unaffected — unrelated to this PRD's changes.

### 7.2 `backend/tests/care_plan/test_pipeline_prompts.py` — rewrite

Delete every test referencing `_SIMPLIFY_PROMPT`, `_CLARIFY_PROMPT`, `_STRUCTURE_PROMPT`, `_STRUCTURING_SCHEMA` (the whole file, as it stands today, is built around exactly these three — nothing survives unmodified). Replace with, mirroring PRD 03 §7.1's pattern for `ground.txt`:

- `test_assemble_prompt_is_non_empty_string`
- `test_assemble_prompt_accepts_all_keys` — `.format(schema="{}", facts_block="[1] medications: x", sub_block="s", medical_block="m", abbrev_block="a")`; assert all five substitutions appear.
- `test_assemble_prompt_raises_on_missing_key` — omit `facts_block`; assert `KeyError`.
- `test_assemble_prompt_contains_not_stated_sentinel` — regression guard: assert the literal substring `"Not stated in your note."` appears in `_ASSEMBLE_PROMPT`.
- `test_assemble_prompt_contains_merge_example` — assert `"left and right heart arteries"` appears (ties the prompt text directly to the worked example the merge rule depends on).
- `test_assemble_prompt_contains_pii_rule_for_clinicians` — assert `"Doctor Alok Singh"` and `"your doctor"` both appear (regression guard for the extended PII rule, task item E).
- `test_assemble_prompt_questions_rule_has_no_minimum` — assert the substring `"no minimum"` appears and that `"exactly three"` / `"exactly 3"` do **not** — regression guard against the forced-inference bug re-entering the prompt.
- `test_assemble_prompt_lists_all_eight_mapping_rows` — assert each of the eight category names from `_FACT_CATEGORY_ORDER` appears in the MAPPING section.

### 7.3 `backend/tests/care_plan/test_pipeline_schema.py` — additions, deletions

Delete every test built on `structure_appointment_note` / `_STRUCTURING_SCHEMA` (`test_structuring_schema_is_generated_from_structured_llm_model`, `test_structure_appointment_note_validates_and_returns_json_model_dump`, `test_structure_appointment_note_uses_long_form_token_budget`, `test_structure_appointment_note_rejects_extra_llm_key`, `test_run_returns_care_plan_model_without_internal_scores` — the last one also references `simplify_language_with_term_plan`/`clarify_and_action`, both deleted). Add:

- `test_assemble_schema_is_generated_from_care_plan_minus_terms_and_note` — `json.loads(pipeline_module._ASSEMBLE_SCHEMA)`; assert `"terms" not in properties`, `"note" not in properties`, `"summary_fact_ids" in properties`, `"medications" in properties`.
- `test_assemble_and_render_returns_care_plan_instance` — monkeypatch `_generate_json` to return a minimal valid dict; assert `isinstance(result, CarePlan)`.
- `test_assemble_and_render_uses_long_form_token_budget_and_json_temperature` — capture kwargs, mirroring `test_ground_uses_long_form_token_budget_and_json_temperature` from PRD 03 §7.2; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.
- `test_assemble_and_render_rejects_non_dict_llm_output` — `_generate_json` returns a `list`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
- `test_assemble_and_render_rejects_extra_llm_key` — output carries an unexpected key (e.g. `"importance"`, same deliberate choice as PRD 03's equivalent test, since it's the field this exact bug pattern already invented once); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
- `test_assemble_and_render_raises_on_empty_fact_list` — call with `facts=[]`; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`, no LLM call made (assert `_generate_json` mock not called).

### 7.4 New file: `backend/tests/care_plan/test_pipeline_assembly.py`

The load-bearing tests for this sub-project — the four areas the task calls out by name.

**Category→field mapping** (build a `Fact` per category, feed through `_format_facts_for_prompt`, and separately through a full `assemble_and_render` call with a canned LLM response, to check both the prompt-construction and the parsing sides):

- `test_format_facts_for_prompt_groups_by_category_in_fixed_order` — facts fed in shuffled category order; assert output lines appear in `_FACT_CATEGORY_ORDER`'s order, not input order.
- `test_format_facts_for_prompt_includes_fact_id_and_category` — assert each line matches `f"[{id}] {category}: {text}"`.
- One parametrized test per category (8 cases), `test_assemble_prompt_construction_includes_fact_for_each_category` — monkeypatch `_generate_json` to capture the prompt string; assert the fact's id and text appear in `facts_block`.

**"Not stated" rendering**:

- `test_assemble_and_render_accepts_not_stated_why` — canned LLM response with `medications[0].why == "Not stated in your note."`; assert it round-trips unchanged (this is the model's job to write, not the pipeline's to inject — the test proves the schema/parsing path doesn't reject or alter the sentinel string).
- `test_assemble_prompt_not_stated_rule_names_all_four_why_fields` — assert `"medications"`, `"tests"`, `"procedures"`, `"other"` all appear in the same paragraph as the not-stated sentinel in `_ASSEMBLE_PROMPT` (string-adjacency check via the NOT STATED section's text block).

**Merge rule preserving variants**:

- `test_assemble_and_render_preserves_merged_diagnosis_variants` — canned LLM response with one `diagnosis.details[0].description` containing `"left and right heart arteries"`; assert the returned `CarePlan.diagnosis.details[0].description` contains both `"left"` and `"right"` substrings (proves the pipeline doesn't post-process/strip anything from a correctly-merged field — the merge itself is the model's job per the prompt, this test guards the pipeline layer doesn't undo it).

**Questions cap** (§4.4's deterministic post-check — the load-bearing pipeline-level test):

- `test_verify_assembly_truncates_questions_over_three` — a `CarePlan` with 5 questions; assert `_verify_assembly` returns one with exactly 3, and that they are the *first* 3 (order-preserving truncation, not resampled).
- `test_verify_assembly_leaves_questions_under_three_unchanged` — 0, 1, and 2-question cases; assert unchanged (proves no minimum is enforced at the pipeline level either).
- `test_verify_assembly_drops_summary_fact_ids_not_in_ledger` — `CarePlan.summary_fact_ids = [1, 2, 999]`, ledger has facts with ids `1, 2`; assert result is `[1, 2]`.
- `test_verify_assembly_returns_same_object_when_no_correction_needed` — no truncation, no bad ids; assert the function still returns a valid, unmodified-in-content `CarePlan` (guards against the `model_copy` branch accidentally firing when `updates` is empty).

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes**, once 06 wires `assemble_and_render()` into the live pipeline (run via ngrok + pm2, `SERVICE_MODE=combined`, against 2-3 real or realistic de-identified notes): (a) confirm a clinician or facility name in the source note renders as "your doctor" / "the hospital" in every field, not just `summary`; (b) confirm a medication with no stated reason in the note renders `why` as exactly `"Not stated in your note."`, not silently blank and not a fabricated reason; (c) confirm a note with two findings at different anatomical sites merges to one item naming both sites, not two items or one item naming only one site; (d) confirm a note that answers every plausible question produces zero `questions`, not three padded ones; (e) confirm a realistic multi-fact ledger does not hit `LLM_MAX_TOKENS` at the 65,536-token output budget. None of this is automatable without a real Vertex AI call and a judgement call on the output, consistent with PRD 03 §8's identical reasoning for `ground()`.
- No new environment variables, credentials, or console configuration — this sub-project is prompt + pure Python only.

## 9. Open Questions & Decisions

- `[RESOLVED: the new method is named assemble_and_render, its prompt file assemble_and_render.txt, its schema constant _ASSEMBLE_SCHEMA — mirroring ground / ground.txt / _GROUNDING_SCHEMA's naming from 03 for consistency across the two new pipeline steps.]`
- `[RESOLVED: assemble_and_render returns a CarePlan object, not a raw dict.]` — the old `structure_appointment_note` returned a dict because `iter_steps` needed to merge in a separately-built `terms`/`raw` dict before constructing `CarePlan`. `raw` no longer exists (01) and `terms` is 07's output, attached later; returning the typed model directly means 06 does `care_plan.model_copy(update={"terms": glossary})` rather than re-validating a dict it already had as a model. Flagged for 06 as the expected call shape.
- `[RESOLVED: "Not stated in your note." is scoped to exactly the four why fields — Medication.why, Test.why, Procedure.why, OtherInstruction.why — not to every optional string field on CarePlan.]` — these are the fields tied to the deleted `structure_note.txt` rule 4 ("every medication must have a 'why'"), the specific forced-inference bug the brief opens with. Applying the sentinel everywhere would clutter output the brief separately wants more concise (§1), diluting the one case that motivated it.
- `[RESOLVED: questions is capped at 3 in two places — a prompt instruction (primary) and a deterministic post-check truncation inside assemble_and_render (backstop).]` — `CarePlan.questions` carries no schema-level `max_length` (01's already-settled schema, not reopened here); rather than ask 01 to add one, the cap is enforced at this PRD's own layer, where the risk (a model overshooting the instruction) actually originates. Truncates rather than fails the step, matching 03's per-item drop-and-continue philosophy (PRD 03 §4.5) rather than its whole-ledger-empty fatal philosophy — a few extra questions is a minor deviation, not a sign the whole output is unusable.
- `[RESOLVED: summary_fact_ids is deterministically filtered to ids present in the input fact ledger, dropping (not failing on) any id the model hallucinates.]` — same shape and same justification as 03's "cited unit id must exist" check (PRD 03 §4.4), applied to the citation surface this PRD introduces.
- `[RESOLVED: assemble_and_render is classified fatal, with no built-in fallback, matching ground() (03) and the old structure_appointment_note.]` — see §4.5.
- `[RESOLVED: a side effect merely listed with no instruction to act on it renders into medications[].side_effects_to_watch, not warning_signs — consistent with 03's own resolved routing decision for this content at the grounding boundary (PRD 03 §9), applied here at the field-splitting stage that actually writes it.]`
- `[RESOLVED: severity (DiagnosisDetail) and urgency (WarningSign) are set only when a fact states or clearly implies them; otherwise left null, matching 01's nullable-no-default precedent for urgency and extending the same "never guess" posture to severity, which 01 already made independently nullable.]`
- `[OPEN: how downstream glossary re-detection (07) and pipeline wiring (06) source the flat text to re-scan for terms, now that assemble_and_render emits a typed CarePlan instead of the single "clarified" prose string build_glossary_from_simplified_text was built to consume (brief §3.7-§3.8 describe re-detection against "the final corrected output" without specifying its shape once that output is no longer prose).]` This PRD does not resolve it — it is explicitly 06/07 territory — but flags it because the interface gap only becomes visible once this step's return type is fixed as `CarePlan`, not `str`. The likely shape (a helper that walks a CarePlan's string fields and concatenates them for re-detection) is a plausible fix but is not this PRD's to design.
- `[RESOLVED: landing this PRD alone breaks iter_steps/run() at runtime (AttributeError on the three deleted method names) until 06 rewires iter_steps to call ground() then assemble_and_render().]` — accepted sequencing consequence of the decomposition's own boundary (pipeline wiring is 06's), not a defect in this PRD; nothing is deployed in the interim per the global no-deploy constraint. Recorded explicitly (rather than left implicit like 01's dead-`.pop()` precedent) because the failure mode here is a hard runtime error, not harmless dead code, and 06's author should not have to rediscover this by running the test suite.
- `[DEFERRED: no minimum content-richness check exists on why/description fields beyond the explicit "Not stated in your note." sentinel — a field could come back technically non-empty but uninformative (e.g. a single vague word).]` — mirrors PRD 03 §9's identical open item about `quote`'s minimum informativeness; a product-judgement call, not a contract this PRD's dependencies settle. Revisit if the manual smoke test (§8) surfaces it in practice.
