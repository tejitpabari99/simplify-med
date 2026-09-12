# PRD 05 — Review and Correct

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5, §3.1, §3.5, §3.6).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Fact`; `backend/models/care_plan/care_plan.py` — the settled `CarePlan` shape, including `source_fact_ids` on all six item models), 03 (the verified `list[Fact]` ledger `ground()` produces), 04 (`CarePlanPipeline.assemble_and_render(...) -> CarePlan`, `assemble_and_render.txt`'s LANGUAGE RULES/PII text — see §4.4's retrofit; also the citation-existence check that guarantees every surviving item's `source_fact_ids` is sound before this PRD's calls ever run — PRD 04 §4.4, §4.7 below).
Depended on by: 06 (pipeline-orchestration, wires `review()`/`correct()` into `iter_steps`, owns fatal/non-fatal wrapping per §4.8's contract), 08 (frontend — `summary` may now be `""` — see §6).

## 1. Problem

Once 04 lands, the pipeline produces a typed `CarePlan` built only from verified facts — but "built from verified facts" is not the same as "verified." Assembly is a single LLM call doing four jobs at once (map, split, render, summarize); nothing checks its output against the ledger it started from, and nothing checks that every fact the ledger contains actually made it into the output. Two independent literatures say this gap is not cosmetic: an LLM verifier bolted onto ungrounded prose largely rubber-stamps (38 invalid plans passed out of ~92 approved, [arXiv:2310.08118](https://arxiv.org/pdf/2310.08118)), and LLM judges asked "is anything missing" perform near chance (0.50–0.63 AUC) because an omission leaves nothing to point at ([arXiv:2608.31016](https://arxiv.org/html/2608.31016v1)). Both risks apply directly here: assembly is itself a fourth author capable of contradicting a fact ("500" becomes "5000"), asserting what a fact doesn't support (a dose the note never gives), or simply dropping a fact assembly had no slot for.

This sub-project builds the two LLM calls the brief specifies as pipeline steps 3 and 4 — review and correct — and the deterministic bookkeeping around them. Review reads the ledger and the assembled plan and reports problems using a fixed three-operation vocabulary; it never rewrites, because a reviewer permitted to write becomes the fourth author it exists to catch. Correct is a separate, narrower LLM call that applies exactly the named corrections plus a PII sweep, and is itself checked by a deterministic diff — the design's acknowledged soft spot, mitigated by asserting that nothing outside the named corrections changed. The project's soundness contract — every item cites at least one real fact, every cited id exists in the ledger — is enforced once, deterministically, at assembly time (04 §4.4); this sub-project's own deterministic layer, the corrector's diff check, additionally guarantees `correct()` cannot violate that invariant on the way out, since `source_fact_ids` is never a field the correction vocabulary can touch (§4.7). The old "does every ledger fact appear somewhere in the output" completeness check is deliberately not reimplemented here — that direction of the check is exactly what the project's soundness-over-completeness inversion (01 §9, 03 §9) retires; omission is a prompt-quality concern for 04, not something this PRD gates on.

## 2. Goals

- `CarePlanPipeline.review(facts, care_plan) -> ReviewResult`: one LLM call producing field-level corrections (fidelity) and a per-fact presence verdict for every fact in the ledger (coverage, enumerate-then-check-presence shape — mandatory per the brief, not a style choice).
- A precise JSON-path addressing scheme, shared by both calls, that is the machine-readable contract between them.
- `CarePlanPipeline.correct(care_plan, corrections, ...) -> CarePlan`: a second LLM call applying only the named corrections plus a PII sweep, with a deterministic diff check that rejects (falls back, does not raise fatally) any output touching a field the corrections don't explain — including, as a direct consequence of that same generic check, any attempt to touch `source_fact_ids` (§4.7).
- No separate deterministic coverage/closing pass in this PRD. The citation-existence property (every item cites ≥1 fact, every cited id exists in the ledger) is established once, at assembly time, by 04's own post-check (04 §4.4) and is preserved through `correct()` by construction (§4.7) — there is nothing left for a second pass in this PRD to check or fix. This replaces the prior design's `close_coverage()` token-overlap heuristic, deleted outright rather than kept as a fallback (§4.7, §9).
- A decided, justified fatal/non-fatal classification for both LLM steps, consistent with `iter_steps`'s existing two patterns, and consistent with the brief's explicit instruction that a fidelity nit must not cost the user their whole result.
- A concrete protocol for testing the one thing unit tests cannot: whether the reviewer actually catches injected errors, rather than rubber-stamping.

## 3. Non-Goals

- No pipeline wiring. Neither new method (`review`, `correct`) is called from `iter_steps`; `Constants.Pipeline.PIPELINE_STEPS` is untouched; no progress-event step numbers are assigned. All 06.
- No taxonomy/category judgement in the reviewer — which section an item belongs in is 04's decided territory (brief §3.5: "loading taxonomy onto the reviewer dilutes the one thing it is for").
- No citation-existence/coverage check in this PRD. That property is 04's (04 §4.4): every item's `source_fact_ids` is already filtered to real ledger ids, and any item left fully unbacked is already dropped, before `review()` is ever called. This PRD does not re-check it — see §4.7 for why the corrector's own diff check is sufficient to guarantee `correct()` cannot undo that guarantee.
- No changes to `models/ledger.py` (01) or `models/care_plan/care_plan.py` (01) — the ledger and the target schema are taken as given. One narrow, disclosed retrofit to 04's `assemble_and_render.txt` is made (§4.4) to share text, not to change its meaning.
- No glossary re-detection (07's other half of brief §3.7).
- No frontend changes; `CarePlanView.tsx` and every `.tsx` file are 08's. §6 flags content-contract nuances only.
- No new `ErrorCode` members — reuses `LLM_INVALID_JSON` and `PIPELINE_VALIDATION_FAILED`, matching 03/04's footprint discipline.
- No automated, fully-deterministic proof that the reviewer catches real errors — that requires a real model call and is out of unit-test reach by construction; §7.5/§8 specify the protocol instead of pretending it can be a `pytest` assertion.

## 4. Architecture Decisions

### 4.1 New module: `backend/models/review.py`

Placement mirrors 01's reasoning for `ledger.py` (§4.3 there): a small, flat, pipeline-internal module, not a subpackage, not nested under `care_plan/` — `Correction`/`CoverageEntry`/`ReviewResult` are never persisted, never serialized to Firestore, never reach an API response, exactly like `Unit`/`Fact`. This PRD owns "the correction-operation vocabulary that is the contract between [review and correct]" per its own charter, so defining it here — rather than reopening 01's settled `ledger.py`/`care_plan.py` — keeps that ownership boundary honest.

```python
"""Reviewer output + correction vocabulary shared with the corrector
(PRD 05 §4). Pipeline-internal only -- same posture as models.ledger."""

