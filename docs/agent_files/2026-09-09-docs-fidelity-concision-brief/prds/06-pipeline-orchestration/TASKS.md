# Tasks: Pipeline Orchestration

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema, `Constants.Enums` deletions, `summary_fact_ids`/`source_fact_ids`), 02 (`Unit`, `resolve_units_from_job_doc`), 03 (`ground()`), 04 (`assemble_and_render()`), 05 (`review()`, `correct()`), 07 (`curate_glossary_terms()`, `render_care_plan_text()`, `build_glossary_from_care_plan()`). This is the integration PRD — every task below assumes 01/02/03/04/05/07's own tasks have already landed in the repo (their model/service files and `CarePlanPipeline` methods exist), since this PRD is the only one that wires them together. Depended on by: nothing (08 owns the result/PDF screens; this PRD's step renumbering does not touch them).

**Known pre-existing breakage this PRD's tasks fix, not introduce**: per 07's own TASKS.md (its closing note) and 04's hand-off section, once 04's and 07's tasks have landed, `care_plan/pipeline.py` calls deleted methods/functions by name and the whole backend fails to import (`ImportError`/`AttributeError` cascading through `app.py`). This is expected and disclosed by 04/07 themselves — Task 4 below is what fixes it. Do not treat a red full-suite run as a regression before Task 4 lands; do treat it as the confirmation that Tasks 1-4 are landing in the right order.

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). Single file/test: `python -m pytest tests/care_plan/test_pipeline_streaming.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- Frontend tests: from `frontend/`, run `npx vitest run` (or the project's configured `npm test` script) — matches CI for `.tsx`/`.ts` changes.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions` (or, for the pure test tasks, `## 7. Testing`, which specifies exactly what those tests must assert); do not add fields, files, or behavior beyond what's cited.

---

### Task 1 — `backend/utils/constants.py`: the new six-member `PIPELINE_STEPS` enum + `GLOSSARY_CURATION_TIMEOUT_S`

   - Files: `backend/utils/constants.py`
   - Changes (PRD §4.1, §4.3):
     - Replace the current `class PIPELINE_STEPS(Enum):` block (currently `constants.py:63-79`, five members `READ_NOTE`/`DETECT_TERMS`/`SIMPLIFY_LANGUAGE`/`CLARIFY_AND_ACTION`/`STRUCTURE_DOCUMENT`) with:
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
       `class Pipeline:`'s `PIPELINE_VERSION: str = "v1-2"` line stays untouched, immediately above this enum.
     - In `class Deadlines:` (currently `SINGLE_JOB_INTERNAL_DEADLINE_S: int = 270`, `JOB_TIMEOUT_SECONDS_SINGLE: int = 300`), add a third line:
       ```python
       GLOSSARY_CURATION_TIMEOUT_S: int = 20
       ```
       (PRD §4.3: sized so `SINGLE_JOB_INTERNAL_DEADLINE_S` (270s) + this (20s) stays under `JOB_TIMEOUT_SECONDS_SINGLE` (300s) with 10s margin — do not change the other two values.)
   - Acceptance criteria:
     - `python -c "from utils.constants import Constants; s = Constants.Pipeline.PIPELINE_STEPS; assert [m.name for m in s] == ['READ_NOTE','DETECT_TERMS','GROUND','ASSEMBLE_AND_RENDER','REVIEW','CORRECT']; assert s.CORRECT.number == 6; assert s.GROUND.label == 'Finding the facts in your note'"` (from `backend/`) succeeds.
     - `python -c "from utils.constants import Constants; assert Constants.Deadlines.GLOSSARY_CURATION_TIMEOUT_S == 20"` succeeds.
     - `grep -n "SIMPLIFY_LANGUAGE\|CLARIFY_AND_ACTION\|STRUCTURE_DOCUMENT" backend/utils/constants.py` returns no hits.
     - The rest of the codebase (`care_plan/pipeline.py`, `services/care_plan_pipeline.py`, `utils/firebase.py`) still references the *old* member names at this point — that's fine and expected; Tasks 4/5/7 fix those call sites next.

### Task 2 — `backend/utils/markers/markers.py`: swap the three old step markers for four new ones

   - Files: `backend/utils/markers/markers.py`
   - Dependency: independent of Task 1; can land in either order, but land before Task 4 (which references `Markers.CarePlan.Ground` etc. only indirectly via `services/care_plan_pipeline.py` — actually Task 5 is the one that references these markers directly, so this must land before Task 5).
   - Changes (PRD §4.11): Inside `class CarePlan:`, replace these three leaves:
     ```python
     @code_marker("care_plan.simplify_language")
     class SimplifyLanguage(CodeMarker): pass

     @code_marker("care_plan.clarify_actions")
     class ClarifyActions(CodeMarker): pass

     @code_marker("care_plan.structure_note")
     class StructureNote(CodeMarker): pass
     ```
     with four new leaves:
     ```python
     @code_marker("care_plan.ground")
     class Ground(CodeMarker): pass

     @code_marker("care_plan.assemble_and_render")
     class AssembleAndRender(CodeMarker): pass

     @code_marker("care_plan.review")
     class Review(CodeMarker): pass

     @code_marker("care_plan.correct")
     class Correct(CodeMarker): pass
     ```
     `ReadInput`, `FindMedicalTerms`, `SaveOutput`, `Pipeline` (all four, with their existing `@code_marker(...)` decorators) are untouched — PRD §4.11 confirms `ReadInput`/`SaveOutput` are pre-existing, already-unused dead code, out of this PRD's scope to remove.
   - Acceptance criteria:
     - `python -c "from utils.markers import Markers; Markers.CarePlan.Ground; Markers.CarePlan.AssembleAndRender; Markers.CarePlan.Review; Markers.CarePlan.Correct"` (from `backend/`) succeeds.
     - `grep -n "SimplifyLanguage\|ClarifyActions\|StructureNote" backend/utils/markers/markers.py` returns no hits.
     - `python -c "from utils.markers import Markers; Markers.CarePlan.ReadInput; Markers.CarePlan.FindMedicalTerms; Markers.CarePlan.SaveOutput; Markers.CarePlan.Pipeline"` still succeeds unchanged.

