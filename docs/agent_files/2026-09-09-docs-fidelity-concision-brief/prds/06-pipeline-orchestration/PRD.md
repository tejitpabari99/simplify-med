# PRD 06 — Pipeline Orchestration

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5, §3.1, §3.7).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (schema, `Constants.Enums` deletions, the `summary_fact_ids`/`source_fact_ids` internal-provenance fields — §4.6), 02 (`Unit`, `resolve_units_from_job_doc`), 03 (`ground()`), 04 (`assemble_and_render()`, deletion of the three old methods/prompts), 05 (`review()`, `correct()`, and whichever of 04/05 lands the citation-existence check that replaces the deleted `close_coverage()` — §4.10), 07 (`curate_glossary_terms()`, `render_care_plan_text()`, `build_glossary_from_care_plan()`).
Depended on by: nothing (this is the integration point; 08 owns the result/PDF screens this PRD's step renumbering does not touch).

## 1. Problem

Every other sub-project builds one piece of the inverted pipeline and stops short of wiring it in — by design (each says so in its own §3/§9). Landed independently, 04 alone leaves `CarePlanPipeline.run()` throwing `AttributeError`: `iter_steps` (`backend/care_plan/pipeline.py:152-258`) still calls `self.simplify_language_with_term_plan`, `self.clarify_and_action`, `self.structure_appointment_note` by name, and 04 deletes all three. Nothing today calls `ground()`, `assemble_and_render()`, `review()`, `correct()`, or `curate_glossary_terms()` — they exist as tested, standalone units with no caller. (An earlier draft of 05 also specified a `close_coverage()` function here; it has since been deleted outright, per 05's own soundness-contract revision — see §4.10.)

Four further things are broken or missing that no single-step PRD owns:

- `Constants.Pipeline.PIPELINE_STEPS` (`backend/utils/constants.py:63-77`) still names `SIMPLIFY_LANGUAGE`/`CLARIFY_AND_ACTION`/`STRUCTURE_DOCUMENT`, with labels ("Simplifying language") that describe steps that no longer exist. The frontend's `ProcessingScreen.tsx` hardcodes its own copy of this same five-step list (`frontend/src/components/ProcessingScreen.tsx:25-35`) — nobody else read that file; PRD 08 was scoped to the result screen and PDF only.
- `PipelineRunResult`/`AdapterResult` (`backend/models/pipeline_events.py`) carry `simplified: str` and `clarified: str` — fields for pipeline stages that 04 deletes. `services/care_plan_pipeline.py:106` computes the "after" readability score from `event.clarified`, which stops existing the moment 04 lands.
- The API→worker boundary never learned about `units: list[Unit]` (02's contract) or `list[Fact]` (03's contract) — `resolve_units_from_job_doc(job)` (02) has no call site, and `run_care_plan_pipeline`/`iter_steps` still take a single `text: str` argument.
- `routes/worker.py`'s pre-persistence stripping (`worker.py:202-203`) only ever knew about two flat fields (`care_plan.raw`, `input.text`), removed via hand-written `.pop()` calls — it has no mechanism for `summary_fact_ids`/`source_fact_ids` (01's new internal-provenance fields, one flat and one nested one-per-item across six item lists). Verified by grep: `summary_fact_ids` has zero hits anywhere in `backend/` today, so nothing strips it yet — the moment 04 starts actually populating these fields with real fact ids, they leak straight into the API response, the frontend, and the PDF unless this PRD closes the gap (§4.6).

This PRD lands last because it is the only place that can see the whole shape at once: the new step sequence, its two new deterministic thread-safety questions (item D), the composite fatal/non-fatal policy across four independently-classified LLM steps, and the one frontend file (`ProcessingScreen.tsx`) that nobody else was briefed to touch.

## 2. Goals

- Rewire `iter_steps`/`run()` to call `ground → assemble_and_render → review → correct`, in that order, followed by the deterministic close (a citation-existence check that replaces the deleted `close_coverage`, then glossary re-detection), threading `units`/`facts`/`care_plan` through correctly, with glossary curation running on its own background thread from right after `detect_terms` until just before the deterministic close.
- Redefine `Constants.Pipeline.PIPELINE_STEPS` with the new six-member step enum and patient-facing labels, and update every consumer: `services/care_plan_pipeline.py`'s `_STEP_MARKER_MAP`, `utils/markers/markers.py`, `routes/worker.py`, `utils/firebase.py::complete_job`'s hardcoded final stage, and `frontend/src/components/ProcessingScreen.tsx`'s duplicated copy.
- Wire `units: list[Unit]` from job doc to pipeline call, and thread `list[Fact]` through the run.
- Redefine `pipeline_events.py`'s three pipeline-layer/two adapter-layer dataclasses to match what the new pipeline actually produces.
- Decide and implement the composite fatal/non-fatal policy across all six steps, consistent with each step-owning PRD's own classification.
- Wire the deterministic close in the right order: any post-`correct()` citation-existence check before glossary re-detection (neither 05 nor 07 settled the old `close_coverage`/glossary order, and nothing settles the new check's order either; §4.10 resolves it).
- Strip `summary_fact_ids`/`source_fact_ids` from the completed job's Firestore document at the same `routes/worker.py` call site that already strips `raw`/`input.text` (§4.6) — the fix PRD 01 specified but explicitly left for this PRD to land, since `routes/worker.py` is 06's file.
- Confirm the existing error taxonomy (no new `ErrorCode` members, per 03/04/05's own discipline) surfaces safely on the frontend for every new failure mode.
- Specify the full test plan, including the two test files (`test_pipeline_executors.py`, `test_pipeline_streaming.py`) that test the step machinery directly and are currently written entirely against the old five-step, three-LLM-call shape.

## 3. Non-Goals

- No prompt text, no LLM call bodies. `ground()`, `assemble_and_render()`, `review()`, `correct()`, `curate_glossary_terms()`, and whichever function replaces `close_coverage()` are taken as given, exactly as 03/04/05/07 specify them.
- No schema changes (01), no unitizer changes (02), no glossary data-file changes (07).
- No frontend changes beyond `ProcessingScreen.tsx` and the minimal `useJobSnapshot.ts` confirmation below — `CarePlanView.tsx`, `buildPdfHtml.ts`, `types/carePlan.ts` are 08's, unaffected by step renumbering.
- No clinical-fidelity evaluation, no per-PR preview environment (global out-of-scope).
- No new `ErrorCode` members (matches 03/04/05's footprint discipline — see §4.8).

## 4. Architecture Decisions

### 4.1 `backend/utils/constants.py` — the new step enum

Old → new:

| Old member | Old label | New member | New (patient-facing) label |
|---|---|---|---|
| `READ_NOTE` (1) | "Reading your note" | `READ_NOTE` (1) | "Reading your note" *(unchanged)* |
| `DETECT_TERMS` (2) | "Finding difficult and medical terms" | `DETECT_TERMS` (2) | "Finding difficult and medical terms" *(unchanged)* |
| `SIMPLIFY_LANGUAGE` (3) | "Simplifying language" | `GROUND` (3) | "Finding the facts in your note" |
| `CLARIFY_AND_ACTION` (4) | "Clarifying actions and numbers" | `ASSEMBLE_AND_RENDER` (4) | "Putting your care plan together" |
| `STRUCTURE_DOCUMENT` (5) | "Organizing your care plan" | `REVIEW` (5) | "Double-checking your care plan" |
| — | — | `CORRECT` (6) | "Finishing touches" |

```python
class PIPELINE_STEPS(Enum):
    """Named steps of the care-plan pipeline. Each member carries its
    1-based step number (`.number`) and its user-facing progress label
    (`.label`). Six members now, not five: the inverted pipeline (brief
    §2.5, §3.1) runs four sequential LLM calls (ground, assemble_and_render,
    review, correct) instead of three (simplify, clarify, structure).
    Labels are patient-facing progress copy — never name an internal
    concept ("grounding", "ledger", "citation check") the patient has no
    reason to see."""
    READ_NOTE           = (1, "Reading your note")
    DETECT_TERMS        = (2, "Finding difficult and medical terms")
    GROUND              = (3, "Finding the facts in your note")
    ASSEMBLE_AND_RENDER = (4, "Putting your care plan together")
    REVIEW              = (5, "Double-checking your care plan")
    CORRECT             = (6, "Finishing touches")

    def __new__(cls, number: int, label: str):
        obj = object.__new__(cls)
        obj._value_ = number
        obj.number = number
        obj.label = label
        return obj
```

`READ_NOTE` (1) is still never emitted as a `StepEvent` — it is set directly by `routes/worker.py`'s initial Firestore update (`"stage": 1`) before `run_care_plan_pipeline` is even called, exactly as today; it now covers OCR + unitization (both deterministic, both already complete by the time the worker starts) rather than just OCR. No code change needed at that call site beyond the comment (§4.6).

Glossary curation (07) gets **no numbered step**: it runs on a background thread with no `StepEvent` of its own (§4.3) — a progress-bar entry for it would either have to expose "curating your glossary" (internal, unrequested detail) or lie about when it actually happens (it spans steps 3 through 6). It is folded silently into whichever step is active when it finishes.

### 4.2 `backend/care_plan/pipeline.py` — `iter_steps` rewired

**Module docstring** (`pipeline.py:1-14`): replace the "three LLM steps" sentence (already flagged as 06's job by PRD 04 §4.2) and the `Steps: 1-5` list:

```
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
```

**Imports** (additive, alongside 03/04/05's own new imports):

```python
from concurrent.futures import ThreadPoolExecutor
from models.ledger import Unit
from utils.term_detection import (
    build_glossary_from_care_plan,      # 07 — replaces build_glossary_from_simplified_text
    curate_glossary_terms,               # 07
    detect_terms,
    format_abbreviations_for_prompt,
    format_medical_terms_for_prompt,
    format_substitution_candidates_for_prompt,
)
```

`build_glossary_from_simplified_text` is removed from the import list — 07 deletes the function itself.

**`iter_steps` signature** — old → new:

| | Old | New |
|---|---|---|
| Signature | `iter_steps(self, text: str, wrap_step=None)` | `iter_steps(self, text: str, units: list[Unit], wrap_step=None)` |

`text` stays (deterministic term detection, glossary curation's "propose" job, and grounding's abbreviation block all still need the flat string); `units` is added because `ground()` (03) takes `list[Unit]`, not text. **02 explicitly left this call site to 06** ("the actual call site inside the pipeline run is 06's to wire" — PRD 02 §4.7); this is that decision.

**Full new body:**

```python
def iter_steps(
    self,
    text: str,
    units: list[Unit],
    wrap_step: WrapStepFn | None = None,
) -> Generator[StepEvent | PipelineRunResult | PipelineStepError, None, None]:
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
    # alongside everything below (brief §3.1/§3.8) — see §4.3 for why the
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
        # Bundled under one progress-bar step deliberately (§4.1) — none of
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

        # Deterministic close (PRD 06 §4.10 settles the order): the
        # citation-existence check FIRST, glossary re-detection SECOND —
        # true regardless of what the check does to care_plan (append,
        # remove, or nothing at all; see §4.10). `check_citations` is a
        # provisional name for whatever 04 or 05 lands in place of the
        # deleted close_coverage (§4.10) — only this one line changes
        # once that name is final; if 04 ends up enforcing the property
        # inline inside assemble_and_render instead, this line is deleted
        # entirely rather than renamed (§4.10's second branch).
        care_plan = check_citations(care_plan, facts)

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
        # a second time (§4.3).
        glossary_executor.shutdown(wait=False)

    yield PipelineRunResult(care_plan=care_plan, term_data=term_data, raw_text=text)
```

`run(self, text: str) -> CarePlan` is now `run(self, text: str, units: list[Unit]) -> CarePlan` — identical body (`for event in self.iter_steps(text, units): ...`), only the call it forwards changes.

### 4.2a Evidence text after `Fact` drops `quote` (dependency on 04/05)

01/03's revision (landed alongside this pass) changed `Fact` from carrying a `quote: str` field to carrying `char_start`/`char_end` offsets into its cited `Unit.text` — the verbatim evidence text is now recovered on demand via `models.ledger.quote_for(fact, units_by_id)`, not read off the `Fact` object directly (01 §4.3, 03 §9). The practical question for this PRD: does anything `iter_steps` calls need `units_by_id` in scope to reach that text, and if so, where does it have to be threaded?

**Verified against the currently-landed 04 and 05 PRDs, by reading them in full: no call site needs it today.** `_format_facts_for_prompt` (04 §4.3, reused by `review()` per 05 §4.5) renders each fact as `f"[{fact.id}] {category}: {fact.text}"` — `fact.text`, never `fact.quote` or `quote_for(...)`. The now-deleted `close_coverage`'s anchor-token check (05 §4.7) likewise read only `fact.text`. Every consumer of `Fact` downstream of grounding — `assemble_and_render`, `review`, and the deleted `close_coverage` alike — uses the LLM-facing clause content (`text`), never the evidence excerpt; the offsets exist for grounding's own fabrication check (03 §4.3) and are not re-read by anything later in the pipeline. So as of this PRD landing, `assemble_and_render`, `review`, and `correct`'s signatures need no `units`/`units_by_id` parameter, and `iter_steps` needs no code change beyond what §4.2 already shows.

**The commitment this PRD makes for the case that changes.** `units` is already a parameter of `iter_steps` itself (§4.2's signature), so it is structurally in scope for the entire generator body, including every step after `GROUND` — nothing needs to be threaded "further" than it already reaches; there is no local-scope boundary here the way there is for `term_data` (§4.3 below). If a future revision of 04 or 05 adds a `units`/`units_by_id` parameter to `assemble_and_render`, `review`, or `correct` (because one of them starts calling `quote_for`), `iter_steps` builds `units_by_id = {u.id: u for u in units}` once, at the point that call site first needs it, and passes it alongside `facts` — a one-line addition to that call's lambda, not a restructuring of the generator. `units_by_id` is deliberately **not** pre-built speculatively in §4.2's code today, consistent with this PRD's own stance in §4.5 against an always-computed-but-unread value (the same "vestigial-surface pattern the brief argues against" reasoning) — it gets built only once a real consumer exists. Recorded `[RESOLVED]` in §9: this is a specified commitment, not an open question, even though the exact call site it eventually lands at is still 04/05's to determine.

### 4.3 Threading (task item D)

**Two separate executors, not one shared one.** `before_score`'s existing executor lives in `services/care_plan_pipeline.py` (the *adapter* layer) and is gated on `grading_enabled`. Glossary curation needs `term_data["preserve_and_define_terms"]`, which exists only inside `iter_steps`'s local scope in `care_plan/pipeline.py` (the *pure algorithm* layer) — PRD 07 §9 confirms this explicitly ("term_data is only visible inside `care_plan/pipeline.py::iter_steps`, not at the `services/care_plan_pipeline.py` adapter layer... this call's site is necessarily different"). Sharing one executor across the two layers would mean either (a) threading `term_data` out through a widened `StepEvent` payload used by exactly one background job, or (b) moving the before-score submission down into the pure algorithm file, which does not have `text`'s use case (readability scoring) as its concern at all. Both are worse than two small, independently-owned `ThreadPoolExecutor(max_workers=1)` instances, each shut down in its own layer. This is a deliberate, disclosed departure from "reuse the existing pattern" toward "reuse the existing *shape* of the pattern" — recorded `[RESOLVED]` in §9.

One acknowledged cost: `care_plan/pipeline.py`'s own docstring for `wrap_step` says instrumentation is attached "without the pipeline importing Flask or g" — `concurrent.futures` is stdlib, not Flask, so the letter of that promise holds, but the pure-algorithm file now owns a concurrency primitive it didn't before. Accepted as the smaller cost versus the alternatives above.

**`LLMClient` thread-safety.** `LLMClient.__init__` calls `vertexai.init(project=..., location=...)` (`utils/llm.py:49`) — a call that mutates SDK-global state and is not documented by Google as safe to call concurrently from multiple threads. The pipeline's own `self._llm = LLMClient()` (main thread) is already constructed by the time `iter_steps` runs; constructing a *second* `LLMClient()` for curation **inside the background thread** (i.e., inside `curate_glossary_terms`'s own `llm_client or LLMClient()` fallback) would race that construction against the main thread's in-flight `ground()`/`assemble_and_render()`/`review()`/`correct()` calls.

**Decision: construct the curation `LLMClient()` eagerly, on the main thread, synchronously, before `executor.submit(...)`** (shown in §4.2's code — `glossary_llm = LLMClient()` runs before `glossary_executor.submit(...)`). At that exact point in `iter_steps`, no other LLM call is in flight yet (grounding hasn't started), so this construction is naturally serialized with respect to every other `vertexai.init()` call in the process. If eager construction itself fails (bad credentials, network), `glossary_llm = None` is passed through; `curate_glossary_terms`'s own `llm_client or LLMClient()` fallback will then retry construction inside the thread and hit the identical failure deterministically (not a race — a real, reproducible failure), which its own try/except already catches and turns into "fall back to uncurated terms" (07 §4.3). No new code needed in `curate_glossary_terms` for this — the eager-construction pattern in `iter_steps` is the entire fix.

**Timeout.** `Constants.Deadlines.GLOSSARY_CURATION_TIMEOUT_S = 20` (new constant, alongside `SINGLE_JOB_INTERNAL_DEADLINE_S`). Curation starts immediately after `DETECT_TERMS`, before the four sequential LLM calls begin — by the time `iter_steps` reaches the deterministic close, curation has already had the entire duration of `ground` + `assemble_and_render` + `review` (+ optionally `correct`) to finish, so in the overwhelmingly common case `glossary_future.result(...)` returns immediately. The 20s ceiling is a safety net for the pathological case (a hung network call), sized so `SINGLE_JOB_INTERNAL_DEADLINE_S` (270s) + this timeout (20s) stays under `JOB_TIMEOUT_SECONDS_SINGLE` (300s, the outer HTTP-level ceiling) with 10s of margin. On timeout, fall back to uncurated terms and `shutdown(wait=False)` — the abandoned thread is harmless: it touches no shared mutable state (its own `LLMClient`, reads `term_data`/`text` which nothing else mutates concurrently) and its return value is simply never read.

### 4.4 `backend/services/care_plan_pipeline.py`

**Signature**: `run_care_plan_pipeline(text: str, units: list[Unit], metrics: Metrics, grading_enabled: bool, source_kind: str = "upload")`. New import: `from models.ledger import Unit`. The one call site, `pipeline.iter_steps(text, wrap_step=wrap_step)` → `pipeline.iter_steps(text, units, wrap_step=wrap_step)`.

**`_STEP_MARKER_MAP`** — old → new:

```python
_STEP_MARKER_MAP = {
    2: (Markers.CarePlan.FindMedicalTerms,   "find_medical_terms",  None),
    3: (Markers.CarePlan.Ground,             "ground",              "care_plan.ground"),
    4: (Markers.CarePlan.AssembleAndRender,  "assemble_and_render", "care_plan.assemble_and_render"),
    5: (Markers.CarePlan.Review,             "review",              "care_plan.review"),
    6: (Markers.CarePlan.Correct,            "correct",             "care_plan.correct"),
}
```

The `if step == 3: scope.add("input_chars", len(text))` special case (`care_plan_pipeline.py:87-88`) stays keyed on `3` — step 3 is still "the first step that processes the full document at scale" (now `GROUND` instead of `SIMPLIFY_LANGUAGE`), so the metric's meaning is preserved, only its underlying step changed identity.

**"After" readability score** (`care_plan_pipeline.py:106,110,131` — closes PRD 04 §9's flagged gap using PRD 07 §4.4's `render_care_plan_text`):

```python
elif isinstance(event, PipelineRunResult):
    if grading_enabled:
        before_score  = before_score_future.result()
        rendered_text = render_care_plan_text(event.care_plan)      # NEW — replaces event.clarified
        after_score   = score_text_safe(rendered_text, "after")

        def _grade(scope):
            SimplifyContext.from_g(function="grading").apply(scope)
            result = build_grading_with_before_after_score(before_score, text, after_score, rendered_text)
            ...
```

New import: `from utils.term_detection import render_care_plan_text`. `AdapterResult(...)` drops `clarified_text=event.clarified` (§4.5).

**PRD 07 §9's flagged open item**, restated for the record here since this is where it becomes observable: *"whether including short, non-sentence label fields (titles, dosage strings, timeframes) as their own paragraphs measurably skews the readability score's sentence-length statistics."* This PRD wires the call; it does not resolve the statistical question. See §9.

### 4.5 `backend/models/pipeline_events.py` (task item I)

| Dataclass | Old fields | New fields |
|---|---|---|
| `StepEvent` | `step, status, label` | unchanged |
| `PipelineRunResult` | `care_plan, term_data, simplified, clarified, raw_text` | `care_plan, term_data, raw_text` — `simplified`/`clarified` deleted outright, nothing replaces them |
| `PipelineStepError` | `step, exc` | unchanged |
| `AdapterStepEvent` | `step, status, label` | unchanged |
| `AdapterResult` | `care_plan, grading, raw_text, clarified_text` | `care_plan, grading, raw_text` — `clarified_text` deleted |
| `AdapterError` | `error_data` | unchanged |

**The ledger (`list[Fact]`) is deliberately NOT added to either dataclass**, departing from PRD 01 §4.1.4's suggested shape ("`units: list[Unit]` / `ledger: list[Fact]` fields once 02/03 exist"). Verified: every consumer of `facts` (grounding's own verification, `assemble_and_render`, `review`, `correct`, and the post-`correct()` citation-existence check that replaces `close_coverage` — §4.10) runs *inside* `iter_steps`, before the single `PipelineRunResult` yield at the end — nothing downstream of that yield (the adapter, the worker, metrics, tests) ever needs the ledger. PRD 01 flagged the *intended shape* so a future author wouldn't reach for `CarePlan.raw` (deleted) as the ledger's carrier; it did not mandate the field exist regardless of a consumer. Adding an always-unread field is exactly the vestigial-surface pattern the brief argues against for `additional_info`/`RawArtifacts` elsewhere — not reproducing it here. Recorded `[RESOLVED]` in §9, since this is a visible departure from a suggestion (not a requirement) in an upstream PRD.

`raw_text` is kept on both dataclasses even though nothing in `routes/worker.py` reads `pipeline_result.raw_text` today (verified by grep — only `.care_plan`/`.grading` are read) — it is not part of this PRD's brief to remove, and it remains a meaningful "the text this run processed" field for future observability. Not touched.

### 4.6 `backend/routes/worker.py`

```python
from services.care_plan_input import resolve_input_from_job_doc, resolve_units_from_job_doc   # NEW import
...
source_kind = job.input_source_kind
text = resolve_input_from_job_doc(job)
units = resolve_units_from_job_doc(job)     # NEW — PRD 02 §4.7's reconstruction, spent here
...
for event in run_care_plan_pipeline(text, units, metrics, grading_enabled, source_kind=source_kind):
```

Both derive from the same `job` object already in scope at that point (`job.input_text`, `job.input_provenance`) — no new Firestore read.

**Internal-provenance stripping — the exact call site.** `worker.py:195-203` currently reads:

```python
output_data.get("care_plan", {}).pop("raw", None)
output_data.get("input", {}).pop("text", None)
```

Three changes land here:

1. `output_data.get("care_plan", {}).pop("raw", None)` — PRD 01 §4.1.4 already flagged this as dead code once `raw` no longer exists on `CarePlan` at all. **Delete this line.**
2. `output_data.get("input", {}).pop("text", None)` — untouched; unrelated to `raw` or to fact-id provenance.
3. **New**: `summary_fact_ids` (a flat top-level key on `care_plan`) and `source_fact_ids` (nested one-per-item inside `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`) must also never survive to `output_data` — PRD 01 §4.1/§9: a fact-ID list is exactly as internal as the ledger it cites into, regardless of size (brief §3.10, "the ledger is never displayed," extended to anything that cites into it). PRD 01 sketched this as "two more `.pop()`-based lines" at this call site; verified against the real shape, that undercounts what the traversal actually needs. `source_fact_ids` lives one level inside a list, on six separate keys — a flat `.pop("source_fact_ids", None)` on the top-level `care_plan` dict does nothing (there is no such top-level key on `care_plan` itself) and would silently no-op forever, which is worse than doing nothing: it would look like the leak was closed when it wasn't. The real fix has to walk each of the six item lists.

**Decision: a named helper, not inline pops.** Two flat pops (`raw`, `input.text`) read fine inline at the call site; seven removals — one top-level key plus six nested list-walks — do not. Inlining all seven here would bury the one call site's "nothing pipeline-internal leaks past this point" invariant inside a block of loop boilerplate, at the exact spot a future reader most needs to trust it at a glance (this call site already does five other things: derive the output name, strip `input.text`, trim `grading.entries`, and call `complete_job`). A small, named, single-purpose helper keeps that invariant legible and gives it one place to extend if a future field ever needs the same treatment:

```python
def _strip_internal_provenance(care_plan: dict) -> None:
    """Remove fields that exist purely for the pipeline's own use --
    evidence citations into the grounding ledger -- and must never reach
    the API response, the frontend, or the PDF (brief §3.10; PRD 01
    §4.1/§9: a fact-ID list is exactly as internal as the ledger it cites
    into, regardless of size). Mutates `care_plan` (the
    `output_data["care_plan"]` dict, already a plain dict via
    `envelope.to_dict()` by the time this runs) in place.

    `summary_fact_ids` is one flat top-level key. `source_fact_ids` is
    nested one-per-item inside six separate item lists, so this cannot be
    a single `.pop()` the way `raw`'s removal could be -- each list has
    to be walked."""
    care_plan.pop("summary_fact_ids", None)
    for _key in ("medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
        for _item in care_plan.get(_key, []):
            _item.pop("source_fact_ids", None)
```

Defined once, module-level in `backend/routes/worker.py`, above `execute_job`. Call site (`worker.py:195-203`, replacing the two-line block quoted above):

```python
output_data.get("input", {}).pop("text", None)
_strip_internal_provenance(output_data.get("care_plan", {}))
```

**Rejected alternative: seven inline `.pop()`/loop lines at the call site, matching PRD 01 §4.1's literal sketch.** PRD 01's own text calls this "an implementation call for whoever lands it, not a mandate," and explicitly recommends a named helper once the count passes two flat removals — which it does here (one flat key, six nested lists). Inlining is the right call only while the removals stay flat and few, as `raw`/`input.text` did; it stops being the right call the moment one of the fields is nested inside a list this call site has to iterate to reach. Named and tested once (§7.3), the helper is also the one place a seventh internal-only field would get added later, rather than a third copy-pasted loop appearing at the call site.

Comment update (`worker.py:74`, "5-stage LLM pipeline a second time, double-billing every Vertex AI call it already made"): the redelivery-guard reasoning is unchanged in substance, but the pipeline is no longer 5-stage/3-LLM-call — update the comment to "the whole pipeline (four sequential LLM calls) a second time."

`"stage": 1` (`worker.py:104`, set at job start) is unchanged — `READ_NOTE` is still step 1.

### 4.7 `backend/utils/firebase.py::complete_job`

`complete_job`'s hardcoded `"stage": 5` (`firebase.py:246`) is the exact bug pattern this PRD's own step renumbering would otherwise silently reproduce — a magic number matching the *old* final step, now one short of the real final stage. Fix, and make it self-correcting against future renumbering:

```python
from utils.constants import Constants   # NEW import

...
update_fields: dict = {
    "status": "completed",
    "stage": Constants.Pipeline.PIPELINE_STEPS.CORRECT.number,   # was: "stage": 5
    ...
}
```

This is the concrete file the task means by "`JobDoc.stage` written by `backend/routes/worker.py`" (the value itself is set here, in `utils/firebase.py`, which `worker.py` calls via `complete_job`) — verified by reading; `worker.py` never sets the terminal `stage` value directly.

### 4.8 Error taxonomy (task item G)

**No new `ErrorCode` members.** 03, 04, and 05 each independently decided to reuse `LLM_INVALID_JSON` and `PIPELINE_VALIDATION_FAILED` for every new failure mode (invalid ground/assemble/correct output shape, empty verified ledger, diff-check rejection) rather than add per-step codes — verified consistent across all three, not a decision left to 06. Every other failure (`LLM_MAX_TOKENS`, Vertex quota/deadline errors, etc.) propagates through `LLMClient` unchanged and is already classified.

**Frontend surface, verified by reading (not assumed):**
- `frontend/src/types/errors.ts`'s `ApiErrorDetail`/`FirestoreJobError` are fully generic over `code`/`message`/`user_hint`/`retryable` — no per-code branching.
- `frontend/src/components/ResultScreen.tsx:64-73` renders `jobDoc.error_data?.user_hint ?? jobDoc.error_data?.message ?? '<generic fallback>'` and logs `{ error_code, stage_reached: jobDoc.stage }` to analytics — a grep across `frontend/src` for any `switch`/`case` keyed on an `ErrorCode` value or any hardcoded error-code string found none outside this generic path.
- `ERROR_CATALOG[ErrorCode.PIPELINE_VALIDATION_FAILED].user_hint` ("An internal error occurred while validating the AI output. Please try again.") already reads correctly for a grounding, assembly, or correction failure — it was written generically, not tied to the old structuring step's name.

**Conclusion: zero frontend changes needed for error handling.** A grounding or assembly failure (now fatal, stage 3 or 4) renders exactly like today's structuring failure did (stage 5) — a generic, non-blank message and a "Start over" button — and `stage_reached` in analytics now naturally reports up to 6. This is a confirmation, not a new implementation; recorded `[RESOLVED]` in §9.

### 4.9 Fatal vs. non-fatal composite policy (task item H)

Each PRD classified its own step; consistency check across all four:

| Step | Classification | Source | Fallback |
|---|---|---|---|
| `DETECT_TERMS` | non-fatal (unchanged) | existing code | empty term lists |
| `GROUND` | **fatal** | PRD 03 §4.6 | none — no whole-document prose survives to fall back to |
| `ASSEMBLE_AND_RENDER` | **fatal** | PRD 04 §4.5 | none, same reasoning |
| `REVIEW` | **non-fatal** | PRD 05 §4.8 | skip `correct()`, ship assembly's output |
| `CORRECT` | **non-fatal** | PRD 05 §4.8 | revert to the pre-correction `care_plan` |
| glossary curation | non-fatal, self-contained (never raises) | PRD 07 §4.3 | uncurated detected-term list |

**No contradiction found** — every PRD's classification is mutually consistent, and the reasoning composes cleanly: the two steps with no possible fallback (because the prose passes that used to provide one are deleted) are fatal; the two steps whose whole purpose is *catching* problems in an already-usable result are non-fatal, per the brief's explicit "a fidelity nit must not cost the user their whole result" (§2.5). This is the implemented policy in §4.2's code.

**Resolves a task-brief note directly**: "Term detection currently fails open; the clarify step currently falls back — that fallback disappears with the step." Confirmed: `CLARIFY_AND_ACTION`'s old non-fatal fallback (revert to `simplified` text) has no equivalent in the new pipeline, because there is no prose stage left for it to fall back to — it is not preserved anywhere, and nothing replaces it in kind. What *does* replace it, structurally, is `REVIEW`/`CORRECT`'s new non-fatal fallback pattern, positioned differently (after assembly, not between two prose passes) and serving a different purpose (undoing a bad correction, not substituting one rewrite for another). `DETECT_TERMS`'s fail-open behavior is untouched and remains the pipeline's only deterministic-step fallback.

### 4.10 Deterministic close ordering (task item F)

**`close_coverage` (05) is deleted outright, not just reordered.** 05's token-overlap completeness heuristic (`_COVERAGE_OVERLAP_THRESHOLD`, `_flatten_care_plan_text`/`_fact_anchor_tokens`) implemented the project's old "does every fact survive somewhere in the output" contract. The project-wide inversion (01 §9, 03 §9) retires that contract entirely: omission is no longer mechanically checkable now that the assembly LLM (04) is trusted to select what belongs in a patient-facing report under its AHRQ-guided prompt, and the only property left that's mechanically enforceable is **soundness** — every emitted item cites at least one real fact via `source_fact_ids`, and every cited id actually exists in the ledger. Whatever function checks that property is what takes `close_coverage`'s old place in the sequence. This PRD's code (§4.2) calls it `check_citations(care_plan, facts) -> CarePlan` as a **provisional name** — which of 04 or 05 owns the real implementation, and under what name, is explicitly the other agent's call to make, not this PRD's (per the task's own framing of that division).

**Decision: whatever this check turns out to be, it still runs before glossary re-detection.** The original justification for `close_coverage`-then-glossary — `close_coverage` could *append* new `low_priority` lines, and `render_care_plan_text` (07 §4.4), the function glossary re-detection scans, walks `care_plan.low_priority` — no longer applies verbatim, because the new citation-existence check may not append anything observable at all: it might log-only, might strip an unsound `source_fact_ids` entry, or might do nothing to `care_plan`'s visible text whatsoever (04/05's call, not this PRD's). But the ordering argument generalizes past the specific mechanism: `render_care_plan_text` must see the CarePlan's *actually final* text, and `correct()` is the last LLM step — nothing after it except this citation check and glossary re-detection can still touch `care_plan`. Whichever of those two runs last is therefore the one whose output the other one might miss; putting the citation check first means glossary re-detection always sees whatever the citation check did (append, remove, or nothing), never the reverse. This "verify/finalize before you decorate" ordering holds regardless of which of the three behaviors 04/05 pick, so it does not need to be re-litigated once their choice is known.

**Dependency on 04/05's ownership decision, both sides specified so 06 is not blocked on it:**
- **If 05 lands it as a standalone deterministic function** — the direct structural replacement for `close_coverage`: same file, same "runs after `correct()`, takes `care_plan` and `facts`, returns `CarePlan`" shape — `iter_steps` calls it exactly where §4.2's code shows, under whatever its real name turns out to be. This PRD's sample name (`check_citations`) is provisional; landing it is a one-line rename in §4.2, not a re-design.
- **If 04 lands it as an assembly-time invariant instead** — i.e., `assemble_and_render` itself is made responsible for never returning an item that fails the citation check, enforced before it returns — there is no separate call for `iter_steps` to make at all. The deterministic close in that case is glossary re-detection alone, and §4.2's code loses the `check_citations(...)` line entirely (a deletion, not a rename). The ordering question dissolves along with the call site: there is nothing left to order against glossary re-detection.

Both outcomes are fully compatible with this PRD's own contract: `iter_steps` needs either one call (05 owns it) or zero calls (04 owns it) at this point in the sequence, and which one is not knowable until 04/05 land. Recorded `[RESOLVED]`, not `[OPEN]`, in §9 — the actionable policy ("if there's a standalone check function, call it before glossary re-detection; if there isn't, there's nothing to wire") is fully specified either way; only a one-line edit to §4.2's code remains contingent on which PRD lands it, which is a naming/deletion detail, not an unresolved design decision.

### 4.11 `backend/utils/markers/markers.py`

`SimplifyLanguage`, `ClarifyActions`, `StructureNote` (three leaves matching the three deleted methods) are deleted; four leaves matching the four new methods are added. `FindMedicalTerms` is unchanged. `ReadInput`/`SaveOutput` (both already unused today, verified by grep) are pre-existing dead code, out of this PRD's scope to clean up.

```python
class CarePlan:
    class ReadInput(CodeMarker): pass          # unchanged, pre-existing, unused
    class FindMedicalTerms(CodeMarker): pass    # unchanged

    @code_marker("care_plan.ground")
    class Ground(CodeMarker): pass

    @code_marker("care_plan.assemble_and_render")
    class AssembleAndRender(CodeMarker): pass

    @code_marker("care_plan.review")
    class Review(CodeMarker): pass

    @code_marker("care_plan.correct")
    class Correct(CodeMarker): pass

    class SaveOutput(CodeMarker): pass          # unchanged, pre-existing, unused
    class Pipeline(CodeMarker): pass            # unchanged
```

## 5. API Change Summary

No HTTP route, request, or response shape changes. `JobDoc.stage`'s *range* changes from `1..5` to `1..6` — this is a Firestore field the frontend already reads as a bare `number | null` with no hardcoded ceiling (`useJobSnapshot.ts` — confirmed, §6). `error_data.details` may now name `ground`/`assemble_and_render`/`correct` in free-text detail strings where it used to name `structure_appointment_note`/`simplify_language`/etc. — these are developer-facing `message`/`details_template` strings, never the patient-facing `user_hint` (§4.8), so no behavior change reaches the patient.

## 6. Frontend Change Summary

**`frontend/src/components/ProcessingScreen.tsx`** — its own hardcoded five-entry `PIPELINE_STEPS` array (line 25) and `STEP_KEYS` map (line 33) become six entries, mirroring §4.1's backend labels (the two copies are independent — no shared source, kept in sync by convention today and by this PRD going forward, §9):

```typescript
const PIPELINE_STEPS: Omit<PipelineStep, 'status'>[] = [
  { id: 1, label: 'Reading your note', description: 'Extracting text from your input' },
  { id: 2, label: 'Finding difficult and medical terms', description: 'Matching terms from AHRQ and medical dictionary' },
  { id: 3, label: 'Finding the facts in your note', description: 'Pulling out what your note actually says' },
  { id: 4, label: 'Putting your care plan together', description: 'Organizing everything into plain language' },
  { id: 5, label: 'Double-checking your care plan', description: 'Comparing it against your note for accuracy' },
  { id: 6, label: 'Finishing touches', description: 'Making final corrections and adding glossary terms' },
];

const STEP_KEYS: Record<number, string> = {
  1: 'read_note', 2: 'find_terms', 3: 'ground', 4: 'assemble_render', 5: 'review', 6: 'correct',
};
```

No other change to `ProcessingScreen.tsx` — `stepsFromStage`, `stepIcon`, the watchdog, the live-region text, and the JSX structure are all already generic over the array's length and contents (verified by reading: `PIPELINE_STEPS.length` in the live-region string at line 104 is not a hardcoded `5`).

**`frontend/src/hooks/useJobSnapshot.ts`** — confirmed by reading: `stage: data.stage ?? null` is a bare pass-through with no hardcoded step count or range check anywhere in the file. **No code change required.** This is the explicit confirmation the task asked for (item C names this file as affected by the renumbering); the renumbering is absorbed entirely by `ProcessingScreen.tsx`'s own array.

**`frontend/src/components/ResultScreen.tsx`** — no change (§4.8): its error rendering and `stage_reached` analytics field are already generic over the stage number and error code.

This crosses into 08's file territory in one place only: `frontend/src/types/carePlan.ts`'s `PipelineStep` interface (`id, label, description, status`) is unchanged and untouched by this PRD — `ProcessingScreen.tsx` is not in 08's file list (08 §3 scopes to the result view and PDF), so no coordination conflict, but flagged per the task's explicit instruction to note the crossing.

## 7. Testing

### 7.1 `backend/tests/care_plan/test_pipeline_streaming.py` — full rewrite

Every test in this file (`_make_pipeline`, all seven test functions) is built around the old three-mocked-method, five-step shape. Rewrite `_make_pipeline` to mock the new surface:

```python
def _make_pipeline(monkeypatch):
    import care_plan.pipeline as pipeline_module
    p = CarePlanPipeline.__new__(CarePlanPipeline)
    p.ground = MagicMock(return_value=[FACT_FIXTURE])
    p.assemble_and_render = MagicMock(return_value=CARE_PLAN_FIXTURE)
    p.review = MagicMock(return_value=ReviewResult(verdict="pass", corrections=[]))
    p.correct = MagicMock(return_value=CARE_PLAN_FIXTURE)
    monkeypatch.setattr(pipeline_module, "detect_terms", lambda text: {...})
    monkeypatch.setattr(pipeline_module, "check_citations", lambda cp, facts: cp)
    monkeypatch.setattr(pipeline_module, "curate_glossary_terms", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline_module, "build_glossary_from_care_plan", lambda cp, terms: {})
    monkeypatch.setattr(pipeline_module, "LLMClient", lambda: MagicMock())
    return p
```

`ReviewResult(...)` above deliberately omits a `coverage=` kwarg: 05's own soundness-contract revision (§4.10) may drop that field from `ReviewResult` entirely, or keep it for telemetry only (05 §4.7's own "review's coverage judgments are used for logging/telemetry only" framing). `coverage` already defaults to `[]` on `ReviewResult` today, so omitting the kwarg constructs correctly either way — this fixture doesn't need to know which 05 lands. `check_citations` is the same provisional name used in §4.2/§4.10; if 04 ends up enforcing the property inline instead (§4.10's other branch), this monkeypatch line is simply removed, since there is no such module-level function to patch.

New/rewritten tests:
- `test_iter_steps_yields_step_events_in_order` — assert `[(2,active),(2,done),(3,active),(3,done),(4,active),(4,done),(5,active),(5,done),(6,active),(6,done)]` (six steps, ten events).
- `test_iter_steps_yields_pipeline_run_result` — assert `result_events[0].care_plan is CARE_PLAN_FIXTURE` and `.term_data`/`.raw_text` are populated; assert **no** `.simplified`/`.clarified` attribute exists (`hasattr(...) is False`) as a regression guard.
- `test_iter_steps_wrap_step_called_per_step` — `calls == [2, 3, 4, 5, 6]`.
- `test_iter_steps_ground_failure_yields_step_error` (renamed from the old step-3 test) — `p.ground = MagicMock(side_effect=RuntimeError(...))`; assert `PipelineStepError(step=3)`, no `PipelineRunResult`.
- `test_iter_steps_assemble_and_render_failure_yields_step_error` — same shape, `step=4`.
- `test_iter_steps_review_failure_is_non_fatal` (replaces the old step-4-falls-back-to-simplified test) — `p.review = MagicMock(side_effect=RuntimeError(...))`; assert no `PipelineStepError`, `p.correct` is never called, and `PipelineRunResult` is still yielded.
- `test_iter_steps_correct_failure_falls_back_to_pre_correction_plan` — `review` returns one correction, `p.correct = MagicMock(side_effect=RuntimeError(...))`; assert no `PipelineStepError`, and `PipelineRunResult.care_plan` equals what `assemble_and_render` returned (not what `correct` would have, since it never successfully ran).
- `test_iter_steps_skips_correct_call_when_no_corrections` — `review` returns `corrections=[]`; assert `p.correct` is never invoked, but `StepEvent(step=6, ...)` is still yielded both active and done.
- `test_run_delegates_to_iter_steps` — `p.run("text", units=[])`, assert `isinstance(result, CarePlan)`.
- New: `test_glossary_executor_is_shut_down_even_on_fatal_ground_failure` — monkeypatch `ThreadPoolExecutor` to a spy; `p.ground` raises; assert `.shutdown(wait=False)` was called exactly once (proves the `finally` block fires on the early-return path, §4.2).
- New: `test_citation_check_runs_before_glossary_redetection` — monkeypatch both `check_citations` (or whatever 04/05 lands, §4.10) and `build_glossary_from_care_plan` to append to a shared `order: list[str]`; assert `order == ["check_citations", "build_glossary_from_care_plan"]` (proves §4.10's ordering decision is actually implemented, not just documented). If 04 ends up enforcing the citation check inline with no separate `iter_steps` call (§4.10's other branch), this test has nothing to monkeypatch on the citation-check side and is dropped — the ordering claim in that case is vacuously true, since there is no second deterministic call left to order against glossary re-detection.

### 7.2 `backend/tests/care_plan/test_pipeline_executors.py` — targeted rewrite

`FakePipeline`/`FailingPipeline`'s `iter_steps` signatures gain `units` (`def iter_steps(self, text, units, wrap_step=None)`); `run_care_plan_pipeline(...)` calls in every test gain a `units=[]` (or positional `[]`) argument. `_make_run_result` drops `simplified=`/`clarified=` kwargs (`PipelineRunResult` no longer has them). `test_grading_enabled_still_computes_before_and_after_scores` and `test_before_score_submitted_before_pipeline_construction` currently assert `mock_score.call_args_list` contains `("clarified", "after")` — rewrite to assert against `render_care_plan_text(care_plan_fixture)`'s known output (monkeypatch `render_care_plan_text` to a fixed stub string and assert that string appears, rather than asserting on a literal `"clarified"` that no longer has meaning).

### 7.3 `backend/tests/routes/test_worker.py` — mechanical updates

Every `AdapterResult(care_plan=..., grading=..., raw_text=..., clarified_text="c")` call site (~10 occurrences, grep-confirmed) drops `clarified_text="c"` — `AdapterResult` no longer has that field (§4.5). `run_care_plan_pipeline` patches in this file (`patch("routes.worker.run_care_plan_pipeline", ...)`) already use a `lambda *a, **kw: fake_pipeline(*a, **kw)` pass-through pattern — confirmed these tolerate the new `units` positional argument with no signature change needed on the test's side, since `resolve_units_from_job_doc` also needs to be mocked/monkeypatched wherever `job` is a bare mock without real `input_text`/`input_provenance` — add `monkeypatch.setattr("routes.worker.resolve_units_from_job_doc", lambda job: [])` (or equivalent per-test mock) to every test that reaches the pipeline call, alongside the existing `resolve_input_from_job_doc` mocking already present. The "5-stage LLM pipeline" comment reference at line 856 (a docstring, not an assertion) gets the same wording update as `worker.py:74` (§4.6).

**New tests, proving §4.6's stripping fix.** Extend `test_job_completed_output_has_no_raw`'s exact pattern (`test_worker.py:425-463`) — same invariant ("nothing pipeline-internal survives to `output_data`"), different fields, same fixture/mock shape (`_make_job_doc_with_pdf_upload`, a `fake_pipeline` yielding `AdapterResult`, `envelope_mock.to_dict.return_value` carrying the field to be stripped, then asserting on `mock_complete.call_args.args[1]`):

- `test_job_completed_output_has_no_summary_fact_ids` — `envelope_mock.to_dict.return_value["care_plan"]` carries `"summary_fact_ids": [1, 2, 3]` alongside a real field (e.g. `reason_for_visit`); assert `"summary_fact_ids" not in saved_output_data["care_plan"]`.
- `test_job_completed_output_has_no_source_fact_ids` — `care_plan` carries at least one populated item per list that gets one (e.g. `"medications": [{"title": "Metoprolol", "source_fact_ids": [4]}]`, `"tests": [{"title": "CBC", "source_fact_ids": [5]}]`); assert `"source_fact_ids" not in saved_output_data["care_plan"]["medications"][0]` and the same for `"tests"][0]`. Covering two of the six item lists (not all six) is enough to prove the loop in `_strip_internal_provenance` runs across keys, not just the first one — the unit test below covers all six exhaustively.

**New unit tests, on the helper directly (no Flask app, no mocks)** — `backend/tests/routes/test_worker.py` or a `test_worker_helpers.py` alongside it, whichever this repo's convention prefers for a pure function in `routes/worker.py`:

- `test_strip_internal_provenance_removes_summary_and_all_six_source_fact_ids` — build a dict with `summary_fact_ids` at the top level and one item (each carrying its own `source_fact_ids` plus an unrelated field, e.g. `title`) in every one of `medications`/`tests`/`procedures`/`other`/`follow_up`/`warning_signs`; call `_strip_internal_provenance(care_plan)`; assert `"summary_fact_ids" not in care_plan` and `"source_fact_ids" not in item` for all six items, while every unrelated field (`title`, etc.) survives untouched — the exhaustive, all-six-lists version of the two worker-level tests above.
- `test_strip_internal_provenance_tolerates_missing_keys` — an empty dict, and a dict with only some of the six item-list keys present; assert no `KeyError`/exception either way (`.get(_key, [])` is what makes this safe — this test pins that behavior).

### 7.4 `backend/tests/routes/test_jobs_e2e_scenarios.py`

PRD 01 §7.1 already fixed `_build_care_plan`'s construction-time breakage (deleted-field kwargs) and explicitly deferred "recalibrating that file's document-size-budget thresholds" to 06. With `RawArtifacts`'s ~9,000-char padding gone (01) and no replacement padding added by this PRD, every size-budget assertion in this file needs re-deriving against the new realistic maximum document size. **Recalibration**: the ledger/units are never persisted (01 §4.1.4, 02 §4.1) so they contribute nothing to `output_data`'s size; the only size growth versus the old 3-LLM-call output is `summary_fact_ids` (a handful of ints, ~20-40 bytes) and `*.status` (a handful of short string fields, ~15 bytes each × 5 item types × N items) — both negligible versus the ~9KB of padding removed. **New threshold**: lower every `MAX_TEXT_BYTES`-adjacent synthetic padding constant in this file's test fixtures by approximately the same ~9,000 chars `RawArtifacts` used to contribute, and re ‑verify the existing `< 1_048_576` (1 MiB) assertions still hold with real margin — do not simply keep the old numeric thresholds unexamined, since they were calibrated against a `raw` field that no longer exists. Also add `assert "input_provenance" not in doc` is already 02's addition (§7.3 there); this PRD adds `assert doc.get("stage") in (None, *range(1, 7))` as a light regression guard that no code path can write an out-of-range stage number after the renumbering.

### 7.5 `frontend/src/tests/components/ProcessingScreen.test.tsx`

- Line 11's `baseJobDoc` (`stage: 3`) now corresponds to `GROUND`, not `SIMPLIFY_LANGUAGE` — the test's own title ("renders steps 1-2 done, step 3 active, steps 4-5 waiting") and its `screen.getByText('Simplifying language')` assertion (line 23) both need updating: title becomes "...steps 4-6 waiting", assertion becomes `screen.getByText('Finding the facts in your note')`, and a fifth/sixth node check (`nodes[4]`, `nodes[5]`) is added for the now six-item `.step-node` list.
- Line 72's `'Step 3 of 5: Simplifying language'` → `'Step 3 of 6: Finding the facts in your note'`.
- Line 82's `'Step 4 of 5'` → `'Step 4 of 6'`.
- No other test in this file depends on step count or labels (the watchdog/terminal-state tests are step-content-agnostic).

### 7.6 Files checked and confirmed unaffected

- `frontend/src/hooks/useJobSnapshot.ts` and its test file (if any) — no hardcoded step count found (§6).
- `frontend/src/components/ResultScreen.tsx` and its tests — error/stage handling fully generic (§4.8).
- `backend/tests/utils/test_firebase.py::test_complete_job_unconditionally_clears_top_level_input_text` — does not assert on the literal `stage` value written, only on `input_text` deletion; unaffected by §4.7's change (spot-check recommended, not required).

## 8. Manual Intervention Required From You

- **End-to-end smoke test via ngrok + pm2 (`SERVICE_MODE=combined`)**, once every sub-project has landed: submit one real note and watch the processing screen through all six steps in order, confirm the final result renders, and confirm a deliberately-corrupted note (e.g., truncate it mid-sentence) produces a clean "Start over" error screen rather than a stuck spinner or a raw error code. This is the first point at which the full four-LLM-call chain runs together; no sub-project's own smoke test (03 §8, 04 §8, 05 §8, 07 §8) exercises the whole thing end-to-end.
- **Watch for the 20-second glossary-curation timeout firing in practice** (§4.3) during the above smoke test — if it fires under normal conditions (not a deliberately slow/broken note), the budget needs raising; this PRD's 20s figure is reasoned from the outer job-timeout ceiling, not measured against real Vertex AI latency.
- **Confirm `stage_reached` values 3-6 appear correctly in analytics** once real traffic flows, since the old dashboard/analytics queries (if any exist outside this repo) may have hardcoded assumptions about a 5-stage pipeline — outside this repo's visibility, flagged for awareness only.

## 9. Open Questions & Decisions

- `[RESOLVED: iter_steps gains a units: list[Unit] parameter; text is retained alongside it for detect_terms/glossary curation's own needs.]` — the concrete answer to PRD 02 §4.7's explicitly deferred call site.
- `[RESOLVED: glossary curation runs on its own ThreadPoolExecutor(max_workers=1), owned by care_plan/pipeline.py::iter_steps, separate from services/care_plan_pipeline.py's before-score executor.]` — see §4.3; term_data's visibility boundary (PRD 07 §9's own observation) makes a shared executor impractical without widening StepEvent's payload.
- `[RESOLVED: the curation LLMClient is constructed eagerly on the main thread, before executor.submit(...), specifically to avoid a concurrent vertexai.init() race with the pipeline's own already-constructed LLMClient.]` — the concrete answer to task item D's "check whether LLMClient is thread-safe": it is not documented as safe for concurrent construction, so construction is serialized instead of relying on it being safe.
- `[RESOLVED: close_coverage (05) is deleted outright, not replaced 1:1 -- its old completeness/omission contract is retired project-wide. Whatever citation-existence check replaces it (04's or 05's call, not this PRD's) still runs before glossary re-detection if it exists as a separate call at all; if 04 enforces the property inline inside assemble_and_render instead, there is no separate call and the ordering question dissolves.]` — neither 05 nor 07 settled the old close_coverage/glossary order, and nothing settles the new one either; §4.10 resolves both branches so this PRD is not blocked on an upstream decision it doesn't control.
- `[RESOLVED: iter_steps needs no units/units_by_id parameter threaded into assemble_and_render, review, or correct as of the currently-landed 04/05 PRDs -- verified by reading that every consumer of Fact downstream of grounding reads only fact.text, never fact.quote/quote_for(...), since Fact dropped its quote field for char_start/char_end offsets (01 §4.3, 03 §9). units already stays in scope for the whole iter_steps body regardless, since it's a parameter of the generator itself (§4.2). If a future 04/05 revision needs the evidence text, iter_steps builds units_by_id = {u.id: u for u in units} once, at the point of first need, and passes it alongside facts -- a one-line addition, not a restructuring.]` — see §4.2a.
- `[RESOLVED: PipelineRunResult/AdapterResult do NOT gain a ledger (list[Fact]) field, departing from PRD 01 §4.1.4's suggested shape.]` — no consumer exists downstream of the single PipelineRunResult yield; PRD 01's suggestion was guidance against reaching for CarePlan.raw, not a mandate for an always-unread field. See §4.5.
- `[RESOLVED: routes/worker.py's internal-provenance stripping gap -- summary_fact_ids was never stripped, and source_fact_ids (nested one-per-item across six item lists) was not reachable by any existing flat .pop() -- is closed here via a new _strip_internal_provenance(care_plan: dict) -> None helper, called at the exact call site the now-dead raw pop is deleted from.]` — PRD 01 introduced both fields with zero existing stripping mechanism to inherit (grep-verified zero hits on `summary_fact_ids` anywhere in `backend/` pre-01) and explicitly specified the fix while deferring its landing to 06, since `routes/worker.py` is 06's file per 01's own Non-Goals — the identical precedent 01 already set for deferring the dead `raw`-pop deletion to this same PRD. See §4.6.
- `[RESOLVED: no new ErrorCode members; verified by reading that the frontend's error handling is fully generic over code/user_hint with no per-code branching, so every new failure mode (grounding, assembly, correction-diff-rejection) renders safely with zero frontend changes.]` — task item G, resolved by confirmation rather than by adding taxonomy.
- `[RESOLVED: Constants.Deadlines.GLOSSARY_CURATION_TIMEOUT_S = 20, chosen so the internal deadline (270s) plus this timeout stays 10s under the outer job timeout (300s).]` — a reasoned default, not measured against real latency; flagged in §8 for a manual check.
- `[RESOLVED: utils/firebase.py::complete_job's hardcoded "stage": 5 becomes Constants.Pipeline.PIPELINE_STEPS.CORRECT.number, so a future step-count change can't silently reproduce this exact bug.]`
- `[RESOLVED: frontend/src/hooks/useJobSnapshot.ts needs no code change; frontend/src/components/ProcessingScreen.tsx's independent, hardcoded copy of the step list is the only frontend file requiring an edit for the renumbering.]` — confirmed by reading both files in full, per task item C.
- `[DEFERRED: PRD 07 §9's open item — whether render_care_plan_text's inclusion of short, non-sentence label fields skews the readability score's sentence-length statistics — is now directly observable via this PRD's wiring (§4.4), but resolving it requires scoring real before/after pairs from a live pipeline run, which is a manual/statistical exercise, not a design decision this PRD can settle.]` — if a skew is found, the fix narrows render_care_plan_text's field list for the readability consumer specifically (07's own noted escape hatch), which would be a small follow-up to 07, not a re-open of this PRD's wiring.
- `[DEFERRED: the two copies of the step-label list (backend Constants.Pipeline.PIPELINE_STEPS and frontend ProcessingScreen.tsx's PIPELINE_STEPS) remain independently maintained, kept in sync by convention only — as they already were before this PRD. Unifying them would require transmitting labels through JobDoc.stage (currently a bare int) or a separate config endpoint, which is a larger change than this renumbering warrants.]`
- `[OPEN]` — none blocking. Every decision this PRD's own scope required has a resolution above.