from __future__ import annotations
from typing import Literal
from .base import JsonModel

CorrectionOp = Literal["correct", "not_stated", "remove"]   # the whole vocabulary


class Correction(JsonModel):
    """One field-level finding. `path` addresses the assembled CarePlan
    (§4.2) -- the machine-readable contract the corrector consumes."""
    op: CorrectionOp
    path: str
    value: str | None = None   # required for "correct"; absent otherwise


class CoverageEntry(JsonModel):
    """One line of the enumerate-then-check-presence walk (brief §3.5) --
    answered for EVERY fact_id, not just ones judged missing."""
    fact_id: int
    present: bool


class ReviewResult(JsonModel):
    """`verdict` is informational only (§4.5) -- whether to run the
    corrector is decided from `len(corrections) > 0`."""
    verdict: Literal["pass", "needs_correction"]
    corrections: list[Correction] = []
    coverage: list[CoverageEntry] = []
```

### 4.2 JSON path addressing scheme

This is the machine-readable contract both prompts and both post-validation layers share. Rules:

1. A path is a dotted sequence of field names, with `[N]` (0-based integer) after any list-typed field: `medications[2].dosage`, `diagnosis.details[0].severity`, `other[1].steps[0]`.
2. `[N]` always refers to the item's position in the **pre-correction** `CarePlan` — the one the reviewer was shown. Corrections are computed once, against one snapshot; the corrector must not reorder items (stated explicitly in `correct.txt`, §4.6), so position stays a stable handle for the one round-trip this contract needs to survive.
3. `remove` may target: an array element (`warning_signs[3]`, `questions[1]`, `low_priority[0]`) — deletes it — or, as the sole named exception, the bare field `summary` — clears it to `""` (see §4.5's rationale: `summary` has no sub-structure a path can address, and the reviewer may not supply replacement prose).
4. `not_stated` may target only one of exactly four paths per item: `medications[N].why`, `tests[N].why`, `procedures[N].why`, `other[N].why` — the same four fields 04 scoped its sentinel to (PRD 04 §4.1). Any other path is invalid.
5. `correct` may target any other leaf field. `value` is a plain string (or, for `warning_signs[N].urgency`, one of the four urgency literals, or `"to_do"`/`"done"` for a `status` field) — never a JSON blob, never multi-field.
6. A path never addresses `CarePlan` itself, `doc_type`, or `version` — nothing in this sub-project's vocabulary touches document identity.

Resolution helper, shared by review-output validation and the diff check (§4.6):

```python
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
```

### 4.3 New prompt file: `backend/care_plan/prompts/review.txt`

Loaded at import like the other prompts. Placeholders: `{schema}`, `{facts_block}`, `{care_plan_block}`.

```
You are reviewing a patient-facing care plan for fidelity to the clinical facts it was built from, and for completeness. You do not see the original note. You do not rewrite anything -- you report problems only in the formats below, and you never write new sentences.

You are given:
1. FACT LEDGER -- every clinical fact already verified against the original note.
2. CARE PLAN -- the structured plan assembled from those facts.

Do two separate jobs.

JOB 1 -- FIDELITY. Find every place the care plan says something its fact(s) do not support: an added diagnosis or interpretation; a medication name, dose, frequency, duration, or status that doesn't match its fact; a date or measurement that doesn't match; a negation or uncertainty flip ("no evidence of X" written as "X", "possible" written as "confirmed"); a declined or conditional treatment written as accepted or vice versa; a warning instruction or urgency that doesn't match its fact; a to_do/done status that doesn't match. For each problem, emit exactly one correction using this vocabulary -- there is no fourth option:

- "correct": the plan contradicts its fact. Give the right value, taken directly from the fact. Do not compose a new sentence -- give only the corrected field's own value.
- "not_stated": the plan asserts a reason the fact doesn't support. Valid ONLY for these four paths: medications[N].why, tests[N].why, procedures[N].why, other[N].why. Do not set a value -- the fixed sentence is inserted downstream.
- "remove": an item with no supporting fact at all. Target the array item itself (e.g. "warning_signs[3]"), not one of its fields.

Do NOT judge which array/section an item belongs to -- only whether its content is true to its fact(s). Do not flag style, tone, or word choice.

SUMMARY -- summary was built from the facts listed in summary_fact_ids. Check that every cited fact actually supports what summary says about it, and that summary asserts nothing outside those cited facts. If summary itself has drifted from its citations, emit {"op": "remove", "path": "summary"} -- you may not supply replacement text for it.

QUESTIONS -- each entry in questions must not presuppose any clinical fact, diagnosis, or concern absent from the fact ledger. If one does, emit {"op": "remove", "path": "questions[N]"} for that entry.

JOB 2 -- COVERAGE. Below is the full numbered fact ledger. For EVERY fact, in order, decide: does this fact's content appear somewhere in the care plan, in its own words or the plan's rewritten words -- it does not need to match verbatim? Answer for every single fact listed; do not skip any, and do not answer for a fact_id not listed.

FACT LEDGER:
{facts_block}

CARE PLAN (JSON, 0-based array positions -- address items exactly by these positions):
{care_plan_block}

Return JSON only, matching this schema. No markdown, no commentary.
{schema}

JSON OUTPUT:
```

Design notes:

- The prompt never asks the model to produce prose — every instruction resolves to a path, a copied value, or a boolean, upholding "never rewrites and never emits prose" (brief §3.5) at the prompt-text level, not just by convention.
- `care_plan_block` is `json.dumps(care_plan.model_dump(mode="json"), indent=2)` — the model needs the real array positions to emit valid paths, so this is the one case in the whole pipeline where a full `CarePlan` dump is shown to a model verbatim (grounding and assembly never see each other's output).
- Coverage's "in its own words is fine" instruction is deliberate: after 04's plain-language rendering, exact-quote matching is not the right bar for the LLM check (unlike 03's deterministic substring check, which operates on the pristine source, not rendered prose).

### 4.4 New prompt file: `backend/care_plan/prompts/correct.txt`, and the shared-style-rules retrofit to 04

**Retrofit to `assemble_and_render.txt` (PRD 04 §4.1) — extract, don't duplicate.** The brief specifies the corrector is "guided by the same style rules as the writer prompts" — literally the same text 04 already wrote for its LANGUAGE RULES and PII paragraphs, not a re-derivation of it. Duplicating that text into `correct.txt` would let the two drift on the next prompt edit. Instead:

- New file `backend/care_plan/prompts/_style_rules.txt`: the LANGUAGE RULES and PII paragraphs, moved verbatim out of `assemble_and_render.txt` (PRD 04 §4.1's text, lines starting `PII --` through the end of `LANGUAGE RULES --`'s bullet list, excluding the `{sub_block}`/`{medical_block}`/`{abbrev_block}` substitution lines which stay call-specific).
- `assemble_and_render.txt` changes only its LANGUAGE RULES/PII section from inline text to one placeholder, `{style_rules}`; `assemble_and_render`'s `.format()` call gains one new kwarg, `style_rules=_STYLE_RULES`.
- `correct.txt` (below) consumes the identical `_STYLE_RULES` constant, loaded once at import next to the other prompts.

This is a small, mechanical, additive change to a file 04 already owns the content of — not a reinterpretation of 04's rules, purely a location change so both prompts read one source of truth. Flagged explicitly, matching the convention 01 used for its own discovered-dependency fix to `utils/misc.py` (PRD 01 §4.6).

New pipeline constant:

```python
_STYLE_RULES = (_PROMPTS_DIR / "_style_rules.txt").read_text(encoding="utf-8")
```

`correct.txt` full text. Placeholders: `{corrections_block}`, `{style_rules}`, `{care_plan_block}`, `{schema}`.

```
You are applying a fixed list of corrections to a plain-language care plan, plus one additional sweep for names. You do not review, and you do not add, remove, or rephrase anything beyond what is listed below.

Apply EXACTLY these corrections and nothing else. Do not reorder any array. Do not touch any field not named below, except during the PII SWEEP.

CORRECTIONS:
{corrections_block}

For a "correct" entry: replace that exact field's value with the value given, re-rendered in the same style as the rest of this document -- e.g. if the given value is raw clinical shorthand, render it the way this document already renders comparable values (units, abbreviation expansion, "you" phrasing). Confine the change to that field; do not extend it into a neighboring field or sentence.

For a "not_stated" entry: set that exact field to precisely this text and nothing else: "Not stated in your note."

For a "remove" entry: delete that array item entirely. If the path is exactly "summary", set summary to "" instead (summary has no array position to delete).

PII SWEEP -- after applying the corrections above, re-read every remaining field once more. Replace any surviving clinician or patient-facing person's name with a generic form ("your doctor", "your cardiologist", etc. if a specialty is named) and any surviving facility name with "the hospital" or "the clinic". This is the ONLY change you may make to a field not listed in CORRECTIONS. Swap the name only -- leave the rest of that field's wording exactly as it was.

