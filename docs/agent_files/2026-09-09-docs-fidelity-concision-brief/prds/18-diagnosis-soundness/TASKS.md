# Tasks: Diagnosis and Reason-for-Visit Soundness

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (`backend/models/care_plan/care_plan.py` — owns the `source_fact_ids` shape this PRD extends), 04 (`backend/care_plan/pipeline.py` — owns `_verify_assembly`/`_ITEM_LIST_FIELDS`/`_log_thin_fields`, and `backend/care_plan/prompts/assemble_and_render.txt`, both extended here), 05 (review/correct — confirmed by direct inspection to need no code change, §4.7), 06 (`backend/routes/worker.py` — owns `_strip_internal_provenance`, extended here). All of 01/04/05/06 have already landed in this repo (verified by reading the live code — see each task below). Seams, not blocking dependencies: 13 (edits `care_plan.py`/`assemble_and_render.txt` for the unrelated `why`-nullability field — zero class/paragraph overlap, PRD §4.8), 14 (edits `assemble_and_render.txt`'s MERGE paragraph — adjacent, independent text), 10 (edits `_verify_assembly`'s tail — this PRD's new block is inserted before the final `return`, same insertion point 10 also uses; whichever of 10/18 lands second must re-locate the insertion point by reading the current file, not by line number). Depended on by: none identified in 15/16/17 (grepped, zero hits). PRD 14's diagnosis-merge observability (`len(source_fact_ids) > 1`) becomes available as a side effect of Task 1 landing — no action needed on this PRD's part.

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). Single file: `python -m pytest tests/care_plan/test_pipeline_assembly.py -q`, or `...::test_name -q` for one test. Lint: `ruff check .` from `backend/`.
- Frontend tests: from `frontend/`, run `npx vitest run` (matches `package.json`'s `"test": "vitest run"`; `npm run test` is equivalent). Single file: `npx vitest run src/tests/components/CarePlanView.test.tsx`. Lint: `npx eslint .` (= `npm run lint`). There is no dedicated typecheck script in `frontend/package.json` — `npx tsc -b` is the half of `"build": "tsc -b && vite build"` that actually type-checks; run it standalone to avoid a full `vite build`.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given. Backend and frontend changes are never mixed in one task.
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Line-number note**: line numbers below were read live at authoring time (2026-09-14) and are for orientation only — locate every edit by symbol/content match, not by line number, since earlier tasks in this same list shift later line numbers.
- **Interim red, by design**: Task 1 (schema addition) leaves `test_care_plan_round_trips_full_fixture` failing until Task 2 lands in the same area (fixture update). Task 3 (`_verify_assembly`'s new diagnosis block) leaves two existing tests failing until Task 5 lands. Both are called out explicitly in their task below, mirroring how PRD 04's TASKS.md Task 2 documented its own accepted interim breakage — never leave the tree at one of these interim states at the end of a work session.

---

### Task 1 — `backend/models/care_plan/care_plan.py`: schema additions

   - Files: `backend/models/care_plan/care_plan.py`
   - Changes (PRD §4.2): `ReasonForVisit`, `DiagnosisDetail`, and `Diagnosis` currently read (verified at HEAD, lines 13-27):
     ```python
     class ReasonForVisit(JsonModel):
         reason: str = ""
         description: str = ""


     class DiagnosisDetail(JsonModel):
         title: str = ""
         plain_name: str = ""
         description: str = ""
         what_it_means_for_you: str = ""
         severity: Literal["high", "medium", "low"] | None = None


     class Diagnosis(JsonModel):
         changed_since_last_visit: str = ""
         details: list[DiagnosisDetail] = Field(default_factory=list)
     ```
     Replace with:
     ```python
     class ReasonForVisit(JsonModel):
         reason: str = ""
         description: str = ""
         source_fact_ids: list[int] = Field(default_factory=list)


     class DiagnosisDetail(JsonModel):
         title: str = ""
         plain_name: str = ""
         description: str = ""
         what_it_means_for_you: str = ""
         severity: Literal["high", "medium", "low"] | None = None
         source_fact_ids: list[int] = Field(default_factory=list)


     class Diagnosis(JsonModel):
         changed_since_last_visit: str = ""
         changed_since_last_visit_fact_ids: list[int] = Field(default_factory=list)
         details: list[DiagnosisDetail] = Field(default_factory=list)
     ```
     `Field` is already imported at the top of this file (used throughout) — no new import needed. This is the only edit in this task; do not touch `Medication`/`Test`/`Procedure`/`OtherInstruction`/`FollowUp`/`WarningSign` or any other model in the file (those are PRD 13's territory per the §4.8 seam note above, and are untouched by this PRD regardless of landing order).
   - **Accepted interim consequence**: `backend/tests/models/test_care_plan.py::test_care_plan_round_trips_full_fixture` will fail after this task lands and before Task 2 lands, because `backend/tests/fixtures/care_plan.json` does not yet carry the three new keys and the test asserts strict `model.model_dump(mode="json") == full_fixture` equality. This is expected; Task 2 restores green. No other test in the repo breaks from this task alone — every other construction of these three models (`ReasonForVisit(...)`, `DiagnosisDetail(...)`) either omits `source_fact_ids` (picks up the new default `[]`, still constructs) or passes only keyword arguments that remain valid.
   - Acceptance criteria:
     - `grep -n "source_fact_ids" backend/models/care_plan/care_plan.py` shows the field present on `ReasonForVisit` and `DiagnosisDetail`; `grep -n "changed_since_last_visit_fact_ids" backend/models/care_plan/care_plan.py` shows it present on `Diagnosis`.
     - `python -c "from models.care_plan.care_plan import ReasonForVisit, DiagnosisDetail, Diagnosis; assert ReasonForVisit().source_fact_ids == []; assert DiagnosisDetail().source_fact_ids == []; assert Diagnosis().changed_since_last_visit_fact_ids == []"` (from `backend/`) succeeds.
     - `python -m pytest tests/models/test_care_plan.py -q` (from `backend/`) shows exactly one failure, `test_care_plan_round_trips_full_fixture`, and no other failures in that file.

### Task 2 — `backend/tests/fixtures/care_plan.json` + `backend/tests/models/test_care_plan.py`: restore green, add default-value tests

   - Files: `backend/tests/fixtures/care_plan.json`, `backend/tests/models/test_care_plan.py`
   - Dependency: land after Task 1.
   - Changes (PRD §4.9, §7.1):
     - In `care_plan.json`, add `"source_fact_ids": [1]` to the existing `reason_for_visit[0]` object and to the existing `diagnosis.details[0]` object. Add `"changed_since_last_visit_fact_ids": [2]` as a sibling key of `diagnosis.changed_since_last_visit` (the fixture's existing value, `"It has stayed high since your last visit."`, is already non-empty, so this genuinely exercises the non-empty case — no need to invent a new string).
     - Add three tests to `test_care_plan.py`, matching the file's existing `test_reason_for_visit`/model-construction convention:
       ```python
       def test_reason_for_visit_source_fact_ids_defaults_to_empty_list():
           assert ReasonForVisit().source_fact_ids == []


       def test_diagnosis_detail_source_fact_ids_defaults_to_empty_list():
           assert DiagnosisDetail().source_fact_ids == []


       def test_diagnosis_changed_since_last_visit_fact_ids_defaults_to_empty_list():
           assert Diagnosis().changed_since_last_visit_fact_ids == []
       ```
       Add `ReasonForVisit, DiagnosisDetail` to the existing `from models.care_plan.care_plan import Diagnosis, WarningSign` import line (becomes `from models.care_plan.care_plan import Diagnosis, DiagnosisDetail, ReasonForVisit, WarningSign`).
   - Acceptance criteria:
     - `python -m pytest tests/models/test_care_plan.py -q` (from `backend/`) passes in full, including `test_care_plan_round_trips_full_fixture` and the 3 new tests.
     - `python -c "import json; d = json.load(open('tests/fixtures/care_plan.json')); assert d['reason_for_visit'][0]['source_fact_ids'] == [1]; assert d['diagnosis']['details'][0]['source_fact_ids'] == [1]; assert d['diagnosis']['changed_since_last_visit_fact_ids'] == [2]"` (from `backend/`) succeeds.

### Task 3 — `backend/care_plan/pipeline.py`: `_verify_assembly`'s new coverage, and the §7.5 soundness-classification constants

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 1 (needs the new model fields to exist).
   - Changes (PRD §4.3):
     Old:
     ```python
     _ITEM_LIST_FIELDS = ("medications", "tests", "procedures", "other", "follow_up", "warning_signs")
     ```
     New:
     ```python
     _ITEM_LIST_FIELDS = (
         "reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs",
     )
     ```
     `reason_for_visit` needs no other special-casing anywhere in this function — it is structurally identical to the six original entries now that `ReasonForVisit` carries `source_fact_ids`, so it flows through the existing flat loop unchanged.

     Insert the following block into `_verify_assembly`, after the existing `for field in _ITEM_LIST_FIELDS: ... if changed: updates[field] = kept` loop and before the function's final `return model.model_copy(update=updates) if updates else model` line (that final line is unchanged — the new block only adds entries to the same `updates` dict it already reads):
     ```python
         # diagnosis is the one nested container on CarePlan -- model.diagnosis.details
         # is a list of DiagnosisDetail one level below CarePlan itself, so it cannot
         # sit in the flat _ITEM_LIST_FIELDS loop above. Handled as a second, dedicated
         # block, mirroring _log_thin_fields' own precedent (a flat loop, then one
         # dedicated loop for model.diagnosis.details) for the same reason: exactly
         # one nested container exists on the whole schema (PRD 18 §4.1's field
         # audit), and a generalized nested-path descriptor for a single occurrence
         # is speculative complexity this project's posture argues against.
         diagnosis_updates: dict = {}

         kept_details: list = []
         details_changed = False
         for detail in model.diagnosis.details:
             cited = [i for i in detail.source_fact_ids if i in valid_ids]
             if not cited:
                 logger.warning(
                     "assemble_and_render: dropping unbacked diagnosis.details item -- "
                     "source_fact_ids=%r cited nothing in the ledger", detail.source_fact_ids,
                 )
                 details_changed = True
                 continue
             if len(cited) != len(detail.source_fact_ids):
                 logger.warning(
                     "assemble_and_render: dropping hallucinated source_fact_ids on a "
                     "diagnosis.details item: %s",
                     [i for i in detail.source_fact_ids if i not in valid_ids],
                 )
                 detail = detail.model_copy(update={"source_fact_ids": cited})
                 details_changed = True
             kept_details.append(detail)
         if details_changed:
             diagnosis_updates["details"] = kept_details

         if model.diagnosis.changed_since_last_visit:
             cited = [i for i in model.diagnosis.changed_since_last_visit_fact_ids if i in valid_ids]
             if not cited:
                 logger.warning(
                     "assemble_and_render: dropping uncited diagnosis.changed_since_last_visit "
                     "claim (%r) -- source_fact_ids=%r cited nothing in the ledger",
                     model.diagnosis.changed_since_last_visit,
                     model.diagnosis.changed_since_last_visit_fact_ids,
                 )
                 diagnosis_updates["changed_since_last_visit"] = ""
                 diagnosis_updates["changed_since_last_visit_fact_ids"] = []
             elif len(cited) != len(model.diagnosis.changed_since_last_visit_fact_ids):
                 diagnosis_updates["changed_since_last_visit_fact_ids"] = cited

         if diagnosis_updates:
             updates["diagnosis"] = model.diagnosis.model_copy(update=diagnosis_updates)
     ```
     Also add, alongside `_ITEM_LIST_FIELDS` (§7.5 — the regression mechanism, production-side constants; the test that consumes them lands in Task 5):
     ```python
     # Every top-level CarePlan field must appear in exactly one of the three
     # sets below (PRD 18 S7.5) -- this is what turns "a new field was added
     # with no soundness decision" into a failing test instead of a silent gap,
     # the exact failure mode this PRD exists to close for diagnosis/reason_for_visit.
     _SOUNDNESS_CHECKED_FIELDS = frozenset(_ITEM_LIST_FIELDS) | {"diagnosis", "summary"}
     _SOUNDNESS_EXEMPT_FIELDS = {
         "questions": "deliberately ungrounded by design (brief S2.5) -- PRD 18 S4.1",
         "low_priority": "demoted low-stakes content, LLM fidelity review only, no deterministic check -- PRD 18 S4.6",
         "terms": "glossary entries from a fixed reference wordlist, not a model-asserted clinical claim -- PRD 18 S4.1",
         "note": "upload metadata, never model output -- PRD 18 S4.1",
     }
     _SOUNDNESS_NOT_APPLICABLE_FIELDS = {"doc_type", "version", "summary_fact_ids"}
     ```
   - **Accepted interim consequence**: two existing tests in `backend/tests/care_plan/test_pipeline_assembly.py` will fail after this task lands and before Task 5 lands:
     - `test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched` (currently ~line 271) asserts `reason_for_visit`/`diagnosis` survive an *empty ledger* unchanged — that premise is now false for both: `reason_for_visit` is newly covered by the flat loop (its item has no `source_fact_ids`, so it is dropped against an empty ledger), and `diagnosis.details[0]` is newly covered by the block above (same reason). Task 5 replaces this test.
     - `test_assemble_and_render_preserves_merged_diagnosis_variants` (currently ~line 144) builds a `diagnosis.details[0]` dict with no `source_fact_ids` key at all; that detail now defaults to `source_fact_ids=[]`, which the new block drops entirely, turning `result.diagnosis.details[0]` into an `IndexError`. Task 5 fixes the fixture dict to add `"source_fact_ids": [1]`.
     Neither breakage is mentioned by PRD §7.2's own task description, but both are real and were confirmed by reading the current test file — do not skip fixing them in Task 5.
   - Acceptance criteria:
     - `grep -n '_ITEM_LIST_FIELDS = (' backend/care_plan/pipeline.py` shows `reason_for_visit` as the first entry.
     - `python -c "from care_plan.pipeline import _SOUNDNESS_CHECKED_FIELDS, _SOUNDNESS_EXEMPT_FIELDS, _SOUNDNESS_NOT_APPLICABLE_FIELDS; assert 'reason_for_visit' in _SOUNDNESS_CHECKED_FIELDS; assert 'diagnosis' in _SOUNDNESS_CHECKED_FIELDS"` (from `backend/`) succeeds.
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` (from `backend/`) shows exactly the two failures named above and no others.

### Task 4 — `backend/care_plan/prompts/assemble_and_render.txt`: MAPPING and SOURCE_FACT_IDS paragraph rewrite

   - Files: `backend/care_plan/prompts/assemble_and_render.txt`
   - Dependency: none (pure prompt text; independent of Tasks 1-3, safe to land in any order relative to them, though listed here for narrative flow). Do not land after Task 5, since Task 5 asserts on this file's new content.
   - Changes (PRD §4.4): the MAPPING paragraph's `reason_for_visit` and `diagnosis` rows currently read:
     ```
     MAPPING -- a fact's category decides which care-plan array it becomes an item in:
     - reason_for_visit -> reason_for_visit[] (reason: a few words; description: one plain-language sentence)
     - diagnosis -> diagnosis.details[] (title, plain_name, description, what_it_means_for_you; set severity ONLY if the fact itself states a severity judgement -- otherwise leave it null, never guess). If any diagnosis fact states something changed since the last visit, put that in diagnosis.changed_since_last_visit; otherwise leave it "".
     ```
     Replace those two rows with:
     ```
     MAPPING -- a fact's category decides which care-plan array it becomes an item in:
     - reason_for_visit -> reason_for_visit[] (reason: a few words; description: one plain-language sentence; source_fact_ids)
     - diagnosis -> diagnosis.details[] (title, plain_name, description, what_it_means_for_you; set severity ONLY if the fact itself states a severity judgement -- otherwise leave it null, never guess; source_fact_ids). If any diagnosis fact states something changed since the last visit, put that in diagnosis.changed_since_last_visit and list the id(s) of the fact(s) that state it in diagnosis.changed_since_last_visit_fact_ids; otherwise leave both "" and [].
     ```
     Leave every other MAPPING row (`medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`) untouched — this PRD does not touch them, and PRD 13's `why`-nullability work touches only the `NOT STATED` paragraph further down, not these rows (§4.8 seam).

     The SOURCE_FACT_IDS paragraph currently reads:
     ```
     SOURCE_FACT_IDS -- every medications, tests, procedures, other, follow_up, and warning_signs item must carry `source_fact_ids`: the id(s) of every fact you built it from (more than one id if MERGE below combines facts into one item). reason_for_visit and diagnosis items have no such field. Never leave source_fact_ids empty for an item you decide to include -- an item with no cited fact has nothing behind it and will not reach the patient.
     ```
     Replace in full with:
     ```
     SOURCE_FACT_IDS -- every reason_for_visit, medications, tests, procedures, other, follow_up, and warning_signs item must carry `source_fact_ids`, and every diagnosis.details item must too: the id(s) of every fact you built it from (more than one id if MERGE below combines facts into one item). If diagnosis.changed_since_last_visit is non-empty, diagnosis.changed_since_last_visit_fact_ids must name the fact(s) that state it. Never leave any of these citation fields empty for a claim you decide to include -- a claim with no cited fact has nothing behind it and will not reach the patient.
     ```
     No other paragraph in the file (MERGE, LOW PRIORITY, QUESTIONS, PII, LANGUAGE RULES, STATUS, NOT STATED) names `reason_for_visit` or `diagnosis`, so no other paragraph needs an edit. The `{schema}` placeholder is generated from the live `CarePlan` model at import time (`_ASSEMBLE_SCHEMA` in `pipeline.py`), so Task 1's field additions already flow into what the model sees — no separate schema-string edit is needed here.
   - Acceptance criteria:
     - `grep -n "reason_for_visit and diagnosis items have no such field" backend/care_plan/prompts/assemble_and_render.txt` returns zero hits.
     - `grep -n "changed_since_last_visit_fact_ids" backend/care_plan/prompts/assemble_and_render.txt` returns at least 2 hits (MAPPING row + SOURCE_FACT_IDS paragraph).
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) still passes in full at this point — this task changes prompt text only, and no *existing* test asserts the literal old exemption sentence (confirmed by grep across `tests/`), so nothing here goes red; Task 6 below adds the tests that check the *new* text.

### Task 5 — `backend/tests/care_plan/test_pipeline_assembly.py`: fix breakage from Task 3, add PRD §7.2's new soundness tests, add §7.5's regression test

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py`
   - Dependency: land after Task 3 (and Task 4, since one new test below checks prompt content) and Task 1/2.
   - Changes:
     1. **Fix `test_assemble_and_render_preserves_merged_diagnosis_variants`** (Task 3's first accepted breakage): add `"source_fact_ids": [1]` to the `diagnosis.details[0]` dict in this test's canned `_generate_json` response, so the merged detail survives `_verify_assembly`'s new nested block.
     2. **Replace `test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched`** (Task 3's second accepted breakage) — this test's premise (both fields untouched by an empty ledger) is no longer true for either field once Task 3 lands. Delete it and add two tests in its place:
        - `test_verify_assembly_enforces_source_fact_ids_on_every_item_type` (PRD §7.2 — extend the existing parametrize list to include `"reason_for_visit"` as a seventh case): change
          ```python
          @pytest.mark.parametrize(
              "field", ["medications", "tests", "procedures", "other", "follow_up", "warning_signs"]
          )
          ```
          to
          ```python
          @pytest.mark.parametrize(
              "field", ["reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs"]
          )
          ```
          This requires extending `_ITEM_MODEL_BY_FIELD` (currently the six-entry dict near the top of the file) with `"reason_for_visit": ReasonForVisit`, and extending `_make_item` — `ReasonForVisit` has neither `status` nor `urgency`, so `_make_item` needs a third branch (alongside its existing `warning_signs`-vs-everything-else split) that, for `field == "reason_for_visit"`, passes only `source_fact_ids` (plus any `**overrides`) with no `status`/`urgency` key, since `JsonModel`'s `extra="forbid"` rejects an unrecognized key.
        - `test_verify_assembly_leaves_diagnosis_untouched_when_fully_cited` — a `CarePlan` with a `diagnosis.details` entry and a `changed_since_last_visit` value, both fully cited against the ledger; assert the returned `CarePlan.diagnosis` is unchanged (no-op path, mirrors `test_verify_assembly_returns_same_object_when_no_correction_needed`).
     3. **Add** (PRD §7.2), using the file's existing `Fact`/`CarePlan`/`Diagnosis`/`DiagnosisDetail` imports (already present):
        - `test_verify_assembly_drops_diagnosis_detail_with_empty_source_fact_ids`
        - `test_verify_assembly_drops_diagnosis_detail_with_all_hallucinated_source_fact_ids`
        - `test_verify_assembly_filters_partial_hallucination_on_diagnosis_detail_without_dropping_it`
        - `test_verify_assembly_drops_all_diagnosis_details_leaves_empty_list` — assert `result.diagnosis.details == []`, not that `diagnosis` itself is removed (`Diagnosis` is not optional on `CarePlan`).
        - `test_verify_assembly_clears_uncited_changed_since_last_visit` — assert both `changed_since_last_visit == ""` and `changed_since_last_visit_fact_ids == []` afterward.
        - `test_verify_assembly_leaves_empty_changed_since_last_visit_unchecked` — `changed_since_last_visit=""`; assert no update applied regardless of what `changed_since_last_visit_fact_ids` holds.
        - `test_verify_assembly_filters_partial_hallucination_on_changed_since_last_visit` — string preserved, id list narrows.
        (Each test's exact fixture shape is specified in PRD §7.2 — follow it directly; use `_make_item`/direct `DiagnosisDetail(...)`/`Diagnosis(...)` construction consistent with the rest of the file.)
     4. **Add the §7.5 regression test**, using the `_SOUNDNESS_*` constants Task 3 added to `pipeline.py`:
        ```python
        def test_every_care_plan_field_has_a_soundness_classification():
            """Regression guard for PRD 18's headline gap: a field added to CarePlan
            with no soundness decision recorded must fail this test, not ship
            silently the way reason_for_visit/diagnosis did."""
            all_fields = set(CarePlan.model_fields)
            classified = (
                set(pipeline_module._SOUNDNESS_CHECKED_FIELDS)
                | set(pipeline_module._SOUNDNESS_EXEMPT_FIELDS)
                | set(pipeline_module._SOUNDNESS_NOT_APPLICABLE_FIELDS)
            )
            unclassified = all_fields - classified
            assert not unclassified, (
                f"{unclassified} added to CarePlan with no soundness decision recorded "
                f"-- see PRD 18 S4.1's audit table and S7.5's classification sets."
            )
        ```
        and:
        - `test_soundness_checked_fields_all_carry_a_source_fact_ids_shape` — for every name in `_SOUNDNESS_CHECKED_FIELDS` other than `"diagnosis"`/`"summary"`, assert the corresponding item model (via `_ITEM_MODEL_BY_FIELD`, extended in step 2 above) declares `source_fact_ids` in `model_fields`; a companion assertion for `"diagnosis"` checks `DiagnosisDetail.model_fields` and `Diagnosis.model_fields` (for `changed_since_last_visit_fact_ids`) instead.
        This file does not currently import the `pipeline` module itself (only names from it) — add `import care_plan.pipeline as pipeline_module` (or equivalent) alongside the existing `from care_plan.pipeline import (...)` block.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` (from `backend/`) passes in full — zero failures, including the two fixed pre-existing tests and every new test named above.
     - `grep -n "test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched" backend/tests/care_plan/test_pipeline_assembly.py` returns zero hits (confirms the obsolete test was replaced, not left alongside its successors).

### Task 6 — `backend/tests/care_plan/test_pipeline_prompts.py`: assert the new prompt text

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 4.
   - Changes (PRD §7.3): add three tests, alongside the file's existing `# 4. Assemble prompt content guards` section:
     ```python
     def test_assemble_prompt_mapping_lists_source_fact_ids_for_reason_for_visit_and_diagnosis():
         mapping_start = _ASSEMBLE_PROMPT.index("MAPPING")
         mapping_section = _ASSEMBLE_PROMPT[mapping_start:_ASSEMBLE_PROMPT.index("SOURCE_FACT_IDS")]
         reason_line = next(l for l in mapping_section.splitlines() if l.startswith("- reason_for_visit"))
         diagnosis_line = next(l for l in mapping_section.splitlines() if l.startswith("- diagnosis"))
         assert "source_fact_ids" in reason_line
         assert "source_fact_ids" in diagnosis_line


     def test_assemble_prompt_source_fact_ids_rule_no_longer_exempts_reason_for_visit_and_diagnosis():
         assert "reason_for_visit and diagnosis items have no such field" not in _ASSEMBLE_PROMPT


     def test_assemble_prompt_names_changed_since_last_visit_fact_ids():
         assert "changed_since_last_visit_fact_ids" in _ASSEMBLE_PROMPT
     ```
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full, including the 3 new tests and every pre-existing test in the file unchanged.

### Task 7 — `backend/routes/worker.py`: `_strip_internal_provenance`

   - Files: `backend/routes/worker.py`
   - Dependency: land after Task 1 (needs the new field names to exist for the code to be meaningful, though nothing here imports the model directly).
   - Changes (PRD §4.5): current implementation (verified at HEAD):
     ```python
     def _strip_internal_provenance(care_plan: dict) -> None:
         """Remove full raw artifacts and pipeline-internal evidence citations.

         These fields must never reach the API response, the frontend, or the PDF
         (brief §3.10; PRD 01 §4.1/§9: a fact-ID list is exactly as internal as
         the ledger it cites into, regardless of size). Mutates `care_plan` (the
         `output_data["care_plan"]` dict, already a plain dict via
         `envelope.to_dict()` by the time this runs) in place.

         `summary_fact_ids` is one flat top-level key. `source_fact_ids` is
         nested one-per-item inside six separate item lists, so this cannot be
         a single `.pop()` the way `raw`'s removal could be -- each list has
         to be walked.
         """
         care_plan.pop("raw", None)
         care_plan.pop("summary_fact_ids", None)
         for _key in ("medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
             for _item in care_plan.get(_key, []):
                 _item.pop("source_fact_ids", None)
     ```
     Replace with:
     ```python
     def _strip_internal_provenance(care_plan: dict) -> None:
         """Remove full raw artifacts and pipeline-internal evidence citations.

         These fields must never reach the API response, the frontend, or the PDF
         (brief §3.10; PRD 01 §4.1/§9: a fact-ID list is exactly as internal as
         the ledger it cites into, regardless of size). Mutates `care_plan` (the
         `output_data["care_plan"]` dict, already a plain dict via
         `envelope.to_dict()` by the time this runs) in place.

         `summary_fact_ids` is one flat top-level key. `source_fact_ids` is
         nested one-per-item inside seven separate item lists, so this cannot be
         a single `.pop()` the way `raw`'s removal could be -- each list has
         to be walked. `diagnosis` is handled separately because its citation
         fields sit one level below `care_plan`
         (`diagnosis.details[].source_fact_ids`,
         `diagnosis.changed_since_last_visit_fact_ids`), not as a flat top-level
         per-item list like the other seven (PRD 18 §4.3/§4.5).
         """
         care_plan.pop("raw", None)
         care_plan.pop("summary_fact_ids", None)
         for _key in ("reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
             for _item in care_plan.get(_key, []):
                 _item.pop("source_fact_ids", None)
         _diagnosis = care_plan.get("diagnosis") or {}
         _diagnosis.pop("changed_since_last_visit_fact_ids", None)
         for _detail in _diagnosis.get("details", []):
             _detail.pop("source_fact_ids", None)
     ```
     No change to the call site (`worker.py`'s existing `_strip_internal_provenance(output_data.get("care_plan", {}))`) — only the function body changes.
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_worker.py -q` (from `backend/`) still passes in full at this point (this change is additive to the function's coverage; no existing test's fixture includes `reason_for_visit`/`diagnosis` keys carrying provenance, so nothing existing regresses).
     - `python -c "
from routes.worker import _strip_internal_provenance
cp = {'reason_for_visit': [{'reason': 'x', 'source_fact_ids': [1]}], 'diagnosis': {'details': [{'title': 'x', 'source_fact_ids': [1]}], 'changed_since_last_visit_fact_ids': [2]}}
_strip_internal_provenance(cp)
assert 'source_fact_ids' not in cp['reason_for_visit'][0]
assert 'source_fact_ids' not in cp['diagnosis']['details'][0]
assert 'changed_since_last_visit_fact_ids' not in cp['diagnosis']
"` (from `backend/`) succeeds.

### Task 8 — `backend/tests/routes/test_worker.py`: extend the `_strip_internal_provenance` test group

   - Files: `backend/tests/routes/test_worker.py`
   - Dependency: land after Task 7.
   - Changes (PRD §7.4), mirroring the existing `test_job_completed_output_has_no_source_fact_ids` / `test_strip_internal_provenance_removes_summary_and_all_six_source_fact_ids` pattern:
     - `test_job_completed_output_has_no_reason_for_visit_source_fact_ids` — mock `envelope_mock.to_dict.return_value["care_plan"]` to include `"reason_for_visit": [{"reason": "...", "source_fact_ids": [1]}]`; assert `"source_fact_ids" not in saved_output_data["care_plan"]["reason_for_visit"][0]`.
     - `test_job_completed_output_has_no_diagnosis_source_fact_ids` — include `"diagnosis": {"details": [{"title": "...", "source_fact_ids": [1]}], "changed_since_last_visit_fact_ids": [2]}`; assert both `"source_fact_ids" not in saved_output_data["care_plan"]["diagnosis"]["details"][0]` and `"changed_since_last_visit_fact_ids" not in saved_output_data["care_plan"]["diagnosis"]`.
     - Extend `test_strip_internal_provenance_removes_summary_and_all_six_source_fact_ids` (rename to `..._removes_summary_and_all_seven_source_fact_ids`, or add a sibling test) to include a `"reason_for_visit"` entry and a `"diagnosis"` block in the input dict, asserting both are stripped correctly, matching the direct-unit-test style already used for the six existing keys.
   - Acceptance criteria: `python -m pytest tests/routes/test_worker.py -q` (from `backend/`) passes in full, including the new/extended tests.

### Task 9 — `frontend/src/components/CarePlanView.tsx`: widen the "What the Doctor Found" render guard, add the fallback sentence

   - Files: `frontend/src/components/CarePlanView.tsx`
   - Dependency: none on the backend tasks above — the frontend already receives `reason_for_visit`, `diagnosis.changed_since_last_visit`, and `diagnosis.details` today; this is a pure render-logic and copy change (§6). Safe to land in parallel with Tasks 1-8.
   - Changes (PRD §6, verified at HEAD lines 162-187):
     - Current render guard (line 162): `{result.diagnosis && result.diagnosis.details?.length > 0 && (`
       New guard:
       ```tsx
       {result.diagnosis && (result.diagnosis.details?.length > 0 || result.reason_for_visit?.length > 0 || !!result.diagnosis.changed_since_last_visit) && (
       ```
     - Immediately after the existing `changed_since_last_visit` paragraph block (lines 164-168) and before the `(() => { const SEVERITY_ORDER... })().map(...)` block, add:
       ```tsx
       {(!result.diagnosis.details || result.diagnosis.details.length === 0) && (
         <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
           We couldn't confirm the specific findings from your note.
         </p>
       )}
       ```
     - The existing `.map((det, i) => ...)` block is otherwise unchanged — it renders zero items when `details` is empty, and the new fallback paragraph stands in for it in that case.
     - Exact copy, verbatim: **"We couldn't confirm the specific findings from your note."**
     - No change to `frontend/src/types/carePlan.ts` (§6 — confirmed unnecessary; see the "Confirmed, no code change" section below) and no change to any other card in this file.
   - Acceptance criteria:
     - `npx tsc -b` (from `frontend/`) compiles `CarePlanView.tsx` with no errors.
     - `grep -n "We couldn't confirm the specific findings from your note." frontend/src/components/CarePlanView.tsx` returns exactly 1 hit.
     - Covered permanently by Task 11's new `CarePlanView.test.tsx` cases.

### Task 10 — `frontend/src/utils/buildPdfHtml.ts`: mirror the same widened guard and fallback in the printed/downloaded report

   - Files: `frontend/src/utils/buildPdfHtml.ts`
   - Dependency: none (independent of Task 9 and of all backend tasks; both frontend production tasks may land in either order, but both must land before Task 11).
   - Changes (PRD §6, verified at HEAD lines 38-51):
     - Current render guard (line 38): `if (result.diagnosis && result.diagnosis.details?.length) {`
       New guard:
       ```ts
       if (result.diagnosis && (result.diagnosis.details?.length || result.reason_for_visit?.length || result.diagnosis.changed_since_last_visit)) {
       ```
     - Inside the block, after the existing `changed_since_last_visit` paragraph (lines 40-42), replace the unconditional `diagnosis += (result.diagnosis.details ?? []).map(det => ...).join('');` with a conditional:
       ```ts
       if (!result.diagnosis.details?.length) {
         diagnosis += `<p style="color:#6B7280;font-size:13px;margin:0 0 8px 0;">We couldn't confirm the specific findings from your note.</p>`;
       } else {
         diagnosis += result.diagnosis.details.map(det =>
           `<div style="padding:8px 12px;margin-bottom:6px;background:#F0FDF4;border-radius:6px;">
             <strong>${escapeHtml(det.plain_name ? `${det.plain_name} (${det.title})` : det.title)}</strong>
             ${det.description ? `<br><span style="color:#6B7280;font-size:13px;">${escapeHtml(det.description)}</span>` : ''}
             ${det.what_it_means_for_you ? `<br><span style="color:#B45309;font-size:13px;">What this means for you: ${escapeHtml(det.what_it_means_for_you)}</span>` : ''}
           </div>`,
         ).join('');
       }
       ```
       (The `else` branch's template is byte-for-byte the existing `.map(...)` body — not new content, just moved under the conditional.)
     - Exact fallback copy, identical to the on-screen card: **"We couldn't confirm the specific findings from your note."**
   - Acceptance criteria:
     - `npx tsc -b` (from `frontend/`) compiles `buildPdfHtml.ts` with no errors.
     - `grep -n "We couldn't confirm the specific findings from your note." frontend/src/utils/buildPdfHtml.ts` returns exactly 1 hit.
     - Covered permanently by Task 11's new `buildPdfHtml.test.ts` cases.

### Task 11 — Frontend tests: `CarePlanView.test.tsx` and `buildPdfHtml.test.ts`

   - Files: `frontend/src/tests/components/CarePlanView.test.tsx`, `frontend/src/tests/utils/buildPdfHtml.test.ts`
   - Dependency: land after Task 9 and Task 10.
   - Changes (PRD §7.6), following the file's existing fixture convention (`summary: '', summary_fact_ids: [], reason_for_visit: [...], diagnosis: { details: [...] }`, already used throughout both files):
     - In `CarePlanView.test.tsx`:
       ```tsx
       it('renders the "What the Doctor Found" card with the couldn\'t-confirm fallback when reason_for_visit is present but diagnosis.details is empty', () => {
         const carePlan: SimplifiedCarePlan = {
           summary: '', summary_fact_ids: [],
           reason_for_visit: [{ reason: 'High blood pressure', description: 'Readings were high.' }],
           diagnosis: { details: [] },
           medications: [], tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [],
         };
         render(<CarePlanView result={carePlan} />);
         expect(screen.getByText('What the Doctor Found')).toBeInTheDocument();
         expect(screen.getByText("We couldn't confirm the specific findings from your note.")).toBeInTheDocument();
       });

       it('renders no "What the Doctor Found" card when there is no evidence of a visit', () => {
         const carePlan: SimplifiedCarePlan = {
           summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
           medications: [], tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [],
         };
         render(<CarePlanView result={carePlan} />);
         expect(screen.queryByText('What the Doctor Found')).not.toBeInTheDocument();
       });
       ```
       Note the first fixture's overall top-level card count differs from `fullyPopulatedCarePlan()`'s 8-card assertion elsewhere in this file — do not touch that unrelated existing test; these two are new, self-contained fixtures.
     - In `buildPdfHtml.test.ts`, add the parallel pair asserting on the generated HTML string: the `reason_for_visit`-present/`details`-empty fixture's output contains `"We couldn't confirm the specific findings from your note."`; the no-evidence fixture's output does not contain `"What the Doctor Found"`.
   - Acceptance criteria:
     - `npx vitest run src/tests/components/CarePlanView.test.tsx src/tests/utils/buildPdfHtml.test.ts` (from `frontend/`) passes in full, including the 4 new tests (2 per file).
     - `npx vitest run` (from `frontend/`) passes with zero failures across the whole suite.

### Task 12 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-11.
   - Acceptance criteria:
     - From `backend/`: `python -m pytest tests/ -q` passes with zero failures and zero errors.
     - From `backend/`: `ruff check .` is clean.
     - From `frontend/`: `npx tsc -b` succeeds with zero errors.
     - From `frontend/`: `npx vitest run` passes with zero failures.
     - From `frontend/`: `npx eslint .` is clean.
     - `python -c "from models.care_plan.care_plan import CarePlan; from care_plan.pipeline import _SOUNDNESS_CHECKED_FIELDS, _SOUNDNESS_EXEMPT_FIELDS, _SOUNDNESS_NOT_APPLICABLE_FIELDS; unclassified = set(CarePlan.model_fields) - (set(_SOUNDNESS_CHECKED_FIELDS) | set(_SOUNDNESS_EXEMPT_FIELDS) | set(_SOUNDNESS_NOT_APPLICABLE_FIELDS)); assert not unclassified, unclassified"` (from `backend/`) succeeds — the same smoke check the §7.5 regression test runs, confirmed once more end-to-end.

---

## Confirmed, no code change (verified against real code — not tasks)

- **§4.6, `low_priority` exemption**: confirmed still `list[str]` on `CarePlan` (`backend/models/care_plan/care_plan.py`), still rendered as plain strings in both `CarePlanView.tsx:284-287` (`result.low_priority.map((item, i) => <li key={i}>{withTerms(item)}</li>)`) and `buildPdfHtml.ts:98-99` (`result.low_priority.map(item => \`<li>${escapeHtml(item)}</li>\`)`). No shape change landed by any other PRD since §4.6 was written. Exemption stands as documented; no task needed.
- **§4.7, review/correct machinery**: confirmed by direct inspection that `_resolve_path`, `_diff_item`, and `_split_array_path` (`backend/care_plan/pipeline.py`) carry no field allowlist — `_split_array_path`'s own docstring names `"diagnosis.details[0]"` as an example it already handles, and `_diff_item` recurses generically. `review.txt`/`correct.txt` are untouched by this PRD. No task needed.
- **§6, `frontend/src/types/carePlan.ts`**: confirmed the six existing `source_fact_ids` fields are correctly absent from every corresponding TS interface (stripped server-side before the frontend ever sees them), and `ReasonForVisit`'s/`DiagnosisDetail`'s/`Diagnosis`'s TS interfaces need no change for the same reason. **One pre-existing, unrelated inconsistency confirmed while checking this**: `CarePlanContent.summary_fact_ids: number[]` is declared as a required field in `carePlan.ts`, but `_strip_internal_provenance` always pops this key before the API response — the type asserts a shape that is never true at runtime. This is not fixed here; it is PRD 08's file to own (PRD §9's resolved hand-off). No task in this list touches `carePlan.ts`.

## Discrepancies found between PRD §4.9 and the real code (flagged, not silently corrected)

- **§4.9's "16 call sites across 4 files" does not hold.** Grepped `DiagnosisDetail(` and `ReasonForVisit(` directly (two independent passes: a plain `grep -rn` and a per-file `grep -c`) across `backend/` and `frontend/src` — the real count is **8 call sites across the same 4 files** the PRD names (`test_pipeline_assembly.py`: 2, `test_pipeline_review.py`: 2, `test_term_detection.py`: 2, `test_jobs_e2e_scenarios.py`: 2). This does not change scope — all three new fields default to `[]`, so none of the 8 sites needs an edit to keep constructing, exactly as §4.9 concludes for its (overstated) 16 — but the count itself is roughly 2x too high and should not be repeated in any future document without re-verifying.
- **Two additional real test breakages exist that PRD §4.9/§7.2 do not name**, found by reading `test_pipeline_assembly.py` directly rather than trusting the PRD's "no edit required for existing tests to keep passing" claim for that file: `test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched` and `test_assemble_and_render_preserves_merged_diagnosis_variants` both break once Task 3 lands (detailed in Task 3's "accepted interim consequence" and fixed in Task 5). §4.9 asserts "no edit required" for this file's *existing* tests; that holds for compilation but not for these two behavioral assertions, which is exactly the kind of thing this task-authoring pass was asked to verify rather than hand-wave.

No genuinely live `[OPEN]` item was found in PRD §9 — both `[OPEN` substrings in the PRD are prose references to items already resolved elsewhere in the same document (confirmed by reading each in context).

## Summary of what requires you (not a dev agent)

Per PRD §8, this is a session-local, judgement-based check against real infrastructure that cannot be automated by a dev agent:

1. **Prompt smoke test against a real note with a diagnosis section**, run via ngrok + pm2 (`SERVICE_MODE=combined`), once Tasks 1-8 have landed:
   - Confirm `diagnosis.details[]` and `reason_for_visit[]` items in the pipeline's internal (pre-strip) output carry non-empty, plausible `source_fact_ids` — not just an empty list the new deterministic guard then silently accepts as "nothing to drop."
   - Confirm a note stating something changed since the last visit produces a non-empty `changed_since_last_visit` *and* a non-empty `changed_since_last_visit_fact_ids` together, never one without the other.
   - Feed a note with an ambiguous/borderline diagnosis-category fact and confirm the model's `diagnosis.details` vs. `low_priority` judgment still tracks the LOW PRIORITY rule correctly now that `diagnosis.details` items also carry a citation obligation.
   - Confirm the "What the Doctor Found" card still renders normally end-to-end for a well-behaved note (no attempted-but-uncited diagnosis silently vanishing when it shouldn't).

No new environment variables, credentials, or console configuration are needed — this PRD is schema + prompt + pure Python + two bounded frontend edits (PRD §8).
