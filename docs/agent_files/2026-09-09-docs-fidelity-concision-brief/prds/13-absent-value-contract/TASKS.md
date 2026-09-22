# Tasks: Absent-Value Contract

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema/nullability precedent — `WarningSign.urgency`, `backend/models/care_plan/care_plan.py`); 04 (the "Not stated in your note." sentinel and `_log_thin_fields`/`_verify_assembly`, `backend/care_plan/pipeline.py`, `backend/care_plan/prompts/assemble_and_render.txt`); 05 (the reviewer/corrector op vocabulary, `_sanitize_review_result`/`_WHY_PATH_RE`, `_verify_correction_diff`/`_diff_item`/`_PII_ELIGIBLE_FIELDS`, `backend/care_plan/prompts/correct.txt` and `review.txt`); 08 (both frontend render paths, `frontend/src/utils/nextSteps.ts`, `frontend/src/types/carePlan.ts`). All of 01/04/05/08 have already landed in this repo — verified by direct read of every file below before writing this task list. Depended on by: nothing directly, but shares two files with PRD 14 (merge-provenance, `merged: bool`) and PRD 18 (diagnosis/reason-for-visit soundness, `source_fact_ids` extensions) — both edit `care_plan.py` and `assemble_and_render.txt` for unrelated fields; see Task 1 and Task 3's seam notes.

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). Single file: `python -m pytest tests/care_plan/test_pipeline_review.py -q` or `...::test_name -q`.
- Backend lint: `ruff check .` from `backend/`.
- Frontend tests: from `frontend/`, run `npm run test` (= `vitest run`). Frontend lint: `npm run lint` (= `eslint .`). There is no dedicated typecheck script in `frontend/package.json` — `npm run build` (= `tsc -b && vite build`) is the only command that type-checks; run it after Task 7/8 if you want a standalone type-check without a full vite build failing on unrelated concerns.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given — later tasks depend on earlier ones landing first (each task states its dependency).
- Keep backend (Python) and frontend (TypeScript) edits in separate tasks/commits — never both in one task.
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited. Line numbers below were read directly from the current repo at authoring time (2026-09-14) — re-locate by symbol/content if a prior task in this list has already shifted them.
- **Suite stays green at every commit in this PRD** — unlike PRD 04's Task 2 (which knowingly left `iter_steps` calling deleted methods until 06 lands), no task here requires an accepted interim red state. Task 3 is the one place a naive edit order would go red (rewriting the prompt text breaks two prompt-content assertions); that task lands the corresponding test fix in the same commit so the suite never goes red.

---

### Task 1 — `backend/models/care_plan/care_plan.py`: `why` becomes nullable, `""` normalizes to `None`

   - Files: `backend/models/care_plan/care_plan.py`
   - Changes (PRD §4.1): Add `field_validator` to the existing `from pydantic import Field` import (`care_plan.py:7`):
     ```python
     from pydantic import Field, field_validator
     ```
     Add a module-level helper, placed after the imports and before `ReasonForVisit` (i.e. after line 10):
     ```python
     def _blank_str_to_none(v: object) -> object:
         """Normalize an empty string to None so a field validated by this
         helper is always exactly one of {None, non-empty text} -- never a
         third, indistinguishable "" state (PRD 13 S4.1). `object`, not
         `str | None`: Pydantic calls a mode="before" validator with
         whatever raw value was actually given, before type coercion runs --
         a non-str value here is returned unchanged and Pydantic's own type
         check raises on it immediately afterward, exactly as it would have
         without this validator in the chain."""
         return (v or None) if isinstance(v, str) else v
     ```
     On each of `Medication` (line 34), `Test` (line 49), `Procedure` (line 59), `OtherInstruction` (line 68), change `why: str = ""` to `why: str | None = None` and add a `_normalize_why` classmethod validator directly below the field. Example for `Medication`:
     ```python
     class Medication(JsonModel):
         title: str = ""
         plain_name: str = ""
         why: str | None = None
         dosage: str = ""
         frequency: str = ""
         timing: str = ""
         duration: str = ""
         instructions: str = ""
         side_effects_to_watch: str = ""
         change: str = ""
         status: Literal["to_do", "done"]
         source_fact_ids: list[int] = Field(default_factory=list)

         @field_validator("why", mode="before")
         @classmethod
         def _normalize_why(cls, v):
             return _blank_str_to_none(v)
     ```
     Repeat identically (same three-line validator body) on `Test`, `Procedure`, `OtherInstruction`, right after each class's own `why: str | None = None` field line. Do not touch `FollowUp` or `WarningSign` — neither has a `why` field.
   - **Seam note (PRD §4.8, do not act on this — informational only):** PRD 14 adds `merged: bool` and PRD 18 adds `source_fact_ids`/`changed_since_last_visit_fact_ids` to some of these same classes and to `ReasonForVisit`/`DiagnosisDetail`/`Diagnosis`. Both PRDs confirm (in their own §4.8/§4.7) zero class-body overlap with this task's edits — this task only adds one field validator to the four `why`-bearing classes. No coordination action is needed here beyond leaving the other classes untouched, which this task already does.
   - Acceptance criteria:
     - `python -c "from models.care_plan.care_plan import Medication, Test, Procedure, OtherInstruction; assert Medication(status='to_do').why is None; assert Medication(status='to_do', why='').why is None; assert Medication(status='to_do', why='x').why == 'x'"` (from `backend/`) succeeds.
     - `grep -n "why: str | None = None" backend/models/care_plan/care_plan.py` returns exactly 4 lines.
     - `grep -c "_normalize_why" backend/models/care_plan/care_plan.py` returns 8 (one `def` + one call site per class, ×4 classes).
     - `python -m pytest tests/ -q` (from `backend/`) passes in full — this change is additive/backward-compatible (existing fixtures use non-empty `why` text, unaffected by the normalizer).
     - `ruff check .` (from `backend/`) is clean.