### Task 3 — `backend/models/pipeline_events.py`: drop `simplified`/`clarified`/`clarified_text`

   - Files: `backend/models/pipeline_events.py`
   - Changes (PRD §4.5):
     - On `PipelineRunResult` (currently `care_plan, term_data, simplified, clarified, raw_text`), delete the `simplified: str` and `clarified: str` fields. Resulting dataclass:
       ```python
       @dataclass
       class PipelineRunResult:
           """Emitted once at the end of a successful pipeline run."""
           care_plan: CarePlan
           term_data: dict
           raw_text: str
       ```
       Nothing replaces `simplified`/`clarified` — do **not** add a `ledger`/`facts` field here (PRD §4.5's explicit, disclosed departure from PRD 01 §4.1.4's suggested shape: every consumer of `list[Fact]` runs inside `iter_steps`, before this dataclass is ever constructed, so nothing downstream needs it).
     - On `AdapterResult` (currently `care_plan, grading, raw_text, clarified_text`), delete the `clarified_text: str` field. Resulting dataclass:
       ```python
       @dataclass
       class AdapterResult:
           """Final result from the adapter; consumed by the worker to complete the job."""
           care_plan: CarePlan
           grading: Grading
           raw_text: str
       ```
     - `StepEvent`, `PipelineStepError`, `AdapterStepEvent`, `AdapterError` are all unchanged — do not touch them.
   - Acceptance criteria:
     - `python -c "import dataclasses; from models.pipeline_events import PipelineRunResult, AdapterResult; assert {f.name for f in dataclasses.fields(PipelineRunResult)} == {'care_plan','term_data','raw_text'}; assert {f.name for f in dataclasses.fields(AdapterResult)} == {'care_plan','grading','raw_text'}"` (from `backend/`) succeeds.
     - The rest of the codebase (`care_plan/pipeline.py`, `services/care_plan_pipeline.py`, and their tests) still constructs these with the *old* fields at this point — expected; Tasks 4, 5, 9, 10, 11, 12 fix those call sites next. `python -m pytest` will show real failures/errors until then; that's the expected transient state this task's own commit leaves behind (same "transient mid-pass invalidity" pattern PRD 01's TASKS.md establishes for its own Tasks 1-2).

### Task 4 — `backend/care_plan/pipeline.py`: rewire `iter_steps`/`run()` to the new four-LLM-call sequence

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Tasks 1, 2, 3, and after 01/02/03/04/05/07's own tasks (this file must already contain `ground()` (03), `assemble_and_render()` (04), `review()`/`correct()` (05) as real methods on `CarePlanPipeline`, and must no longer contain `simplify_language_with_term_plan`/`clarify_and_action`/`structure_appointment_note`, `_SIMPLIFY_PROMPT`/`_CLARIFY_PROMPT`/`_STRUCTURE_PROMPT`, per 04's own deletions). This task touches only the module docstring, the import block, and the `iter_steps`/`run()` methods — leave every other method, helper, or prompt-loading line that 03/04/05 already established (`_llm_schema`, `ground`, `assemble_and_render`, `review`, `correct`, their own prompt constants) exactly as those PRDs left them.
   - Changes (PRD §4.2, §4.2a, §4.3, §4.9, §4.10):
     - **Module docstring** (currently lines 1-14): replace the "three LLM steps" sentence and `Steps: 1-5` list with:
       ```
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
       ```
     - **Imports** — additive only, alongside whatever 03/04/05 already added to this file's import block:
       - Add `from concurrent.futures import ThreadPoolExecutor` (new, needed for glossary curation's own executor).
       - Confirm `from models.ledger import Unit` is present (03 likely already imports `Unit` alongside `Fact`/`FactCategory` for grounding — do not add a second, duplicate import line if so).
       - In the existing `from utils.term_detection import (...)` block, add `build_glossary_from_care_plan` and `curate_glossary_terms`, and **remove** `build_glossary_from_simplified_text` (07 deletes that function outright — leaving it imported raises `ImportError` at module load, which is exactly the breakage described in this file's header note above). Resulting import block:
         ```python
         from utils.term_detection import (
             build_glossary_from_care_plan,      # 07 — replaces build_glossary_from_simplified_text
             curate_glossary_terms,               # 07
             detect_terms,
             format_abbreviations_for_prompt,
             format_medical_terms_for_prompt,
             format_substitution_candidates_for_prompt,
         )
         ```
     - **Replace `iter_steps` and `run`** (currently `pipeline.py:152-267` in the pre-01/02/03/04/05 baseline; by this point in the sequence these two methods are the last remaining piece still shaped around the old three-LLM-call pipeline) with:
       ```python
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
       ```
     - This task deliberately does **not** thread `units`/`units_by_id` into `ground`/`assemble_and_render`/`review`/`correct`'s own call signatures beyond what's shown above — PRD §4.2a verified none of those calls need evidence-quote lookup as landed by 03/04/05 today. `units` stays in scope for the whole generator body regardless, since it's a parameter of `iter_steps` itself.
   - Acceptance criteria:
     - `python -c "import care_plan.pipeline"` (from `backend/`) succeeds with no `ImportError`.
     - `python -c "import inspect; from care_plan.pipeline import CarePlanPipeline; sig = inspect.signature(CarePlanPipeline.iter_steps); assert list(sig.parameters) == ['self','text','units','wrap_step']"` succeeds.
     - `grep -n "simplify_language_with_term_plan\|clarify_and_action(\|structure_appointment_note\|build_glossary_from_simplified_text" backend/care_plan/pipeline.py` returns no hits inside `iter_steps`/`run` (any remaining hits would only be from 04's own method-body naming choices, which this task doesn't touch).
     - Full behavior is exercised by Task 9's rewritten `test_pipeline_streaming.py` — this task's own acceptance criterion is "imports cleanly and matches the signature above"; do not hand-verify step-by-step behavior here since Task 9 does that exhaustively.

### Task 5 — `backend/services/care_plan_pipeline.py`: new signature, `_STEP_MARKER_MAP`, `render_care_plan_text`-based after-score

   - Files: `backend/services/care_plan_pipeline.py`
   - Dependency: land after Tasks 2 and 4 (needs the new `Markers.CarePlan.Ground`/etc. leaves and `CarePlanPipeline.iter_steps`'s new `units` parameter).
   - Changes (PRD §4.4):
     - Add import: `from models.ledger import Unit` and `from utils.term_detection import render_care_plan_text` (alongside the existing imports).
     - **Signature**: change
       ```python
       def run_care_plan_pipeline(
           text: str,
           metrics: Metrics,
           grading_enabled: bool,
           source_kind: str = "upload",
       ) -> Generator[AdapterStepEvent | AdapterResult | AdapterError, None, None]:
       ```
       to
       ```python
       def run_care_plan_pipeline(
           text: str,
           units: list[Unit],
           metrics: Metrics,
           grading_enabled: bool,
           source_kind: str = "upload",
       ) -> Generator[AdapterStepEvent | AdapterResult | AdapterError, None, None]:
       ```
     - **`_STEP_MARKER_MAP`** (currently lines 59-64) — replace:
       ```python
       _STEP_MARKER_MAP = {
           2: (Markers.CarePlan.FindMedicalTerms,   "find_medical_terms",  None),
           3: (Markers.CarePlan.SimplifyLanguage,   "simplify_language",   "care_plan.simplify_language"),
           4: (Markers.CarePlan.ClarifyActions,     "clarify_actions",     "care_plan.clarify_actions"),
           5: (Markers.CarePlan.StructureNote,      "structure_note",      "care_plan.structure_note"),
       }
       ```
       with:
       ```python
       _STEP_MARKER_MAP = {
           2: (Markers.CarePlan.FindMedicalTerms,   "find_medical_terms",  None),
           3: (Markers.CarePlan.Ground,             "ground",              "care_plan.ground"),
           4: (Markers.CarePlan.AssembleAndRender,  "assemble_and_render", "care_plan.assemble_and_render"),
           5: (Markers.CarePlan.Review,             "review",              "care_plan.review"),
           6: (Markers.CarePlan.Correct,            "correct",             "care_plan.correct"),
       }
       ```
       Leave the `if step == 3: scope.add("input_chars", len(text))` special case (inside `wrap_step`'s `_inner`) keyed on the literal `3` — unchanged, since step 3 is still "the first step that processes the full document at scale" (now `GROUND`, PRD §4.4).
     - **The one call site** — `pipeline.iter_steps(text, wrap_step=wrap_step)` becomes `pipeline.iter_steps(text, units, wrap_step=wrap_step)`.
     - **"After" readability score** — replace:
       ```python
       elif isinstance(event, PipelineRunResult):
           if grading_enabled:
               before_score = before_score_future.result()
               after_score  = score_text_safe(event.clarified, "after")

               def _grade(scope):
                   SimplifyContext.from_g(function="grading").apply(scope)
                   result = build_grading_with_before_after_score(before_score, text, after_score, event.clarified)
       ```
       with:
       ```python
       elif isinstance(event, PipelineRunResult):
           if grading_enabled:
               before_score  = before_score_future.result()
               rendered_text = render_care_plan_text(event.care_plan)      # NEW — replaces event.clarified
               after_score   = score_text_safe(rendered_text, "after")

               def _grade(scope):
                   SimplifyContext.from_g(function="grading").apply(scope)
                   result = build_grading_with_before_after_score(before_score, text, after_score, rendered_text)
       ```
       (the rest of `_grade`'s body — the `scope.add(...)` calls — is unchanged).
     - **`AdapterResult(...)` construction** (end of the `PipelineRunResult` branch) — drop the `clarified_text=event.clarified` kwarg:
       ```python
       yield AdapterResult(
           care_plan=event.care_plan,
           grading=grading,
           raw_text=event.raw_text,
       )
       ```
   - Acceptance criteria:
     - `python -c "import inspect; from services.care_plan_pipeline import run_care_plan_pipeline; sig = inspect.signature(run_care_plan_pipeline); assert list(sig.parameters) == ['text','units','metrics','grading_enabled','source_kind']"` (from `backend/`) succeeds.
     - `grep -n "SimplifyLanguage\|ClarifyActions\|StructureNote\|event.clarified\|clarified_text=" backend/services/care_plan_pipeline.py` returns no hits.
     - Full behavior exercised by Task 10's rewritten `test_pipeline_executors.py`.

### Task 6 — `backend/routes/worker.py`: wire `units`, add `_strip_internal_provenance`

   - Files: `backend/routes/worker.py`
   - Dependency: land after Task 5 (needs `run_care_plan_pipeline`'s new `units` parameter) and after 02's own tasks (needs `resolve_units_from_job_doc` to exist in `services/care_plan_input.py`).
   - Changes (PRD §4.6):
     - Import (line 18, alongside the existing `resolve_input_from_job_doc` import): change
       ```python
       from services.care_plan_input import resolve_input_from_job_doc
       ```
       to
       ```python
       from services.care_plan_input import resolve_input_from_job_doc, resolve_units_from_job_doc
       ```
     - Immediately after the existing `text = resolve_input_from_job_doc(job)` (currently line 119), add:
       ```python
       units = resolve_units_from_job_doc(job)     # NEW — PRD 02 §4.7's reconstruction, spent here
       ```
       Both derive from the same `job` object already in scope — no new Firestore read.
     - The pipeline call site (currently line 144): change
       ```python
       for event in run_care_plan_pipeline(text, metrics, grading_enabled, source_kind=source_kind):
       ```
       to
       ```python
       for event in run_care_plan_pipeline(text, units, metrics, grading_enabled, source_kind=source_kind):
       ```
     - **New module-level helper**, defined above `execute_job` (after the imports/blueprint setup, before the `# ── Job execution handler ──` comment):
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
     - Call site (currently lines 195-203, the block right before the grading-entries trim) — replace:
       ```python
       output_data.get("care_plan", {}).pop("raw", None)
       output_data.get("input", {}).pop("text", None)
       ```
       with:
       ```python
       output_data.get("input", {}).pop("text", None)
       _strip_internal_provenance(output_data.get("care_plan", {}))
       ```
       (the `.pop("raw", None)` line is deleted outright — it is dead code once `CarePlan.raw` no longer exists at all, per 01's own hand-off note; the surrounding comment block above these two lines can be updated to mention `summary_fact_ids`/`source_fact_ids` alongside `raw`/`input.text`, but that's optional prose, not load-bearing).
     - Comment update (currently line 74, "5-stage LLM pipeline a second time, double-billing every Vertex AI call it already made"): change "5-stage LLM pipeline" to "the whole pipeline (four sequential LLM calls)". The redelivery-guard reasoning around it is unchanged.
     - `"stage": 1` (currently line 104, set at job start) is unchanged — `READ_NOTE` is still step 1; no code change here beyond understanding it now also covers unitization.
   - Acceptance criteria:
     - `python -c "import routes.worker"` (from `backend/`) succeeds with no `ImportError`.
     - `grep -n 'pop("raw", None)' backend/routes/worker.py` returns no hits.
     - `grep -n "_strip_internal_provenance" backend/routes/worker.py` returns at least 2 hits (definition + call site).
     - `grep -n "5-stage" backend/routes/worker.py` returns no hits.
     - Full behavior (the stripping actually removing the two fields, and tolerating missing keys) is exercised by Task 11's new tests.

### Task 7 — `backend/utils/firebase.py::complete_job`: fix the hardcoded terminal stage

   - Files: `backend/utils/firebase.py`
   - Dependency: land after Task 1 (needs the new `CORRECT` member on `Constants.Pipeline.PIPELINE_STEPS`). Independent of Tasks 2-6; can land any time after Task 1.
   - Changes (PRD §4.7):
     - Add import: `from utils.constants import Constants` (new, alongside the existing `firebase_admin`/`flask`/`errors` imports at the top of the file).
     - In `complete_job` (currently `firebase.py:231-256`), change the hardcoded `"stage": 5,` (currently line 246) to:
       ```python
       "stage": Constants.Pipeline.PIPELINE_STEPS.CORRECT.number,   # was: "stage": 5
       ```
     - Do not touch `fail_job` — it has no equivalent hardcoded terminal-stage field (confirmed by reading; `fail_job` only sets `status`/`error_data`/`input_text: DELETE_FIELD`, no `stage`).
   - Acceptance criteria:
     - `python -c "from utils.firebase import complete_job"` (from `backend/`) succeeds (confirms no circular-import issue from the new `Constants` import — `utils/constants.py` imports nothing from `utils/firebase.py`, so this is safe).
     - `grep -n '"stage": 5' backend/utils/firebase.py` returns no hits.
     - `grep -n "Constants.Pipeline.PIPELINE_STEPS.CORRECT.number" backend/utils/firebase.py` returns one hit, inside `complete_job`.

### Task 8 — `frontend/src/components/ProcessingScreen.tsx`: six-step patient-facing list

   - Files: `frontend/src/components/ProcessingScreen.tsx`
   - Dependency: independent of every backend task above; can land at any point (frontend and backend renumbering are two independently-maintained copies per PRD §9's `[DEFERRED]` note — no shared source to keep them in sync beyond convention).
   - Changes (PRD §6): Replace the current five-entry `PIPELINE_STEPS` array (currently line 25) and `STEP_KEYS` map (currently line 33):
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
     No other line in this file changes — `stepsFromStage`, `stepIcon`, the watchdog, the live-region text, and the JSX are all already generic over the array's length/contents (verified by reading: the live-region string at line ~104 uses `PIPELINE_STEPS.length`, not a hardcoded `5`).
   - Acceptance criteria:
     - `grep -n "Simplifying language\|Clarifying actions\|Organizing your care plan" frontend/src/components/ProcessingScreen.tsx` returns no hits.
     - `grep -n "Finding the facts in your note\|Putting your care plan together\|Finishing touches" frontend/src/components/ProcessingScreen.tsx` returns three hits.
     - `STEP_KEYS` has exactly six numeric keys, `1` through `6`.
     - Full behavior exercised by Task 13's updated `ProcessingScreen.test.tsx`.

### Task 9 — Rewrite `backend/tests/care_plan/test_pipeline_streaming.py`

   - Files: `backend/tests/care_plan/test_pipeline_streaming.py`
   - Dependency: land after Task 4 (needs the new `iter_steps` signature/behavior).
   - Changes (PRD §7.1): Every test in this file is built around the old three-mocked-method, five-step shape and must be rewritten. Replace `_make_pipeline` with:
     ```python
     from models.review import ReviewResult

     def _make_pipeline(monkeypatch):
         import care_plan.pipeline as pipeline_module
         p = CarePlanPipeline.__new__(CarePlanPipeline)
         p.ground = MagicMock(return_value=[FACT_FIXTURE])
         p.assemble_and_render = MagicMock(return_value=CARE_PLAN_FIXTURE)
         p.review = MagicMock(return_value=ReviewResult(verdict="pass", corrections=[]))
         p.correct = MagicMock(return_value=CARE_PLAN_FIXTURE)
         monkeypatch.setattr(pipeline_module, "detect_terms", lambda text: {
             "substitution_candidates": [], "preserve_and_define_terms": [], "abbreviations": [],
         })
         monkeypatch.setattr(pipeline_module, "curate_glossary_terms", lambda *a, **kw: [])
         monkeypatch.setattr(pipeline_module, "build_glossary_from_care_plan", lambda cp, terms: {})
         monkeypatch.setattr(pipeline_module, "LLMClient", lambda: MagicMock())
         return p
     ```
     Define `FACT_FIXTURE` and `CARE_PLAN_FIXTURE` as module-level fixtures at the top of the file (not shown by the PRD verbatim — build them the same minimal way `test_pipeline_schema.py`/`test_pipeline_streaming.py`'s sibling test files construct minimal valid instances, e.g. `FACT_FIXTURE = Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")` from `models.ledger`, and `CARE_PLAN_FIXTURE = CarePlan(doc_type="care_plan", version=Constants.Schema.CARE_PLAN_VERSION, summary="...")` — a minimal instance is sufficient since these tests only check identity (`is CARE_PLAN_FIXTURE`) and step-event sequencing, never field contents). `ReviewResult(...)` deliberately omits `coverage=` — it defaults to `[]` (05 §4.1) and nothing in `iter_steps` branches on it.

     Every call to `p.iter_steps(...)`/`p.run(...)` in this file's tests must also pass `units=[]` (or a positional `[]`) as the new required second argument — e.g. `list(p.iter_steps("input text", []))`, `p.run("text", units=[])`.

     Rewrite/add the following tests (replacing the old `test_iter_steps_step3_failure_yields_step_error`, `test_iter_steps_step4_failure_falls_back_to_simplified`, `test_iter_steps_step5_failure_yields_step_error`):
     - `test_iter_steps_yields_step_events_in_order` — assert `[(2,"active"),(2,"done"),(3,"active"),(3,"done"),(4,"active"),(4,"done"),(5,"active"),(5,"done"),(6,"active"),(6,"done")]` (six steps, ten events — was eight events/four steps).
     - `test_iter_steps_yields_pipeline_run_result` — assert `result_events[0].care_plan is CARE_PLAN_FIXTURE` and `.term_data`/`.raw_text` are populated; assert `hasattr(result_events[0], "simplified") is False` and `hasattr(result_events[0], "clarified") is False` as a regression guard (replaces the old `.simplified == "simplified"` / `.clarified == "clarified"` assertions, which no longer apply — those attributes are gone per Task 3).
     - `test_iter_steps_wrap_step_called_per_step` — `calls == [2, 3, 4, 5, 6]` (was `[2, 3, 4, 5]`).
     - `test_iter_steps_ground_failure_yields_step_error` (renamed from `test_iter_steps_step3_failure_yields_step_error`) — `p.ground = MagicMock(side_effect=RuntimeError("ground failed"))`; assert one `PipelineStepError(step=3)`, no `PipelineRunResult`.
     - `test_iter_steps_assemble_and_render_failure_yields_step_error` (new) — `p.assemble_and_render = MagicMock(side_effect=RuntimeError("assemble failed"))`; assert one `PipelineStepError(step=4)`, no `PipelineRunResult`.
     - `test_iter_steps_review_failure_is_non_fatal` (replaces `test_iter_steps_step4_failure_falls_back_to_simplified`) — `p.review = MagicMock(side_effect=RuntimeError("review failed"))`; assert no `PipelineStepError`, `p.correct` is never called, `PipelineRunResult` is still yielded with `care_plan is CARE_PLAN_FIXTURE`.
     - `test_iter_steps_correct_failure_falls_back_to_pre_correction_plan` (new) — `p.review` returns a `ReviewResult` with one non-empty correction (e.g. `corrections=[{"op": "correct", "path": "x"}]`), `p.correct = MagicMock(side_effect=RuntimeError("correct failed"))`; assert no `PipelineStepError`, and `result_events[0].care_plan is CARE_PLAN_FIXTURE` (i.e. `assemble_and_render`'s output, not whatever `correct` would have returned, since it never successfully ran).
     - `test_iter_steps_skips_correct_call_when_no_corrections` (new) — `p.review` returns `corrections=[]`; assert `p.correct` is never invoked, but `StepEvent(step=6, status="active"/"done")` is still yielded.
     - `test_run_delegates_to_iter_steps` — `p.run("text", units=[])`; assert `isinstance(result, CarePlan)`.
     - `test_glossary_executor_is_shut_down_even_on_fatal_ground_failure` (new) — monkeypatch `ThreadPoolExecutor` (via `monkeypatch.setattr(pipeline_module, "ThreadPoolExecutor", <spy factory>)`) to return a `MagicMock()` whose `.submit(...)` returns a `MagicMock()`; `p.ground` raises; assert the mocked executor's `.shutdown(wait=False)` was called exactly once (proves the `finally` block runs on the early-`return` path).
     - Do **not** write a `test_citation_check_runs_before_glossary_redetection`-style test — the citation-existence property is enforced entirely inside 04's `assemble_and_render` (already exercised via the mocked `p.assemble_and_render` above and by 04's own suite), not as a second, orderable `iter_steps` call (PRD §4.10).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_streaming.py -q` (from `backend/`) passes in full with all tests listed above present; `grep -n "simplify_language_with_term_plan\|clarify_and_action\|structure_appointment_note\|\.simplified\b\|\.clarified\b" backend/tests/care_plan/test_pipeline_streaming.py` returns no hits.

### Task 10 — Targeted rewrite of `backend/tests/care_plan/test_pipeline_executors.py`

   - Files: `backend/tests/care_plan/test_pipeline_executors.py`
   - Dependency: land after Task 5.
   - Changes (PRD §7.2):
     - `FakePipeline.iter_steps`, `FailingPipeline.iter_steps`, and `OrderTrackingPipeline.iter_steps` (in `test_before_score_submitted_before_pipeline_construction`) all gain a `units` parameter: `def iter_steps(self, text, units, wrap_step=None):`.
     - `_make_run_result` drops the `simplified="simplified"` and `clarified="clarified"` kwargs (no longer valid fields on `PipelineRunResult` per Task 3):
       ```python
       def _make_run_result(text="plain note"):
           """Return a PipelineRunResult with a minimal stub care_plan."""
           return PipelineRunResult(
               care_plan=MagicMock(),
               term_data={"substitution_candidates": [], "preserve_and_define_terms": [], "abbreviations": []},
               raw_text=text,
           )
       ```
     - Every `run_care_plan_pipeline("...", metrics, grading_enabled=...)` call site in this file (8 occurrences: `test_run_care_plan_pipeline_yields_typed_step_events`, `test_run_care_plan_pipeline_yields_adapter_result`, `test_run_care_plan_pipeline_step_error_yields_adapter_error`, `test_grading_enabled_still_computes_before_and_after_scores`, `test_grading_disabled_never_creates_a_threadpool`, `test_step_error_with_grading_enabled_does_not_hang_or_leak_thread`, `test_pipeline_constructor_failure_with_grading_enabled_does_not_hang_or_leak_thread`, `test_before_score_submitted_before_pipeline_construction`) gains a `units=[]` argument, e.g. `run_care_plan_pipeline("plain note", [], metrics, grading_enabled=False)`.
     - `test_grading_enabled_still_computes_before_and_after_scores` and `test_before_score_submitted_before_pipeline_construction` currently assert on the literal string `"clarified"` (`("clarified", "after") in called_args` / `mock_score.assert_called_once_with("clarified", "after")`), which no longer has meaning once `event.clarified` is gone. Add `patch("services.care_plan_pipeline.render_care_plan_text")` to each test's `with` block, set `mock_render.return_value = "rendered text stub"`, and change the assertions to check for `("rendered text stub", "after")` / `mock_score.assert_called_once_with("rendered text stub", "after")` instead. (`render_care_plan_text` is imported into `services/care_plan_pipeline.py` by Task 5, so it's patchable at `services.care_plan_pipeline.render_care_plan_text`.)
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_executors.py -q` (from `backend/`) passes in full; `grep -n '"clarified"' backend/tests/care_plan/test_pipeline_executors.py` returns no hits.

### Task 11 — `backend/tests/routes/test_worker.py`: mechanical updates + new provenance-stripping tests

   - Files: `backend/tests/routes/test_worker.py`
   - Dependency: land after Task 6.
   - Changes (PRD §7.3):
     - **Every `fake_pipeline`/`fake_pipeline_error`/`fake_pipeline_slow`/`fake_pipeline_raises` function definition in this file (16 occurrences, grep-confirmed: `grep -n "def fake_pipeline" backend/tests/routes/test_worker.py`)** currently has the fixed signature `(text, metrics, grading_enabled, source_kind="text", is_batch=False)` and is invoked through a `patch("routes.worker.run_care_plan_pipeline", lambda *a, **kw: fake_pipeline(*a, **kw))` pass-through. Since `routes/worker.py`'s real call site (Task 6) now passes `units` as a new positional argument between `text` and `metrics`, **each of these 16 function definitions must add `units` as a new positional parameter in the same position**: `def fake_pipeline(text, units, metrics, grading_enabled, source_kind="text", is_batch=False):`. (The `lambda *a, **kw: fake_pipeline(*a, **kw)` wrapper itself needs no change — it's already generic — but the fixed-signature function it forwards to does; verified by reading the actual call shape, since a stale signature here would raise `TypeError: got multiple values for argument 'source_kind'` once `units` is inserted.)
     - Every `AdapterResult(care_plan=..., grading=..., raw_text=..., clarified_text="c")`-shaped call (12 occurrences, grep-confirmed: `grep -n "AdapterResult(" backend/tests/routes/test_worker.py`) drops the `clarified_text=...` kwarg — `AdapterResult` no longer has that field (Task 3).
     - Every test that reaches the pipeline call (i.e., every test using one of the `fake_pipeline*` functions above) needs `resolve_units_from_job_doc` mocked, since `job` in these tests is typically a bare `MagicMock()`/`_make_job_doc_with_pdf_upload()`-style stub without a real `input_provenance`. Add, alongside the existing `resolve_input_from_job_doc` mocking already present in each such test:
       ```python
       monkeypatch.setattr("routes.worker.resolve_units_from_job_doc", lambda job: [])
       ```
       (or an equivalent per-test mock/patch, matching whichever pattern — `monkeypatch` fixture vs. `@patch` decorator — that specific test already uses for `resolve_input_from_job_doc`).
     - The "5-stage LLM pipeline" docstring reference (currently line ~856, a comment/docstring, not an assertion) gets the same wording update as `worker.py:74` (Task 6): "the whole pipeline (four sequential LLM calls)".
     - **New tests proving Task 6's stripping fix**, extending `test_job_completed_output_has_no_raw`'s exact pattern (`test_worker.py:425-463` — `_make_job_doc_with_pdf_upload`, a `fake_pipeline` yielding `AdapterResult`, `envelope_mock.to_dict.return_value` carrying the field to be stripped, asserting on `mock_complete.call_args.args[1]`):
       ```python
       def test_job_completed_output_has_no_summary_fact_ids(...):
           # envelope_mock.to_dict.return_value["care_plan"] carries
           # "summary_fact_ids": [1, 2, 3] alongside "reason_for_visit"
           # assert "summary_fact_ids" not in saved_output_data["care_plan"]
           ...

       def test_job_completed_output_has_no_source_fact_ids(...):
           # care_plan carries at least one populated item in "medications"
           # (e.g. {"title": "Metoprolol", "source_fact_ids": [4]}) and "tests"
           # (e.g. {"title": "CBC", "source_fact_ids": [5]})
           # assert "source_fact_ids" not in saved_output_data["care_plan"]["medications"][0]
           # assert "source_fact_ids" not in saved_output_data["care_plan"]["tests"][0]
           ...
       ```
       Covering two of the six item lists is enough here; the next set of tests covers all six exhaustively.
     - **New unit tests on `_strip_internal_provenance` directly** (no Flask app, no mocks) — add to this file or a new `test_worker_helpers.py` alongside it:
       ```python
       def test_strip_internal_provenance_removes_summary_and_all_six_source_fact_ids():
           from routes.worker import _strip_internal_provenance
           care_plan = {
               "summary_fact_ids": [1, 2],
               "medications": [{"title": "m", "source_fact_ids": [1]}],
               "tests": [{"title": "t", "source_fact_ids": [2]}],
               "procedures": [{"title": "p", "source_fact_ids": [3]}],
               "other": [{"title": "o", "source_fact_ids": [4]}],
               "follow_up": [{"title": "f", "source_fact_ids": [5]}],
               "warning_signs": [{"title": "w", "source_fact_ids": [6]}],
           }
           _strip_internal_provenance(care_plan)
           assert "summary_fact_ids" not in care_plan
           for key in ("medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
               assert "source_fact_ids" not in care_plan[key][0]
               assert "title" in care_plan[key][0]   # unrelated fields survive

       def test_strip_internal_provenance_tolerates_missing_keys():
           from routes.worker import _strip_internal_provenance
           _strip_internal_provenance({})   # no exception
           _strip_internal_provenance({"medications": [{"title": "m"}]})   # no exception, no source_fact_ids key present
       ```
   - Acceptance criteria: `python -m pytest tests/routes/test_worker.py -q` (from `backend/`) passes in full, including the 4 new tests above; `grep -n "clarified_text=" backend/tests/routes/test_worker.py` returns no hits; `grep -n "def fake_pipeline" backend/tests/routes/test_worker.py | wc -l` still shows 16, each now with `units` as its second parameter (spot-check a few).

### Task 12 — `backend/tests/routes/test_jobs_e2e_scenarios.py`: pipeline-fake updates, doc-size recalibration, stage regression guard

   - Files: `backend/tests/routes/test_jobs_e2e_scenarios.py`
   - Dependency: land after Tasks 6, 7, and after 01/02's own tasks have landed against this file (01's Task 13 already fixes `_build_care_plan`'s construction-time breakage; 02's Task 16 already adds `input_provenance` lifecycle assertions). This task's job is only what those two explicitly deferred to 06.
   - Changes (PRD §7.4, §4.6, §4.7):
     - **`_fake_pipeline_factory`'s inner `fake_pipeline`** (currently `text, metrics, grading_enabled, source_kind="upload", is_batch=False`) and the standalone **`racing_pipeline`** (currently `text, metrics, grading_enabled, source_kind="text", is_batch=False`, inside the DELETE-race test) both gain `units` as a new second positional parameter, matching `routes/worker.py`'s new call shape (Task 6) — these are patched directly (`patch("routes.worker.run_care_plan_pipeline", fake_pipeline)`), not via a `lambda *a, **kw:` pass-through, so their fixed signatures must match exactly or the call raises `TypeError`.
     - Both `yield AdapterResult(care_plan=..., grading=..., raw_text=text, clarified_text=text)` call sites (inside `_fake_pipeline_factory` and `racing_pipeline`) drop the `clarified_text=text` kwarg.
     - `_fake_pipeline_factory`'s `AdapterStepEvent` sequence (currently steps 2/3/4/5 labeled "Terms"/"Simplify"/"Clarify"/"Structure") gets a sixth step added for `CORRECT` (label "Correct" or similar — the exact label string isn't asserted anywhere in this file's tests, only the step *numbers* matter for the worker's stage-tracking loop): add `yield AdapterStepEvent(step=6, status="active", label="Correct")` / `yield AdapterStepEvent(step=6, status="done", label="Correct")` after the existing step-5 pair. Relabeling steps 3/4/5's strings (e.g. "Simplify" → "Ground") is cosmetic and optional — not asserted anywhere in this file.
     - **Doc-size-budget recalibration**: with 01's `RawArtifacts` deletion (~9,000 chars of synthetic padding removed from `_build_care_plan`) and no replacement padding added by this PRD, the completed-doc-size assertions (`assert size < 1_048_576` at ~line 486 and ~line 671; `assert max_leaf < 1500` at ~line 491) now have significantly more headroom than before, weakening their value as near-boundary regression checks. The ledger/units are never persisted (01 §4.1.4, 02 §4.1), so they add nothing to `output_data`'s size; the only size growth versus the old 3-LLM-call output is `summary_fact_ids` (a handful of ints) and `*.status` (a handful of short strings) — both negligible. Concretely:
       1. Run `python -m pytest tests/routes/test_jobs_e2e_scenarios.py::TestScenario1TypicalDischargeSummary::test_full_chain_completes_and_final_doc_is_safe_and_small -q -s` (from `backend/`) and read the printed `[scenario 1] completed doc size: N bytes` line.
       2. If `N` is still a meaningful fraction of `1_048_576` (i.e. the test still exercises real margin, not a trivially-small doc), leave the `1_048_576`/`1500` thresholds as-is — they still hold and still mean something.
       3. If the margin has grown so large that the assertion no longer meaningfully tests "stays under the limit" (e.g. the doc is now under 10% of the cap where it used to be much closer), increase `_build_care_plan`'s `"large"`-size item count (currently `n = 14` for non-`"typical"` sizes) or extend one of its longer free-text fields (e.g. `why`/`instructions`/`what_it_might_mean`) so the "large" scenario's completed doc size is restored to a comparable fraction of the 1 MiB budget as before `RawArtifacts` was removed — document the new size inline with a comment explaining why the padding was added (mirroring this task's own reasoning). Do not change the `1_048_576`/`1500` numeric limits themselves — those are Firestore's actual hard limits, not this test's own calibration.
     - **Stage regression guard**: in the same completed-doc assertion blocks (Scenario 1 at ~line 486 and Scenario 4's `TestScenario4MultibyteNearLimits::test_mixed_multibyte_just_under_both_caps_completes_and_stays_under_1mib` at ~line 671), add:
       ```python
       assert doc.get("stage") in (None, *range(1, 7))
       ```
       immediately alongside the existing size assertions — a light guard that no code path can write an out-of-range stage number after the six-step renumbering. (02's own Task 16 already adds `assert "input_provenance" not in doc` to these same two tests — this is an additional, independent assertion in the same test bodies, not a replacement.)
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_jobs_e2e_scenarios.py -q` (from `backend/`) passes in full — every test that reaches `_fake_pipeline_factory`/`racing_pipeline` constructs and completes without `TypeError`.
     - `grep -n "clarified_text=" backend/tests/routes/test_jobs_e2e_scenarios.py` returns no hits.
     - `grep -n 'doc.get("stage") in (None,' backend/tests/routes/test_jobs_e2e_scenarios.py` returns 2 hits.
     - The doc-size assertions still pass with real, documented margin (state the actual byte counts found in step 1 above in your task-completion notes if you had to add compensating padding).

### Task 13 — `frontend/src/tests/components/ProcessingScreen.test.tsx`

   - Files: `frontend/src/tests/components/ProcessingScreen.test.tsx`
   - Dependency: land after Task 8.
   - Changes (PRD §7.5):
     - `baseJobDoc`'s `stage: 3` now corresponds to `GROUND`, not `SIMPLIFY_LANGUAGE`. Update the test titled `'renders steps 1-2 done, step 3 active, steps 4-5 waiting for stage=3'` to `'renders steps 1-2 done, step 3 active, steps 4-6 waiting for stage=3'`, and its `screen.getByText('Simplifying language')` assertion to `screen.getByText('Finding the facts in your note')`. Since `.step-node` now has six entries, add a `nodes[5]` check (`expect(nodes[5].className).toContain('waiting')`) alongside the existing `nodes[0]`-`nodes[4]` checks.
     - `'exposes an aria-live polite region announcing the current active step'`: change `'Step 3 of 5: Simplifying language'` to `'Step 3 of 6: Finding the facts in your note'`.
     - `'updates the live region as the active step advances'`: change `'Step 4 of 5'` to `'Step 4 of 6'`.
     - No other test in this file depends on step count or labels (the watchdog/terminal-state/focus tests are step-content-agnostic) — do not touch them.
   - Acceptance criteria: `npx vitest run src/tests/components/ProcessingScreen.test.tsx` (from `frontend/`) passes in full; `grep -n "Simplifying language\|Step 3 of 5\|Step 4 of 5" frontend/src/tests/components/ProcessingScreen.test.tsx` returns no hits.

### Task 14 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-13.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors. If any failure remains, confirm it traces only to a later sub-project's own still-open scope (there should be none by this point, since 01/02/03/04/05/07 are all prerequisites) — do not mark this task done with unexplained red tests.
     - From `frontend/`, `npx vitest run` passes with zero failures and zero errors.
     - `grep -rn "SIMPLIFY_LANGUAGE\|CLARIFY_AND_ACTION\|STRUCTURE_DOCUMENT\|simplify_language_with_term_plan\|clarify_and_action\|structure_appointment_note\|build_glossary_from_simplified_text\|\.clarified\b\|\.simplified\b\|clarified_text" backend --include=*.py` returns zero hits anywhere in the codebase (confirms every old name is fully retired, not just from primary call sites).
     - `python -c "from care_plan.pipeline import CarePlanPipeline; from services.care_plan_pipeline import run_care_plan_pipeline; from routes.worker import _strip_internal_provenance; from utils.constants import Constants; assert Constants.Pipeline.PIPELINE_STEPS.CORRECT.number == 6"` (from `backend/`) succeeds — a single smoke import proving every symbol this PRD touches is wired together correctly.
     - Spot-check (per PRD §7.6, no code change expected): `frontend/src/hooks/useJobSnapshot.ts` and its tests, `frontend/src/components/ResultScreen.tsx` and its tests, and `backend/tests/utils/test_firebase.py::test_complete_job_unconditionally_clears_top_level_input_text` all still pass unmodified — confirm by running their specific test files/suites and reading `useJobSnapshot.ts`/`ResultScreen.tsx` to confirm no stray edit crept in.
     - Confirm the error-taxonomy conclusion from PRD §4.8 by inspection only (no test to add): `grep -rn "ErrorCode\." frontend/src --include=*.tsx --include=*.ts | grep -i "switch\|case"` returns no hits keyed on a specific error code (zero frontend changes needed for error handling, per PRD §4.8's `[RESOLVED]`).

---

## Gaps found while grounding these tasks (not actioned here — flagged per instructions)

- **PRD 01's hand-off item "clean up `_STRUCTURING_SCHEMA`'s exclude set at `care_plan/pipeline.py:61` (currently `exclude={"terms", "raw", "note"}`)"** is *not* decided anywhere in PRD 06's own text (verified: `grep -n "_STRUCTURING_SCHEMA\|exclude" PRD.md` returns zero hits in this PRD). PRD 01 itself calls this "harmless to leave" (a no-op via `_llm_schema`'s `.pop(field, None)`), so it is not a functional bug — but per this task-generation exercise's own instruction, an undecided hand-off item is not actioned here rather than invented as new scope. Whoever picks this up next (a later cleanup pass, or simply left alone) should know it was never assigned to 06.

## Summary of what requires you (not a dev agent)

Per PRD §8, all three items are session-local judgment calls or checks against real infrastructure/traffic that cannot be automated by a dev agent:

1. **End-to-end smoke test via ngrok + pm2 (`SERVICE_MODE=combined`)**, once every sub-project (01-07) has landed: submit one real note and watch the processing screen through all six steps in order, confirm the final result renders, and confirm a deliberately-corrupted note (e.g., truncated mid-sentence) produces a clean "Start over" error screen rather than a stuck spinner or raw error code. This is the first point the full four-LLM-call chain runs together end-to-end — no other sub-project's own smoke test exercises the whole thing.
2. **Watch for the 20-second glossary-curation timeout (`GLOSSARY_CURATION_TIMEOUT_S`) firing in practice** during the above smoke test — if it fires under normal (non-degraded) conditions, the budget needs raising; the 20s figure is reasoned from the outer job-timeout ceiling, not measured against real Vertex AI latency.
3. **Confirm `stage_reached` values 3-6 appear correctly in analytics** once real traffic flows, since any external dashboard/analytics queries with hardcoded assumptions about a 5-stage pipeline are outside this repo's visibility — flagged for awareness only.

No PRD §9 items are `[OPEN]` — the gate was clear; all 14 tasks above derive from `[RESOLVED]` decisions only. Two `[DEFERRED]` items are recorded in PRD §9 as genuinely requiring a live pipeline run to resolve (the readability-score label-field skew question, and keeping the frontend/backend step-label copies in sync by convention) — neither blocks any task above.