STYLE RULES (for restyling corrected values only -- do not apply these to re-write anything not named above):
{style_rules}

CARE PLAN (JSON, 0-based array positions matching the paths above):
{care_plan_block}

Return the complete corrected care plan as JSON, matching this schema -- same shape as the input, with only the named corrections and the PII sweep applied. No markdown, no commentary.
{schema}

JSON OUTPUT:
```

### 4.5 `CarePlanPipeline.review` — the method

```python
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
    raw = self._generate_json(prompt, temperature=Constants.Llm.TEMPERATURE_JSON,
                               max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM)
    if not isinstance(raw, dict):
        raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")
    try:
        result = ReviewResult.model_validate(raw)
    except ValidationError as e:
        raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

    return _sanitize_review_result(result, care_plan, facts)
```

Deterministic post-validation (drop-and-log, not fail — mirrors 03's per-fact policy, PRD 03 §4.5):

```python
_WHY_PATH_RE = re.compile(r"^(medications|tests|procedures|other)\[\d+\]\.why$")

def _sanitize_review_result(result: ReviewResult, care_plan: CarePlan, facts: list[Fact]) -> ReviewResult:
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
```

`_targets_removed_item` checks whether a `correct`/`not_stated` path's leading `array[N]` segment matches an already-`remove`d item path — a small string-prefix comparison, omitted here for brevity but exercised directly in tests (§7.2).

**Whether to run `correct()` at all is driven by `len(result.corrections) > 0`, not `result.verdict`** — `verdict` is carried through for logging/observability only (§4.1's docstring), so a model that says `"pass"` but still lists a correction (or vice versa) doesn't silently skip real findings.

### 4.6 `CarePlanPipeline.correct` — the method, and the diff check

```python
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
    raw = self._generate_json(prompt, temperature=Constants.Llm.TEMPERATURE_JSON,
                               max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM)
    if not isinstance(raw, dict):
        raise SimplifyError(ErrorCode.LLM_INVALID_JSON, detail=f"expected dict, got {type(raw)}")
    try:
        corrected = CarePlan.model_validate(raw)
    except ValidationError as e:
        raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

    _verify_correction_diff(care_plan, corrected, corrections)   # raises on violation
    return corrected
```

**The diff check (brief's named mitigation for the corrector's soft spot).** The naive approach — flatten both `CarePlan`s to `{path: value}` maps and diff — breaks the moment a `remove` changes an array's length, because index `k` in the corrected array no longer denotes the same original item as index `k` in the pre-correction one. The fix does not require content-based alignment: the prompt requires order preservation (§4.4, "do not reorder any array"), so position bookkeeping is enough, checked defensively rather than assumed:

```python
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

def _verify_correction_diff(before: CarePlan, after: CarePlan, corrections: list[Correction]) -> None:
    before_d, after_d = before.model_dump(mode="json"), after.model_dump(mode="json")
    named = {c.path for c in corrections}
    removed_by_array: dict[str, set[int]] = {}   # e.g. "warning_signs" -> {1, 3}
    for c in corrections:
        if c.op == "remove" and c.path != "summary":
            arr, idx = _split_array_path(c.path)   # "warning_signs[3]" -> ("warning_signs", 3)
            removed_by_array.setdefault(arr, set()).add(idx)

    for field in CarePlan.model_fields:
        if field not in _LIST_FIELDS:
            _check_scalar_or_nested(before_d[field], after_d[field], field, named)
            continue
        before_arr, after_arr, removed = before_d[field], after_d[field], removed_by_array.get(field, set())
        expected_survivors = [i for i in range(len(before_arr)) if i not in removed]
        if len(after_arr) != len(expected_survivors):
            raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED,
                detail=f"{field}: expected {len(expected_survivors)} items after correction, got {len(after_arr)}")
        for k, orig_idx in enumerate(expected_survivors):
            _diff_item(before_arr[orig_idx], after_arr[k], f"{field}[{orig_idx}]", named)

def _diff_item(before_item, after_item, path_prefix: str, named: set[str]) -> None:
    for key, before_v in (before_item.items() if isinstance(before_item, dict) else enumerate([before_item])):
        after_v = after_item[key] if isinstance(after_item, dict) else after_item
        full_path = f"{path_prefix}.{key}" if isinstance(before_item, dict) else path_prefix
        if before_v == after_v:
            continue
        if full_path in named or any(full_path.startswith(p) for p in named):
            continue
        if isinstance(before_v, str) and isinstance(after_v, str) and \
           key in _PII_ELIGIBLE_FIELDS and _looks_like_pii_substitution(before_v, after_v):
            continue
        raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED,
            detail=f"corrector changed unnamed, non-PII field: {full_path}")