### Task 2 — Backend: new model tests + fixture null item

   - Files: `backend/tests/models/test_care_plan.py`, `backend/tests/fixtures/care_plan.json`
   - Dependency: land after Task 1.
   - Changes (PRD §7.1, §7.4, §9):
     - In `test_care_plan.py`, add (mirroring the file's existing `test_warning_sign_accepts_null_urgency` at lines 101-103 and `test_medication_requires_status` at line 106), after the existing `WarningSign` tests and before/after the `Medication` tests — placement anywhere in the file's flat function list is fine:
       ```python
       import pytest

       from models.care_plan.care_plan import Medication, Test, Procedure, OtherInstruction


       @pytest.mark.parametrize("model_cls", [Medication, Test, Procedure, OtherInstruction])
       def test_why_defaults_to_none(model_cls):
           assert model_cls(status="to_do").why is None


       @pytest.mark.parametrize("model_cls", [Medication, Test, Procedure, OtherInstruction])
       def test_why_accepts_explicit_none(model_cls):
           assert model_cls(status="to_do", why=None).why is None


       @pytest.mark.parametrize("model_cls", [Medication, Test, Procedure, OtherInstruction])
       def test_why_empty_string_normalizes_to_none(model_cls):
           assert model_cls(status="to_do", why="").why is None


       @pytest.mark.parametrize("model_cls", [Medication, Test, Procedure, OtherInstruction])
       def test_why_preserves_real_text(model_cls):
           assert model_cls(status="to_do", why="Prescribed for high blood pressure.").why == \
               "Prescribed for high blood pressure."
       ```
       (Add the `Medication, Test, Procedure, OtherInstruction` names to the file's existing `from models.care_plan.care_plan import ...` import line instead of a second import statement if that line already exists — check the file's current imports before adding a duplicate.)
     - In `backend/tests/fixtures/care_plan.json`, add one new item with `why: null` to the fixture so `test_care_plan_round_trips_full_fixture` (which does a **strict** `model.model_dump(mode="json") == full_fixture` comparison) incidentally exercises the null state. Add a second `other[]` entry (simplest array to extend without disturbing the single-item `medications`/`tests`/`procedures` arrays other tests may key off of), e.g.:
       ```json
       {
         "title": "Track symptoms in a log",
         "why": null,
         "steps": [],
         "description": "Write down any new symptoms you notice.",
         "frequency": "",
         "duration": "",
         "status": "to_do",
         "source_fact_ids": [1]
       }
       ```
       appended to the existing one-item `other` array (currently at `care_plan.json` lines 73-87).
   - **Seam note (informational only):** PRD 18 also extends this same fixture (adding `source_fact_ids` to `reason_for_visit`/`diagnosis.details` and `changed_since_last_visit_fact_ids` to `diagnosis`) for the same round-trip test. This task only touches the `other[]` array; PRD 18's additions are to different top-level keys (`reason_for_visit`, `diagnosis`), so no line collision is expected regardless of landing order — a straightforward JSON merge either way.
   - Acceptance criteria:
     - `python -m pytest tests/models/test_care_plan.py -q` (from `backend/`) passes in full, including the 16 new parametrized cases (4 tests × 4 model classes).
     - `python -c "import json; d = json.load(open('tests/fixtures/care_plan.json')); assert any(o.get('why') is None for o in d['other'])"` (from `backend/`) succeeds.
     - `python -m pytest tests/models/test_care_plan.py::test_care_plan_round_trips_full_fixture -q` (from `backend/`) passes (proves the null item round-trips through strict dict equality).
     - `python -m pytest tests/ -q` (from `backend/`) passes in full.

### Task 3 — Backend: rewrite prompt text (§4.2), keep prompt-content tests green in the same commit

   - Files: `backend/care_plan/prompts/assemble_and_render.txt`, `backend/care_plan/prompts/correct.txt`, `backend/care_plan/prompts/review.txt`, `backend/care_plan/pipeline.py`, `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 1 (schema must already accept `null`/`None` before the prompts start instructing it). Independent of Task 2.
   - Changes (PRD §4.2):
     - `assemble_and_render.txt:28`, replace the `NOT STATED --` paragraph in full:
       ```
       NOT STATED -- if a medications, tests, procedures, or other item's `why` is not given by its fact, set why to null. Do not invent a reason, and do not write an empty string ("") -- null is the only way to mark a genuinely unstated reason. The app fills in a clear message for the patient wherever why is null, so you do not need to write one yourself.
       ```
     - `correct.txt:10`, replace the `not_stated` line:
       ```
       For a "not_stated" entry: set that exact field to null (JSON null) -- not an empty string, and not any text.
       ```
     - `review.txt:12`, cosmetic accuracy fix (no test depends on the exact old/new wording beyond the four path names, already covered by an untouched test — see below):
       ```
       - "not_stated": the plan asserts a reason the fact doesn't support. Valid ONLY for these four paths: medications[N].why, tests[N].why, procedures[N].why, other[N].why. Do not set a value -- the field is cleared to null downstream, and the app shows the patient a message when it renders a null why.
       ```
     - `pipeline.py`'s `_log_thin_fields` docstring (currently lines 367-380), replace only the last two sentences (the logic below the docstring is untouched — see Task 1/§4.3, no logic change anywhere in this function):
       ```python
       def _log_thin_fields(model: CarePlan) -> None:
           """Logs (never mutates or drops) a why/description field that fails
           03's _is_informative_quote floor (PRD 04 §9). Observability only: unlike
           NOT STATED, there is no fallback value to substitute for a field the
           model DID fill in, and dropping an otherwise-backed item over one thin
           field would remove genuine content the brief's "remove nothing"
           principle protects. why may be None (not stated) -- None is falsy, so
           it short-circuits the `if value and ...` guard below before
           _is_informative_quote is ever called on it (PRD 13 §4.3); a thin-but-
           present why still gets flagged exactly as before."""
       ```
     - In `test_pipeline_prompts.py`, the prompt-text rewrite above breaks two existing assertions mechanically (they assert the now-deleted literal string is present) — fix both in this same commit so the suite never goes red:
       - `test_assemble_prompt_contains_not_stated_sentinel` (line 93-94) → rename to `test_assemble_prompt_not_stated_rule_instructs_null`:
         ```python
         def test_assemble_prompt_not_stated_rule_instructs_null():
             assert "Not stated in your note." not in _ASSEMBLE_PROMPT
             not_stated_start = _ASSEMBLE_PROMPT.index("\nNOT STATED --")
             next_section_start = _ASSEMBLE_PROMPT.index("\nMERGE --")
             not_stated_section = _ASSEMBLE_PROMPT[not_stated_start:next_section_start]
             assert "null" in not_stated_section
         ```
       - `test_correct_prompt_contains_not_stated_sentinel` (line 189-190) → rename to `test_correct_prompt_not_stated_rule_instructs_null`:
         ```python
         def test_correct_prompt_not_stated_rule_instructs_null():
             assert "Not stated in your note." not in _CORRECT_PROMPT
             assert "null" in _CORRECT_PROMPT
         ```
   - **Confirmed unaffected by this task, no action needed (verified by direct read):** `test_assemble_prompt_not_stated_rule_names_all_four_why_fields` (`test_pipeline_assembly.py:129-137`) and `test_review_prompt_scopes_not_stated_to_four_why_fields` (`test_pipeline_prompts.py:153-160`) both assert only that the four field names/paths appear in the relevant section — the new wording still contains `medications`/`tests`/`procedures`/`other` in the `NOT STATED --` paragraph and the four `...[N].why` paths in `review.txt`, so neither test needs to change.
   - **Seam note (PRD §4.8, informational only):** PRD 14's `MERGE --` paragraph and PRD 18's `MAPPING --`/`SOURCE_FACT_IDS --` paragraphs in this same file are adjacent but textually independent of the `NOT STATED --` paragraph this task rewrites — no shared sentence needs to satisfy more than one PRD.
   - Acceptance criteria:
     - `grep -c "Not stated in your note" backend/care_plan/prompts/assemble_and_render.txt backend/care_plan/prompts/correct.txt` returns `0` for both files.
     - `grep -n "the fixed sentence is inserted downstream" backend/care_plan/prompts/review.txt` returns no hits; `grep -n "cleared to null downstream" backend/care_plan/prompts/review.txt` returns 1 hit.
     - `grep -n '"Not stated in your note." (25 chars)' backend/care_plan/pipeline.py` returns no hits.
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full.
     - `python -m pytest tests/ -q` (from `backend/`) passes in full — no other test in the repo asserts on this exact prompt wording (confirmed by the repo-wide grep in this PRD's investigation: only the two tests fixed above referenced the literal sentinel inside a prompt constant).

### Task 4 — Backend: rewrite the three remaining stale "why sentinel" tests to null semantics

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py`, `backend/tests/care_plan/test_pipeline_correct.py`
   - Dependency: land after Task 1 and Task 3 (these tests should reflect the new prompt's instructed behavior, even though — per §4.3 — no pipeline logic change makes them fail mechanically; they are updated for correctness, not to fix a red suite).
   - Changes (PRD §7.2):
     - `test_pipeline_assembly.py:113-126`, `test_assemble_and_render_accepts_not_stated_why` → rename to `test_assemble_and_render_accepts_null_why`:
       ```python
       def test_assemble_and_render_accepts_null_why():
           pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
           facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]
           pipeline._generate_json = lambda *a, **k: {
               **_minimal_care_plan_response(),
               "medications": [
                   {"why": None, "status": "to_do", "source_fact_ids": [1]}
               ],
           }

           result = pipeline.assemble_and_render(facts, [], [], [])

           assert result.medications[0].why is None
           assert result.medications[0].source_fact_ids == [1]
       ```
     - `test_pipeline_assembly.py:329-338`, `test_verify_assembly_does_not_flag_not_stated_sentinel_as_thin` → rename to `test_verify_assembly_does_not_flag_null_why_as_thin`:
       ```python
       def test_verify_assembly_does_not_flag_null_why_as_thin(caplog):
           model = CarePlan(
               medications=[_make_item("medications", [1], why=None)]
           )
           facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

           with caplog.at_level(logging.WARNING):
               _verify_assembly(model, facts)

           assert not any("thin" in record.message for record in caplog.records)
       ```
       (The assertion is unchanged from before — this now correctly demonstrates the falsy-short-circuit reason the guard doesn't fire, per §4.3, rather than the old, coincidental 25-char-clears-the-floor reason.)
     - `test_pipeline_correct.py:114-124`, `test_correct_applies_not_stated_to_exact_sentinel_text` → rename to `test_correct_applies_not_stated_by_nulling_the_field`:
       ```python
       def test_correct_applies_not_stated_by_nulling_the_field():
           pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
           before = _base_care_plan()
           corrections = [Correction(op="not_stated", path="medications[0].why")]
           after_dict = copy.deepcopy(before.model_dump(mode="json"))
           after_dict["medications"][0]["why"] = None
           pipeline._generate_json = lambda *a, **k: after_dict

           result = pipeline.correct(before, corrections, [], [], [])

           assert result.medications[0].why is None
       ```
   - Acceptance criteria:
     - `grep -n "not_stated_to_exact_sentinel\|accepts_not_stated_why\|does_not_flag_not_stated_sentinel_as_thin" backend/tests/care_plan/test_pipeline_assembly.py backend/tests/care_plan/test_pipeline_correct.py` returns no hits (old names gone).
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py tests/care_plan/test_pipeline_correct.py -q` (from `backend/`) passes in full.
     - `python -m pytest tests/ -q` (from `backend/`) passes in full.

### Task 5 — Backend: new diff-check transition tests (`test_pipeline_correct.py`)

   - Files: `backend/tests/care_plan/test_pipeline_correct.py`
   - Dependency: land after Task 1 (uses `why=None`/`null` transitions against the now-nullable field). Independent of Tasks 3/4.
   - Changes (PRD §7.4): add these three tests, the load-bearing regression coverage for §4.3's transition-table walkthrough (confirms `_verify_correction_diff` needs no code change, only new coverage):
     ```python
     def test_diff_check_passes_when_not_stated_nulls_a_filled_why():
         before = _base_care_plan()
         corrections = [Correction(op="not_stated", path="medications[0].why")]
         after = _mutate(before, lambda d: d["medications"][0].__setitem__("why", None))

         _verify_correction_diff(before, after, corrections)  # no exception


     def test_diff_check_rejects_why_nulled_without_being_named():
         before = _base_care_plan()
         after = _mutate(before, lambda d: d["medications"][0].__setitem__("why", None))

         with pytest.raises(SimplifyError) as exc_info:
             _verify_correction_diff(before, after, corrections=[])
         assert exc_info.value.error_code == ErrorCode.PIPELINE_VALIDATION_FAILED


     def test_diff_check_passes_when_named_correct_fills_a_null_why():
         before = _base_care_plan(
             medications=[
                 _medication(why=None, dosage="10 mg", source_fact_ids=[1]),
                 _medication(dosage="20 mg", source_fact_ids=[2]),
             ]
         )
         corrections = [Correction(op="correct", path="medications[0].why",
                                    value="Prescribed for high blood pressure.")]
         after = _mutate(before, lambda d: d["medications"][0].__setitem__(
             "why", "Prescribed for high blood pressure."))

         _verify_correction_diff(before, after, corrections)  # no exception
     ```
     Place these in the "The corrector-diff check" section of the file, alongside the existing `test_diff_check_passes_when_only_named_field_changes` / `test_diff_check_passes_small_pii_substitution_on_eligible_field` tests. `_medication`, `_base_care_plan`, `_mutate` are the file's existing helpers (see `_medication(**overrides) -> dict` at the top of the file) — no new helper needed. Note `_medication`'s default `why="Prescribed by Doctor Alok Singh"` must be overridden to `why=None` explicitly in the third test's fixture construction, as shown.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_correct.py -q` (from `backend/`) passes in full, including the 3 new tests.
     - Each of the three new test names appears exactly once via `grep -c "def test_diff_check_passes_when_not_stated_nulls_a_filled_why\|def test_diff_check_rejects_why_nulled_without_being_named\|def test_diff_check_passes_when_named_correct_fills_a_null_why" backend/tests/care_plan/test_pipeline_correct.py` returning `3`.

### Task 6 — Backend: new LLM-empty-string-normalization test (`test_pipeline_assembly.py`)

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py`
   - Dependency: land after Task 1. Independent of Tasks 3, 4, 5.
   - Changes (PRD §7.4): add one test confirming the model-validator normalization survives a full `assemble_and_render` round trip (guards against an LLM that ignores the prompt's "do not write an empty string" instruction and emits `""` instead of `null`):
     ```python
     def test_assemble_and_render_normalizes_llm_empty_string_why_to_none():
         pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
         facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")]
         pipeline._generate_json = lambda *a, **k: {
             **_minimal_care_plan_response(),
             "medications": [{"why": "", "status": "to_do", "source_fact_ids": [1]}],
         }
         result = pipeline.assemble_and_render(facts, [], [], [])
         assert result.medications[0].why is None
     ```
     Place in the "Not stated" rendering section, next to `test_assemble_and_render_accepts_null_why` (Task 4). `_minimal_care_plan_response` is the file's existing helper (line 56-57) — no new helper needed.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` (from `backend/`) passes in full, including this new test.
     - `python -m pytest tests/ -q` (from `backend/`) passes in full — Tasks 1 through 6 complete the entire backend side of this PRD.
     - `ruff check .` (from `backend/`) is clean.

### Task 7 — Frontend: `frontend/src/types/carePlan.ts` — `why` becomes nullable, stays optional

   - Files: `frontend/src/types/carePlan.ts`
   - Dependency: none within this PRD (independent of all backend tasks — pure type change). Land before Task 8 (which relies on the widened type to justify `resolveWhy`'s signature).
   - Changes (PRD §4.4): on `Medication` (line 33), `Test` (line 47), `Procedure` (line 56), `OtherInstruction` (line 64), change:
     ```typescript
     why?: string;
     ```
     to:
     ```typescript
     why?: string | null;
     ```
     Do this on all four interfaces; do not add `null` anywhere else (`DiagnosisDetail`, `FollowUp`, etc. are untouched — none has a `why` field affected by this PRD). Keep the `?` (optional key) on all four — this is a deliberate deviation from `WarningSign.urgency`'s required-key precedent, since nothing downstream branches on key-presence vs. value-falsiness for `why` (verified: the only two files constructing these types as object literals, `carePlan.ts` itself and `nextSteps.test.ts`, already omit `why` freely in most fixtures — making the key required would force ~18 unrelated test-fixture edits in `CarePlanView.test.tsx`/`buildPdfHtml.test.ts` for zero functional gain, per PRD §4.4).
   - Acceptance criteria:
     - `grep -c "why?: string | null;" frontend/src/types/carePlan.ts` returns `4`.
     - `grep -c "why?: string;" frontend/src/types/carePlan.ts` returns `0`.
     - `npm run build` (from `frontend/`) type-checks cleanly (no consumer of `Medication.why`/etc. is typed in a way that breaks on the widened union — confirmed by reading `nextSteps.ts`, the only file that reads these fields directly, ahead of Task 8's edit).

### Task 8 — Frontend: `frontend/src/utils/nextSteps.ts` — the one fallback site

   - Files: `frontend/src/utils/nextSteps.ts`
   - Dependency: land after Task 7.
   - Changes (PRD §4.5): add a new exported constant and helper (placed after the `joinDetail` helper, before `buildNextStepsRows`):
     ```typescript
     export const WHY_NOT_STATED = 'Not stated in your note.';

     // Single point through which BOTH CarePlanView.tsx and buildPdfHtml.ts see
     // "why" -- neither reads Medication/Test/Procedure/OtherInstruction.why
     // directly (verified: repo-wide grep for `.why` under frontend/src finds
     // no other read site). A falsy check, not `== null`, so a stray "" that
     // somehow reaches this function (it shouldn't -- the backend validator in
     // S4.1 normalizes "" to None before this ever leaves the API) still gets
     // the same fallback rather than rendering a blank "Why:" line, which is
     // exactly the silent-omission failure mode this whole PRD exists to close.
     function resolveWhy(why: string | null | undefined): string {
       return why || WHY_NOT_STATED;
     }
     ```
     Then change the four `why: m.why` / `t.why` / `p.why` / `o.why` assignments inside `buildNextStepsRows` (current lines 59, 64, 68, 76) to call `resolveWhy(...)`:
     ```typescript
     why: resolveWhy(m.why),   // medications, line 59
     why: resolveWhy(t.why),   // tests, line 64
     why: resolveWhy(p.why),   // procedures, line 68
     why: resolveWhy(o.why),   // other, line 76
     ```
     These are the only four lines that change in this file. `NextStepRow.why`'s own type (`why?: string;`) is unchanged — do not touch the `NextStepRow` interface. `follow_up` rows are untouched (no `why` field, unaffected).
   - **Confirmed no change needed elsewhere (PRD §4.6, verified by direct read — do not add a task for these):**
     - `frontend/src/components/CarePlanView.tsx:210`: `{row.why && <p ...>Why: {withTerms(row.why)}</p>}` already renders correctly once `row.why` is always a non-empty string for a row that has the field at all (via `resolveWhy`) — no edit needed.
     - `frontend/src/utils/buildPdfHtml.ts:68`: `${row.why ? ... : ''}` — identical reasoning, no edit needed.
     Both files read `why` exclusively through `NextStepRow.why`, which this task's `resolveWhy` fully resolves before either renderer ever sees it — confirmed by a repo-wide grep for `.why` under `frontend/src`, which returns exactly the three sites named here and the four assignment sites this task edits.
   - Acceptance criteria:
     - `grep -n "why: resolveWhy(m.why)\|why: resolveWhy(t.why)\|why: resolveWhy(p.why)\|why: resolveWhy(o.why)" frontend/src/utils/nextSteps.ts` returns 4 lines.
     - `grep -n "export const WHY_NOT_STATED = 'Not stated in your note.';" frontend/src/utils/nextSteps.ts` returns 1 line.
     - `grep -n "why: m.why\|why: t.why\|why: p.why\|why: o.why" frontend/src/utils/nextSteps.ts` returns 0 lines (old direct assignments gone).
     - `npm run test` (from `frontend/`) passes in full — existing tests in `nextSteps.test.ts`, `CarePlanView.test.tsx`, `buildPdfHtml.test.ts` construct fixtures with either a real-text `why` or no `why` key at all, both of which `resolveWhy` handles identically to the pre-PRD behavior (a present value passes through; an absent one now explicitly falls back to the same literal string the old backend sentinel used to produce) — no existing test assertion changes.
     - `npm run lint` (from `frontend/`) is clean.

### Task 9 — Frontend: new tests for the null-`why` fallback

   - Files: `frontend/src/tests/utils/nextSteps.test.ts`, `frontend/src/tests/components/CarePlanView.test.tsx`, `frontend/src/tests/utils/buildPdfHtml.test.ts`, `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json`
   - Dependency: land after Task 8.
   - Changes (PRD §7.5, §9):
     - `nextSteps.test.ts` — add, reusing the file's existing `baseCarePlan`/`medication` helpers (no helper changes needed, since `why` stays optional):
       ```typescript
       it('falls back to the not-stated text when why is null', () => {
         const rows = buildNextStepsRows(baseCarePlan({ medications: [medication({ why: null })] }));
         expect(rows[0].why).toBe('Not stated in your note.');
       });

       it('falls back to the not-stated text when why is undefined', () => {
         const rows = buildNextStepsRows(baseCarePlan({ medications: [medication({})] }));
         expect(rows[0].why).toBe('Not stated in your note.');
       });

       it('passes through a real why value unchanged', () => {
         const rows = buildNextStepsRows(baseCarePlan({ medications: [medication({ why: 'For blood pressure.' })] }));
         expect(rows[0].why).toBe('For blood pressure.');
       });
       ```
     - `CarePlanView.test.tsx` — add, matching the file's existing minimal-`SimplifiedCarePlan`-literal style (e.g. the "renders a check mark..." test's fixture shape):
       ```typescript
       it('renders the not-stated fallback when a medication has a null why', () => {
         const carePlan: SimplifiedCarePlan = {
           summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
           medications: [{ title: 'Lisinopril', why: null, change: '', status: 'to_do' }],
           tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [],
         };
         render(<CarePlanView result={carePlan} />);
         expect(screen.getByText(/Not stated in your note\./)).toBeInTheDocument();
       });
       ```
     - `buildPdfHtml.test.ts` — add, using the file's existing `baseCarePlan` helper:
       ```typescript
       it('renders the not-stated fallback in the generated HTML when a medication has a null why', () => {
         const carePlan = baseCarePlan({
           medications: [{ title: 'Lisinopril', why: null, change: '', status: 'to_do' }],
         });
         const html = buildPdfHtml(carePlan);
         expect(html).toContain('Not stated in your note.');
       });
       ```
     - `realCarePlanOutput.fixture.json` — add one item with `why: null` alongside its existing real-text `why` values (mirrors Task 2's backend fixture addition), so `ResultScreen.test.tsx` and `HomePage.test.tsx` — both of which import this fixture and render it through the full `CarePlanView` — incidentally exercise a null `why` in addition to the three dedicated tests above. Add a second `other[]` entry with `"why": null` (parallel to Task 2's backend choice), keeping every other existing field on that item non-empty so it doesn't also trip an unrelated assertion in `ResultScreen.test.tsx`/`HomePage.test.tsx`.
   - Acceptance criteria:
     - `npm run test` (from `frontend/`) passes in full, including the 3 new `nextSteps.test.ts` cases, the 1 new `CarePlanView.test.tsx` case, and the 1 new `buildPdfHtml.test.ts` case.
     - `python3 -c "import json; d = json.load(open('frontend/src/tests/fixtures/realCarePlanOutput.fixture.json')); assert any(o.get('why') is None for o in d['care_plan']['other'])"` (the fixture's top-level keys are `metrics`, `input`, `grading`, `care_plan` — confirmed by direct read; the care plan content itself lives at `care_plan`, not nested under `output_data`, which is only how the test files wrap it at the call site) succeeds.
     - `npm run test -- ResultScreen HomePage` (or `npx vitest run src/tests/components/ResultScreen.test.tsx src/tests/pages/HomePage.test.tsx` from `frontend/`) passes in full — both suites render the updated fixture without a new failure.
     - `npm run lint` (from `frontend/`) is clean.

### Task 10 — Full-suite verification (backend + frontend)

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-9.
   - Acceptance criteria:
     - From `backend/`: `python -m pytest tests/ -q` passes with zero failures and zero errors.
     - From `backend/`: `ruff check .` is clean.
     - From `backend/`: `grep -rn "Not stated in your note" .` (excluding `.git`) returns **zero** hits anywhere in `backend/` — production prompts, pipeline docstring, and all test files have been fully migrated to the null contract. (The string now lives in exactly one place in the whole repo: `frontend/src/utils/nextSteps.ts`'s `WHY_NOT_STATED` constant, plus the test files added in Task 9 that assert against it.)
     - From `frontend/`: `npm run test` passes with zero failures.
     - From `frontend/`: `npm run lint` is clean.
     - From `frontend/`: `npm run build` type-checks and builds cleanly.
     - `python -c "from models.care_plan.care_plan import Medication; import inspect; assert 'why: str | None = None' not in inspect.getsource(Medication)" 2>/dev/null; grep -n "why: str | None = None" backend/models/care_plan/care_plan.py | wc -l` — sanity re-check that returns `4` (the grep, not the python one-liner, which is illustrative only — just confirm the 4-line grep count from Task 1 still holds after all subsequent tasks).
     - **Re-confirm PRD §4.6 and §4.7's "no code change" claims still hold** (they were verified against the pre-task-list code at authoring time in this file's own investigation): `git diff --stat main -- frontend/src/components/CarePlanView.tsx frontend/src/utils/buildPdfHtml.ts backend/care_plan/pipeline.py` — the first two files should show **zero** lines changed across this entire PRD; `pipeline.py` should show changes **only** within `_log_thin_fields`'s docstring (Task 3) — no changes to `_verify_assembly`, `_sanitize_review_result`, `_WHY_PATH_RE`, `_verify_correction_diff`, `_diff_item`, `_PII_ELIGIBLE_FIELDS`, or any other guard logic. If either check fails, stop and report — it means scope crept beyond what §4.3/§4.6 decided.

## Summary of what requires you (not a dev agent)

Per PRD §8, these are session-local, judgement-based checks against real infrastructure and cannot be automated by a dev agent:

1. **Real-pipeline smoke check, post-06.** Once a live `SERVICE_MODE=combined` run through ngrok produces a real `assemble_and_render` completion, spot-check that the Gemini model actually emits JSON `null` for an unstated `why` rather than reverting to writing prose that merely resembles "not stated" — a prompt-compliance risk inherent to any LLM instruction, not unique to this PRD, but worth one real-note confirmation before trusting it silently. (Same category of caveat PRD 04 §8 and PRD 08 §8 already record for their own real-note-dependent behaviors.)
2. **Visual QA of the rendered fallback**, both on-screen and in the downloaded PDF: confirm "Not stated in your note." still reads identically to today in both places now that it originates from `frontend/src/utils/nextSteps.ts` instead of pipeline output — this should be byte-for-byte identical (it is, per Task 8's exact string), but a human read against the actual rendered card/PDF is cheap insurance given the patient-visible-behavior-must-not-change constraint.

No new environment variables, credentials, or console configuration are needed for this PRD — it is prompt + pure Python + pure TypeScript only.

No PRD §9 items are `[OPEN]` — the gate was clear; all 10 tasks above derive from `[RESOLVED]` decisions only.