```

Any violation raises `PIPELINE_VALIDATION_FAILED`; §4.8 specifies the non-fatal fallback the caller applies. `summary`'s `correct`-op-is-forbidden rule (§4.2) means `summary`'s diff check only ever needs to permit `remove` (clear to `""`) or a PII-eligible small swap — never an arbitrary replacement, which is exactly the guardrail the boundary in §4.2 exists to produce.

### 4.7 The citation-existence check belongs to 04, not this PRD

**`close_coverage()` is deleted, not reimplemented with a different check.** The prior design's `close_coverage` existed only to catch the old-direction failure — "does every ledger fact appear somewhere in the output" — using a token-overlap heuristic (`_COVERAGE_TOKEN_RE`, `_COVERAGE_OVERLAP_THRESHOLD`) because no per-item fact provenance existed to check exactly. That heuristic is deleted outright, not kept as a fallback: the project's contract has inverted from completeness to soundness (01 §9, 03 §9) — a ledger fact no item cites is now legitimate, not an error, so there is nothing left for a "did every fact make it out" check to legitimately gate on. The `"From your note: <fact text>"` safety-net line this function used to append to `low_priority` is deleted along with it.

**The check the new contract actually calls for — every item cites ≥1 fact, every cited id exists in the ledger — is owned entirely by 04 (04 §4.4), not this PRD.** `Medication`/`Test`/`Procedure`/`OtherInstruction`/`FollowUp`/`WarningSign` all carry `source_fact_ids` now (01 §4.1), populated by `assemble_and_render` the same way `summary_fact_ids` already is; 04's own deterministic post-check filters every item's `source_fact_ids` to real ledger ids and drops any item left with none, before `assemble_and_render` even returns. By the time `review()` is called, every `CarePlan` this PRD ever sees already satisfies the invariant. Re-checking it here would be pure duplication: this PRD has no new information about fact-to-item provenance that 04 didn't already have (and act on) first.

**Why no second pass is needed after `correct()` runs, either.** The only way the invariant could break downstream is if `correct()` altered or dropped a `source_fact_ids` list in a way 04 didn't intend. It cannot: the correction vocabulary (§4.2) never names `source_fact_ids` as a target — `correct`/`not_stated` only ever address content fields (`why`, `dosage`, `status`, ...), and `remove` deletes a whole item (taking its `source_fact_ids` with it, which is correct — a removed item citing nothing is not a soundness gap, it no longer exists). The corrector's own diff check (§4.6) independently enforces this: `_diff_item` walks every field of every surviving item, including `source_fact_ids`, and any unnamed, non-PII-eligible change (`source_fact_ids` is not in `_PII_ELIGIBLE_FIELDS`) raises `PIPELINE_VALIDATION_FAILED`, which `correct()`'s caller then falls back away from (§4.8) rather than ship. A test enforcing this directly — `test_diff_check_rejects_change_to_source_fact_ids` — is added in §7.3, since this argument is exactly what makes a redundant post-`correct()` check unnecessary, and it deserves its own regression guard rather than just a paragraph of reasoning.

**Ownership, stated once:** 04 §4.4 is the single place in the pipeline the citation-existence property is checked and enforced; this PRD cross-references it rather than re-implementing any part of it. See PRD 04 §9 and §4.4 for the check itself.

### 4.8 Failure behaviour and budgets

Compare against `iter_steps`'s two existing patterns (`pipeline.py:177-234`):
- **Non-fatal** (`DETECT_TERMS`, `CLARIFY_AND_ACTION`): a defined, safe fallback lets the next step run.
- **Fatal** (`SIMPLIFY_LANGUAGE`/`STRUCTURE_DOCUMENT`, and `ground()`/`assemble_and_render()` per 03/04): no fallback exists because the step's output is exactly what the next step needs.

**Both `review()` and `correct()` are non-fatal**, the opposite classification from grounding/assembly, and deliberately so — the brief is explicit that "failing the job over a fidelity nit is the wrong trade" (§2.5 decision-log). Both have a real, safe fallback available, unlike grounding/assembly which have none once the prose passes are deleted:

- **`review()` fails or raises** → log loudly, skip `correct()` entirely, ship `assemble_and_render()`'s output as-is. The plan may carry uncorrected drift, which is a real, disclosed residual risk (§9) — but it is never less sound or more broken than what 04 already produced (04's own citation-existence check has already run and cannot be undone by review failing); review failing does not make the plan worse, only unimproved.
- **`correct()` fails, raises, or its diff check rejects** → log loudly (including the specific violated field, for observability) and fall back to the **pre-correction** `care_plan` (the one `review()` was shown). The reviewer's findings are lost for this run, but nothing fabricated by a misbehaving corrector ever ships — a stricter posture than review's fallback, matching the brief's explicit framing of the corrector as the design's acknowledged soft spot. There is no third deterministic pass after this one to fall through to (§4.7): 04's soundness check already ran, and the pre-correction `care_plan` this fallback returns to is by definition sound, since it's exactly what 04 produced.

**Budgets**: both `review` and `correct` use `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536) — `review`'s coverage list alone is one entry per ledger fact (the same scale as the ledger itself), and `correct`'s output is a full `CarePlan` (the same scale as assembly's). Both use `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2), matching every other structured-JSON call in this file (`ground`, `assemble_and_render`) — `correct`'s restyled values are still bounded, short-field substitutions, not free prose, so `TEMPERATURE_TEXT` is not appropriate here either.

## 5. API Change Summary

**No schema shape change** — 01 owns `CarePlanInternal`'s shape and it is unmodified by this PRD (`review`/`correct` both take and return `CarePlan`, never a different type). What changes is which *values* the pipeline can produce within that shape, once 06 wires these calls in:

| Behavior | Before this PRD (04 alone) | After |
|---|---|---|
| A field contradicting its fact (e.g. wrong dose) | Ships uncorrected | Corrected, or the item removed, if `correct()` succeeds |
| An item with no supporting fact | Already removed by 04's own citation-existence check (04 §4.4) before this PRD ever runs | Unchanged by this PRD — 04 already handles it; review/correct add fidelity correction on top |
| `summary` drifted from `summary_fact_ids` | Ships as assembled | May come back `""` (§4.2's `remove`-only rule) |
| Surviving clinician/facility name (04's rendering missed it) | Ships | Scrubbed by the corrector's PII sweep, if corrections ran at all |

`review()`/`correct()` are new, standalone methods; neither is called from anywhere yet (06's job), so no route, job-document shape, or `output_data` field changes as a direct effect of this PRD landing, mirroring 03 §5's identical posture.

## 6. Frontend Change Summary

**No new fields, no file changes** — 08's contract is 01's §6, unmodified here. One content-contract nuance for 08 to be aware of, a consequence of §4's decisions rather than a schema change:

- `summary` may now legitimately be `""` (§4.2/§4.5's `remove`-only rule for a drifted summary). 08 should render an empty "What You Need to Know" card the same way it already handles an empty `questions` array (`CarePlanView.tsx:284`'s existing `?.length > 0 &&` guard pattern) — hide the card, don't show an empty shell. Flagged here since it is this PRD, not 04, that makes an empty `summary` a real (if hopefully rare) production case rather than a theoretical default.

(An earlier draft of this PRD also flagged `low_priority` possibly carrying `"From your note: <fact text>"` safety-net lines from `close_coverage`. That mechanism is deleted — §4.7 — so `low_priority` only ever contains 04's own genuine low-priority one-liners; no 08 note needed.)

## 7. Testing

All new/changed tests live under `backend/tests/care_plan/` and `backend/tests/models/`, following the existing files' conventions (`CarePlanPipeline.__new__(CarePlanPipeline)` plus monkeypatched `_generate_json`).

### 7.1 `backend/tests/models/test_review.py` (new)

Round-trip `Correction`/`CoverageEntry`/`ReviewResult` through `to_dict()`/`from_dict()`; assert `extra="forbid"` rejects an unknown key on each. `Correction(op="correct", value=None)` validates at the model level (the requirement is enforced by `_sanitize_review_result`, not Pydantic) — assert that, paired with §7.2's test that the sanitizer drops it.

### 7.2 `backend/tests/care_plan/test_pipeline_review.py` (new)

- `_resolve_path`: finds a nested scalar (`"medications[1].dosage"`); returns `(False, None)`, never raises, for an out-of-range index and an unknown field name.
- `_sanitize_review_result`: drops a correction with an unresolvable path; drops `not_stated` outside the four `why` fields (and keeps it, parametrized, on each of the four); drops `correct` with no `value`; `remove` wins over a `correct`/`not_stated` targeting the same item; fills a coverage entry missing from a 3-fact ledger as `present=False`; drops a coverage entry citing an unknown `fact_id`.
- `review()`: runs `correct()` from `len(corrections) > 0` regardless of a contradicting `verdict="pass"` (§4.5's contract, asserted directly rather than inferred); uses `MAX_TOKENS_LONG_FORM`/`TEMPERATURE_JSON` (mirrors 03/04's identical test); rejects non-dict LLM output with `LLM_INVALID_JSON`.

### 7.3 `backend/tests/care_plan/test_pipeline_correct.py` (new) — the load-bearing file

**Correction application on fixtures** (parsing/formatting correctness, not model judgment): applies a `correct` op to exactly the named field; applies `not_stated` to exactly `"Not stated in your note."`; applies `remove` on an array item (array one shorter, right item gone) and on `"summary"` (`summary == ""`); returns the input unchanged with `_generate_json` never called when `corrections == []` (§4.6's short-circuit).

**The corrector-diff check — the single most load-bearing test group in this sub-project:**
- `test_diff_check_passes_when_only_named_field_changes` — one `correct` on `medications[0].dosage`; output changes exactly that field; no exception.
- `test_diff_check_rejects_change_to_unnamed_unrelated_field` — corrections name `medications[0].dosage`; output *also* changes `medications[1].frequency` (untouched, not PII-shaped); `PIPELINE_VALIDATION_FAILED`.
- `test_diff_check_passes_small_pii_substitution_on_eligible_field` — `medications[0].why` goes `"Prescribed by Doctor Alok Singh"` → `"Prescribed by your doctor"` (4-token delta), no correction naming it; passes under `_looks_like_pii_substitution`.
- `test_diff_check_rejects_large_rewrite_disguised_as_pii` — same field, but a wholly different longer sentence; delta exceeds `_MAX_PII_TOKEN_DELTA`; rejected despite being PII-eligible.
- `test_diff_check_rejects_pii_substitution_on_non_eligible_field` — a small-delta change to `medications[0].dosage` (not in `_PII_ELIGIBLE_FIELDS`); rejected — dosage/status/severity/urgency must never be "PII-swept".
- `test_diff_check_accounts_for_removed_array_length` — `remove` on `warning_signs[1]` and `[3]` (of 4); output has 2 items; the survivors are matched against original indices 0 and 2 and pass if otherwise unchanged.
- `test_diff_check_rejects_wrong_surviving_count` — same setup, output has 3 items (one expected removal didn't happen); rejected, message names the array.
- `test_diff_check_rejects_reordered_items` — no `remove` ops; same items, swapped order; rejected (positional diff reads a swap as "every field differs").
- `test_diff_check_rejects_change_to_source_fact_ids` — corrections name `medications[0].dosage` only; output *also* changes `medications[0].source_fact_ids` (e.g. drops an id); `PIPELINE_VALIDATION_FAILED`, since `source_fact_ids` is neither a named correction target nor in `_PII_ELIGIBLE_FIELDS` — the regression guard for §4.7's "no second coverage pass is needed after `correct()`" argument.
- `test_correct_raises_on_diff_violation_rather_than_silently_falling_back` — `correct()` itself raises; the fallback-to-pre-correction-plan behavior belongs to the *caller* (§4.8), not to `correct()`.

### 7.4 `close_coverage` tests are deleted, not replaced

`backend/tests/care_plan/test_pipeline_coverage_close.py` (and every test in it — the token-overlap fixture tests, `_flatten_care_plan_text`, `_fact_anchor_tokens`, the `_COVERAGE_OVERLAP_THRESHOLD` boundary case) is deleted along with `close_coverage()` itself (§4.7). The citation-existence property those tests indirectly protected is now covered by 04's own test suite (PRD 04 §7.4, "Soundness: `source_fact_ids`") and by this PRD's own `test_diff_check_rejects_change_to_source_fact_ids` (§7.3, above), which together are the load-bearing regression guard for the new contract: 04 proves the property holds when a `CarePlan` is first assembled, and this PRD proves `correct()` cannot break it afterward. No new test file replaces this one.

### 7.5 Testing whether the reviewer actually catches injected errors

Brief §5's own open-risk table names this directly: "the reviewer may rubber-stamp rather than catch errors — documented behaviour for LLM verifiers... inject known errors at a known rate... and measure catch rate." This cannot be a deterministic unit test — it requires a real model call and a judgment call on an acceptable catch rate, exactly like 03/04's real-note smoke tests (their §8). The concrete protocol:

1. Take 5–10 real or realistic de-identified notes already run through grounding + assembly, producing a known-good `(facts, care_plan)` pair per note.
2. Programmatically perturb the assembled `CarePlan` (never the ledger) with exactly the three injection categories the brief names: (a) delete one `medications[]` item entirely ("dropped medication"), (b) mutate one numeric field by a plausible-looking amount, e.g. `dosage: "25 mg"` → `"250 mg"` ("wrong dose"), (c) append one fabricated `follow_up[]` item with no corresponding fact ("invented follow-up").
3. Run the real `review()` call against `(facts, perturbed_care_plan)` for each of the ~30 perturbed cases (10 notes × 3 categories).
4. Score catch rate per category: for (a)/(c), did `coverage`/`corrections` flag the missing/invented item (a `remove` correction, or — for (a) specifically — the underlying dropped fact surfacing as `present: false` in `coverage`)? For (b), did `corrections` include a `correct` op on that exact path?
5. This is a script, not a `pytest` test (needs live Vertex AI credentials and human judgment on the resulting rate) — lives at `backend/tests/care_plan/manual_reviewer_catch_rate.py` or similar, run manually per §8, not part of CI. A catch rate materially below the 24.6%-omission / high-added-content-detection split the brief's cited research reports would be a signal the review prompt (§4.3) needs iteration before this sub-project's fidelity claims can be trusted in production — recorded as the acceptance bar, not enforced automatically.

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes**, once 06 wires these calls into the live pipeline (ngrok + pm2, `SERVICE_MODE=combined`): (a) confirm a deliberately-broken dose in a test note gets a `correct` op with the right value, not silently ignored; (b) confirm a fabricated warning sign gets `remove`d; (c) confirm the PII sweep catches a clinician name that slipped past 04's own rendering; (d) confirm a realistic ledger + care plan does not hit `LLM_MAX_TOKENS` at 65,536 on either call. Same reasoning as 03 §8/04 §8 — not automatable without a real model call and a judgment call on the output.
- **Run the injected-error catch-rate protocol (§7.5)** and decide whether the resulting rate is acceptable before treating review as a trustworthy fidelity backstop in production. This is explicitly a product judgment call, not a pass/fail this PRD can encode.
- **Tune `_MAX_PII_TOKEN_DELTA` (4)** against real notes once the corrector is exercised end-to-end — a disclosed, reasoned starting point (§9), not empirically derived. (`_COVERAGE_OVERLAP_THRESHOLD` no longer exists — the coverage heuristic it tuned is deleted; see §4.7, §9.)
- No new environment variables, credentials, or console configuration — this sub-project is prompt + pure Python only.

## 9. Open Questions & Decisions

- `[RESOLVED: the JSON path addressing scheme is dotted-field + 0-based [N] bracket-index, resolved against the pre-correction CarePlan's own array positions, shared verbatim by review.txt's instructions, correct.txt's instructions, and both post-validation layers.]` — see §4.2.
- `[RESOLVED: summary is remove-only in the correction vocabulary -- never a correct target.]` — a `correct` op's "supply the right value" is a values-swap for atomic fields, but for a bare, undecomposed prose field like `summary` it would mean the reviewer composing replacement prose, which directly violates "never rewrites... a reviewer permitted to write becomes a fourth author" (brief §2.5). `remove` (clear to `""`) is the only vocabulary member that fixes a drifted summary without writing new text. Alternative considered: let the reviewer supply full replacement summary text under `correct` — rejected as a direct boundary violation, not a judgment call.
- `[RESOLVED: not_stated is validated (and silently dropped if violated) to apply only to the same four why fields 04 scoped its sentinel to -- medications/tests/procedures/other[N].why.]` — keeps the reviewer's vocabulary from drifting wider than the one bug it was named for (PRD 04 §4.1's identical scoping rationale, reused here).
- `[RESOLVED: whether to run correct() is decided by len(corrections) > 0, not ReviewResult.verdict.]` — avoids a brittle dependency on the model's own internal consistency between two fields it emits in the same call.
- `[RESOLVED: the corrector-diff check tolerates a bounded (<=4 word-token) change on a fixed allow-list of PII-eligible fields, in addition to exact matches on named correction paths; anything else is rejected outright.]` — resolves a real tension in the brief's own text: "assert only fields named in the correction list changed" (the mitigation) versus "additionally scrubs any person or facility name that survived rendering" (the corrector's other explicit job) cannot both be satisfied by a strict named-paths-only diff, since PII can appear anywhere. The bounded-token-delta heuristic is the narrowest tolerance that satisfies both: broad enough to permit a real name swap anywhere, narrow enough that a disguised rewrite of an untouched field still gets caught. Alternative considered: route PII scrubbing through a second, separate LLM call with its own strict diff check — rejected because it would make five sequential LLM calls, one more than the brief's explicit, settled budget of four (§3.1).
- `[RESOLVED: remove and correct/not_stated cannot both target the same array item; remove wins and the other is dropped.]` — a defensive contradiction guard for reviewer output; a plausible model failure mode (flagging one item as both "wrong" and "unsupported"), not a case the prompt can fully prevent through instruction alone.
- `[RESOLVED: close_coverage() and its token-overlap heuristic (_COVERAGE_TOKEN_RE, _COVERAGE_OVERLAP_THRESHOLD, _flatten_care_plan_text, _fact_anchor_tokens) are deleted outright, not kept as a fallback and not reimplemented with a different heuristic.]` — an earlier draft of this PRD adopted the heuristic specifically because CarePlan items carried no per-item fact-id provenance (only summary_fact_ids did, per 01 at the time). That gap is now closed: 01 added source_fact_ids to all six item models, and 04 populates and deterministically verifies it at assembly time (04 §4.4). The heuristic's entire reason to exist — approximating a check that couldn't be done exactly — no longer applies, and the direction it checked (ledger→output completeness) is no longer even the project's contract (01 §9, 03 §9: soundness, not completeness). Superseded, not just improved: the previously `[DEFERRED]` item recommending "add source_fact_ids so this check can become exact" is resolved by that addition having already happened upstream, one layer earlier than this PRD, and owned entirely there — see §4.7.
- `[RESOLVED: _MAX_PII_TOKEN_DELTA stays at 4, a named, documented, tunable constant (§4.6) -- a reasoned starting point, not an empirically derived one.]` — the value distinguishes a targeted name/facility swap ("Doctor Alok Singh" → "your doctor", a 4-token change) from a disguised rewrite of a whole field; 4 was chosen to comfortably cover a full name plus title while staying well short of what a genuine sentence-level rewrite would produce, but it has not been calibrated against real notes. Calibration is listed as a manual step (§8) to run once the corrector is exercised end-to-end, not blocked on here — this mirrors 03 §9's identical treatment of `_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH` (named, tunable, reasoned-not-derived) and 04 §9's treatment of the content-richness floor it reuses from 03. This resolves the half of the item previously left open here concerning this constant; the other half, `_COVERAGE_OVERLAP_THRESHOLD`, is moot — that constant no longer exists (above).
- `[DEFERRED: empirically measuring the reviewer's actual catch rate against injected errors on this app's real note distribution is out of this PRD's scope — the brief's own deferred-evaluation-harness Non-Goal applies here exactly as it does to 03's analogous open risks.]` — §7.5 specifies the protocol; running it and deciding on an acceptable threshold is manual (§8). (The prior version of this item also named "the coverage check's actual omission-detection rate" — moot now that the coverage check it referred to, `close_coverage`'s heuristic, is deleted; there is no completeness/omission check left in this PRD to measure a detection rate for.)
- `[RESOLVED: both review() and correct() are non-fatal steps with defined, safe fallbacks -- skip correction entirely if review fails; fall back to the pre-correction plan if correct fails or its diff check rejects.]` — direct application of the brief's explicit "failing the job over a fidelity nit is the wrong trade" guidance (§2.5), and the opposite classification from grounding/assembly (03/04), which have no safe fallback once the prose passes are deleted.
- `[RESOLVED: the shared style-rules text is extracted from 04's assemble_and_render.txt into a new _style_rules.txt fragment, loaded by both assemble_and_render and correct via one _STYLE_RULES constant, rather than duplicated into correct.txt.]` — a small, disclosed retrofit to a file 04 already owns the content of; needed because the brief names "the same style rules as the writer prompts" as part of the corrector's contract, and duplicating text invites drift on the next prompt edit.
