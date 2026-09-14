# Tasks: Merge Provenance

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config — the six `source_fact_ids`-bearing item models this PRD reads but does not modify, and the precedent that a default/self-reported value must earn its place); 04 (`assemble_and_render.txt`'s MERGE paragraph and `_verify_assembly`, both edited here — both already landed in this repo, verified by reading). Depended on by: nothing directly (blocking). Shares two files with 13 (absent-value-contract) — `care_plan.py` (this PRD makes **no edit** to it) and `assemble_and_render.txt` (this PRD edits only the MERGE paragraph; 13 edits the adjacent NOT STATED paragraph — confirmed non-overlapping, §4.7). Related, non-blocking: 18 (diagnosis-soundness) will later add `source_fact_ids` to `DiagnosisDetail`/`ReasonForVisit`, which extends this PRD's free `len(source_fact_ids) > 1` signal to diagnosis-category merges — not this PRD's job, mentioned for context only.

**Headline scope note**: PRD §4.1 is a rejection — `merged: bool` does not earn its place over the already-free `len(source_fact_ids) > 1` signal. **No schema change in this task list.** The work is: harden the MERGE paragraph's prompt text (§4.2), add regression fixtures (§4.3), and make merges findable in logs via a log-only aggregate signal, no new field (§4.4).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q`. Single file: `python -m pytest tests/care_plan/test_pipeline_assembly.py -q`; single test: `... ::test_name -q`.
- Lint: `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, Non-Goals) — no frontend test commands needed.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited. In particular: do not add a `merged: bool` field anywhere — §4.1 explicitly rejects it, and re-adding it under a different name would undo this PRD's own conclusion.
- Carry PRD prompt/code snippets verbatim — do not paraphrase them.
- **Line-number note**: verified against the real, already-landed code at authoring time. `backend/care_plan/pipeline.py`: `_ITEM_LIST_FIELDS` at line 349, `_verify_assembly` at lines 394-446 (the `for field in _ITEM_LIST_FIELDS:` loop at 420-444). `backend/care_plan/prompts/assemble_and_render.txt`: the `MERGE --` paragraph is line 30 (one line, between the `NOT STATED --` and `LOW PRIORITY --` paragraphs). `backend/utils/constants.py`: `LOG_EXTRA_KEYS` at lines 164-171, currently 24 entries, containing none of PRDs 10/11/12's own additions yet (verified — those PRDs have not landed in this repo as of this writing). Locate everything below by symbol/grep, not by these line numbers — sibling PRDs 10, 11, 12, 13, and 18 also land in `pipeline.py`, `assemble_and_render.txt`, `care_plan.py`, and `constants.py`, and whichever lands first will shift the others' line numbers.
- **Note on file drift already observed**: `assemble_and_render.txt` and `pipeline.py` already carry an unrelated, previously-landed change not attributable to this batch's PRDs 10-18 — a `{style_rules}` placeholder and a `_STYLE_RULES` constant (extracted PII/style rules shared with `correct.txt`). This does not affect the MERGE paragraph or `_verify_assembly`'s shape; it is noted only so the dev agent isn't surprised the file doesn't look byte-for-byte like an untouched PRD-04-era file. The MERGE paragraph itself, and `_verify_assembly`'s `for field in _ITEM_LIST_FIELDS:` loop, were verified to match this PRD's PRD.md §4.2/§4.4 "current text"/"current code" quotes exactly.

## Confirmed no-change items (§4.5, §4.6, §4.7) — recorded here, not tasks

- **§4.5 `_strip_internal_provenance`** (`backend/routes/worker.py:36-54`) — confirmed by reading: it already strips `raw`, `summary_fact_ids`, and per-item `source_fact_ids` from the six `_ITEM_LIST_FIELDS` lists. This PRD adds no new field to `CarePlan` or any item model (§4.1's `merged: bool` is rejected; §4.4's signal is a `logger.info` call, never attached to the `CarePlan` object or serialized into `output_data["care_plan"]`). **No change needed here, confirmed against the real code.**
- **§4.6 `_diff_item`/`_verify_correction_diff`** (`backend/care_plan/pipeline.py:568-632`) — confirmed by reading: since no new field is added, there is no new leaf for the corrector-diff machinery to compare. **Moot, no change needed, confirmed against the real code.**
- **§4.7 seam with PRD 13** — confirmed by reading `assemble_and_render.txt` in full: the `MERGE --` paragraph (this PRD, Task 1 below) and the `NOT STATED --` paragraph (PRD 13's territory) are adjacent but textually independent — no shared sentence needs to satisfy both PRDs. This PRD makes no edit to `care_plan.py` at all, so PRD 13's `_normalize_why` validators have nothing from this PRD to rebase against. **No conflict, confirmed against the real code; 13 and 14 can land in either order.**
- **The one place the free signal doesn't reach** (§4.1, §9 `[RESOLVED]`): `Diagnosis`/`DiagnosisDetail` (`backend/models/care_plan/care_plan.py:13-28`) carry no `source_fact_ids` field today — confirmed by reading. This means `len(source_fact_ids) > 1` cannot observe a diagnosis-category merge (the MERGE paragraph's own worked example is a diagnosis merge) until PRD 18 adds `source_fact_ids` to `DiagnosisDetail`/`ReasonForVisit`. This is a soft, non-blocking ordering note only — nothing for this task list to build; PRD 18 owns that schema change.

---

### Task 1 — Harden the MERGE paragraph in `assemble_and_render.txt`

   - Files: `backend/care_plan/prompts/assemble_and_render.txt`
   - Changes (PRD §4.2): Replace the current one-line `MERGE --` paragraph (verified verbatim in the file today) with the new four-line paragraph. Do not touch any other paragraph in the file (in particular, leave `NOT STATED --` and `LOW PRIORITY --` untouched — PRD 13's and this PRD's edits are confirmed non-adjacent, see "Confirmed no-change" note above).

     Old (the entire current `MERGE --` paragraph, one line):
     ```
     MERGE -- if two or more facts describe the identical underlying clinical fact (the same finding or instruction, stated more than once, possibly with different specific details), merge them into ONE item. Preserve every differing detail explicitly in the merged wording -- never drop one to shorten the sentence. Example: plaque reported separately in the left and right coronary arteries merges to "heavy plaque in your left and right heart arteries," NEVER to "heavy plaque in your heart arteries." Do not merge facts that are merely related; only merge facts that say the same thing.
     ```

     New (replaces the line above, verbatim from PRD §4.2):
     ```
     MERGE -- if two or more facts describe the identical underlying clinical fact (the same finding or instruction, stated more than once, possibly with different specific details), merge them into ONE item. Preserve every differing detail explicitly in the merged wording, no matter how many facts merge -- never drop one to shorten the sentence, and never fall back to a vaguer collective term once naming each one individually gets long.
     Example (two variants): plaque reported separately in the left and right coronary arteries merges to "heavy plaque in your left and right heart arteries," NEVER to "heavy plaque in your heart arteries."
     Example (three variants): calcified plaque reported separately in the right coronary artery, the left anterior descending artery, and the circumflex artery merges to "heavy calcified plaque in your right coronary, left anterior descending, and circumflex arteries," NEVER to "heavy calcified plaque in your heart arteries," and NEVER to "heavy calcified plaque in your right coronary and left anterior descending arteries" (silently dropping the third site is exactly as wrong as dropping to a collective term -- every site names once, however many there are).
     Do not merge facts that are merely related; only merge facts that say the same thing. Record the id of every fact that went into a merged item in that item's source_fact_ids (see SOURCE_FACT_IDS) -- an item built from more than one fact is the signal that a merge happened here.
     ```
     Keep the surrounding blank lines that separate this paragraph from `NOT STATED --` above and `LOW PRIORITY --` below exactly as they are today (one blank line on each side) — only the paragraph's own internal text grows from one line to four.
   - Acceptance criteria:
     - `grep -c "left and right heart arteries" backend/care_plan/prompts/assemble_and_render.txt` returns at least 1 (two-site example preserved verbatim).
     - `grep -c "circumflex" backend/care_plan/prompts/assemble_and_render.txt` and `grep -c "left anterior descending" backend/care_plan/prompts/assemble_and_render.txt` both return at least 1 (new three-site example present).
     - `grep -c "no matter how many facts merge" backend/care_plan/prompts/assemble_and_render.txt` returns at least 1.
     - `python -c "from care_plan.pipeline import _ASSEMBLE_PROMPT; s=_ASSEMBLE_PROMPT.index('\nMERGE --'); e=_ASSEMBLE_PROMPT.index('\nLOW PRIORITY --'); sec=_ASSEMBLE_PROMPT[s:e]; assert 'source_fact_ids' in sec; assert 'circumflex' in sec"` (from `backend/`) succeeds — confirms the new cross-reference sentence and the three-site example both land inside the MERGE paragraph specifically, not merely somewhere in the file.
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py::test_assemble_prompt_contains_merge_example -q` (from `backend/`) still passes unchanged (existing two-site guard, PRD §7.4).
     - Permanently covered by Task 3's new prompt-text guard tests.

### Task 2 — Regression fixtures in `test_pipeline_assembly.py`: three-way merge and a non-diagnosis merged item

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py`
   - Dependency: independent of Task 1 (these fixtures exercise the deterministic pipeline layer against a canned LLM response — they do not read `_ASSEMBLE_PROMPT` — so they do not require Task 1 to have landed first, though landing after Task 1 is the natural reading order). Requires no other change.
   - Changes (PRD §4.3, Fixtures 1 and 2): Add both tests to the "Merge rule preserving variants" section, immediately after the existing `test_assemble_and_render_preserves_merged_diagnosis_variants` (kept as-is, unmodified — it is not replaced). Insert verbatim:

     ```python
     def test_assemble_and_render_preserves_merged_diagnosis_variants_three_way():
         """Regression fixture for brainstorm.v1.md §5's named risk: 'merging
         near-duplicate findings may quietly lose an anatomical variant.' Uses
         three sites, not two, deliberately -- two is the number the prompt's
         own worked example uses, so a two-site fixture cannot distinguish
         genuine generalization from copying the example verbatim."""
         pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
         facts = [Fact(id=1, category="diagnosis", unit_id=1, char_start=0, char_end=1, text="x")]
         pipeline._generate_json = lambda *a, **k: {
             **_minimal_care_plan_response(),
             "diagnosis": {
                 "changed_since_last_visit": "",
                 "details": [
                     {
                         "title": "Coronary artery disease",
                         "plain_name": "clogged heart arteries",
                         "description": (
                             "heavy calcified plaque in your right coronary, "
                             "left anterior descending, and circumflex arteries"
                         ),
                         "what_it_means_for_you": "",
                         "severity": None,
                     }
                 ],
             },
         }

         result = pipeline.assemble_and_render(facts, [], [], [])

         description = result.diagnosis.details[0].description
         assert "right coronary" in description
         assert "left anterior descending" in description
         assert "circumflex" in description


     def test_assemble_and_render_merged_item_carries_all_source_fact_ids():
         """The merge signal this PRD keeps (§4.1): a merged item's
         source_fact_ids length is the free, always-available 'a merge may
         have happened here' marker. This fixture proves it survives
         _verify_assembly's citation-existence check (PRD 04 §4.4) intact --
         a merge is not itself flagged as a hallucination just because it
         cites more than one fact."""
         pipeline = CarePlanPipeline.__new__(CarePlanPipeline)
         facts = [
             Fact(id=1, category="tests", unit_id=1, char_start=0, char_end=1, text="x"),
             Fact(id=2, category="tests", unit_id=2, char_start=0, char_end=1, text="y"),
         ]
         pipeline._generate_json = lambda *a, **k: {
             **_minimal_care_plan_response(),
             "tests": [
                 {
                     "description": "elevated readings on your left and right arm blood pressure cuffs",
                     "status": "done",
                     "source_fact_ids": [1, 2],
                 }
             ],
         }

         result = pipeline.assemble_and_render(facts, [], [], [])

         assert result.tests[0].source_fact_ids == [1, 2]
         assert "left" in result.tests[0].description
         assert "right" in result.tests[0].description
     ```
     No new imports needed — `CarePlanPipeline`, `Fact`, `_minimal_care_plan_response` are already imported/defined in this file.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -k "three_way or merged_item_carries_all_source_fact_ids" -q` (from `backend/`) passes, 2 tests.
     - The existing `test_assemble_and_render_preserves_merged_diagnosis_variants` is untouched and still passes (kept alongside, not replaced, per PRD §7.4).

### Task 3 — Prompt-text guard tests in `test_pipeline_prompts.py`

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 1 (asserts on the new prompt text Task 1 adds).
   - Changes (PRD §4.3 "Prompt-text guard", §7.2): Add both tests immediately after the existing `test_assemble_prompt_contains_merge_example` (do not modify that test):

     ```python
     def test_assemble_prompt_contains_three_way_merge_example():
         assert "circumflex" in _ASSEMBLE_PROMPT
         assert "left anterior descending" in _ASSEMBLE_PROMPT


     def test_assemble_prompt_merge_rule_names_source_fact_ids():
         merge_start = _ASSEMBLE_PROMPT.index("\nMERGE --")
         next_section_start = _ASSEMBLE_PROMPT.index("\nLOW PRIORITY --")
         merge_section = _ASSEMBLE_PROMPT[merge_start:next_section_start]

         assert "source_fact_ids" in merge_section
     ```
     `test_assemble_prompt_merge_rule_names_source_fact_ids` is sliced the same way `test_assemble_prompt_not_stated_rule_names_all_four_why_fields` (in `test_pipeline_assembly.py`) slices its own paragraph — `\n<NAME> --` to the next `\n<NAME> --`. No new imports needed — `_ASSEMBLE_PROMPT` is already imported at the top of this file.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py -k "three_way_merge_example or merge_rule_names_source_fact_ids" -q` (from `backend/`) passes, 2 tests.
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full (no regression to the 3 preexisting `_ASSEMBLE_PROMPT` content-guard tests, `test_assemble_prompt_contains_not_stated_sentinel`/`test_assemble_prompt_contains_merge_example`/`test_assemble_prompt_questions_rule_has_no_minimum`/`test_assemble_prompt_lists_all_eight_mapping_rows`).

### Task 4 — `_verify_assembly`: compute and log the `merge_candidate_signal` aggregate

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: independent of Tasks 1-3. Land before Task 6 (which tests this code).
   - Changes (PRD §4.4): Inside `_verify_assembly`'s `for field in _ITEM_LIST_FIELDS:` loop, add per-field multi-fact counting, and after the loop (before the final `return`), add one aggregate `logger.info` call. This is the load-bearing, log-only, non-gating "findable in logs" signal — do not attach it to the `CarePlan` object, do not add a return value, do not make it fatal or gating in any way.

     Old (the current loop and return, verified verbatim in the file today):
     ```python
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

         return model.model_copy(update=updates) if updates else model
     ```

     New (replaces the block above verbatim, additions only — no line inside the old block is removed or reordered):
     ```python
         multi_fact_counts: dict[str, int] = {}
         for field in _ITEM_LIST_FIELDS:
             items = getattr(model, field)
             kept = []
             changed = False
             multi_fact = 0
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
                 if len(cited) > 1:
                     multi_fact += 1
                 kept.append(item)
             if multi_fact:
                 multi_fact_counts[field] = multi_fact
             if changed:
                 updates[field] = kept

         total_multi_fact = sum(multi_fact_counts.values())
         logger.info(
             "assemble_and_render: %d item(s) across %d section(s) cite more than "
             "one fact -- candidate near-duplicate merges (a superset: an item "
             "legitimately built from several complementary facts also counts), "
             "by section: %s",
             total_multi_fact, len(multi_fact_counts), multi_fact_counts,
             extra={"merge_candidate_signal": {
                 "total": total_multi_fact, "by_section": multi_fact_counts,
             }},
         )

         return model.model_copy(update=updates) if updates else model
     ```
     Note the count uses `cited` (post-hallucination-cleanup), never `item.source_fact_ids` directly — an id about to be dropped as hallucinated must not inflate the merge-candidate count (PRD §4.4 design choice, tested explicitly in Task 6). Note also the signal is named `merge_candidate_signal` (not `merged_items`) and the log message says "candidate... a superset" — do not rename either; §4.1/§4.4 establish this is deliberately a superset signal, not a confirmed-merge count.
   - Acceptance criteria:
     - `grep -n "multi_fact_counts\|merge_candidate_signal" backend/care_plan/pipeline.py` shows the new local variable, the per-field counter, and the `extra={"merge_candidate_signal": ...}` call.
     - `python -m pytest tests/care_plan/ -q` (from `backend/`) passes in full — this change is additive only (new local state, one new log call) and must not alter any existing `_verify_assembly` test's outcome (drops, truncation, corrections all unchanged).
     - Permanently covered by Task 6's new tests.

### Task 5 — `Constants.Observability.LOG_EXTRA_KEYS`: add `"merge_candidate_signal"`

   - Files: `backend/utils/constants.py`
   - Dependency: independent of Task 4 in terms of code (different file), but logically pairs with it — land after Task 4 so the signal this key gates already exists.
   - Changes (PRD §4.4, §9 coordination note): Add one entry, `"merge_candidate_signal"`, to the `LOG_EXTRA_KEYS` list (`backend/utils/constants.py:164-171` as of authoring — locate by the `LOG_EXTRA_KEYS: list[str] = [` line, not by line number). **Append it to the list as it stands at the time you make this edit — do not paste over the list with the snippet below if PRDs 10, 11, or 12 have already landed their own entries (`"coverage_signal"`, `"extraction_signal"`, `"extraction_signal_facts"`) by then.** As of this writing none of those three have landed in this repo (verified: the list has exactly 24 entries today, none of them any of the four PRD-10/11/12/14 additions), so if you are implementing this task before any of 10/11/12 land, the list becomes:
     ```python
     LOG_EXTRA_KEYS: list[str] = [
         "user_id", "function", "care_plan_version", "grading_version", "input_version",
         "operation", "metric", "metric_type", "duration_ms", "success", "outcome",
         "step_name", "status", "http_method", "http_path", "http_status",
         "http_status_code", "total_duration_ms", "saved_id", "input_chars",
         "error", "labels", "duration_ms_observed", "OpOutcome",
         "service", "environment",
         "merge_candidate_signal",   # PRD 14
     ]
     ```
     If one or more of 10/11/12's entries are already present, add only the `"merge_candidate_signal",   # PRD 14` line (anywhere in the list, trailing comment included) and leave every other entry exactly as you found it.
   - Acceptance criteria:
     - `python -c "from utils.constants import Constants; assert 'merge_candidate_signal' in Constants.Observability.LOG_EXTRA_KEYS"` (from `backend/`) succeeds.
     - Every entry present in `LOG_EXTRA_KEYS` before this edit is still present after it (no entry dropped) — `git diff backend/utils/constants.py` shows only added line(s), no removed lines.
     - Permanently covered by Task 7's `test_constants.py` addition.

### Task 6 — New `_verify_assembly` tests for the `merge_candidate_signal` aggregate

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py`
   - Dependency: land after Task 4.
   - Changes (PRD §7.1): Add a new section (after the existing "Content-richness floor" section, at the end of the file), using the file's established `CarePlan(...)`/`_verify_assembly(model, facts)` direct-construction convention (see `test_verify_assembly_truncates_questions_over_three` and neighbors for the pattern) and the file's existing `caplog.at_level(...)` convention (see the content-richness tests):

     ```python
     # ---------------------------------------------------------------------------
     # merge_candidate_signal aggregate (§4.4)
     # ---------------------------------------------------------------------------

     def test_verify_assembly_logs_merge_candidate_signal_aggregate(caplog):
         model = CarePlan(
             medications=[_make_item("medications", [1, 2])],
             tests=[_make_item("tests", [3])],
         )
         facts = [
             Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a"),
             Fact(id=2, category="medications", unit_id=1, char_start=0, char_end=1, text="b"),
             Fact(id=3, category="tests", unit_id=1, char_start=0, char_end=1, text="c"),
         ]

         with caplog.at_level(logging.INFO):
             _verify_assembly(model, facts)

         signal_records = [r for r in caplog.records if hasattr(r, "merge_candidate_signal")]
         assert len(signal_records) == 1
         assert signal_records[0].merge_candidate_signal == {
             "total": 1, "by_section": {"medications": 1},
         }


     def test_verify_assembly_logs_merge_candidate_signal_zero_when_no_multi_fact_items(caplog):
         model = CarePlan(medications=[_make_item("medications", [1])])
         facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

         with caplog.at_level(logging.INFO):
             _verify_assembly(model, facts)

         signal_records = [r for r in caplog.records if hasattr(r, "merge_candidate_signal")]
         assert len(signal_records) == 1
         assert signal_records[0].merge_candidate_signal == {"total": 0, "by_section": {}}


     def test_verify_assembly_merge_candidate_count_excludes_dropped_hallucinated_ids(caplog):
         model = CarePlan(medications=[_make_item("medications", [1, 999])])
         facts = [Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="a")]

         with caplog.at_level(logging.INFO):
             _verify_assembly(model, facts)

         signal_records = [r for r in caplog.records if hasattr(r, "merge_candidate_signal")]
         assert len(signal_records) == 1
         assert signal_records[0].merge_candidate_signal == {"total": 0, "by_section": {}}
     ```
     The third test is the regression guard for the "counted post-cleanup, not pre-cleanup" design choice in §4.4: `source_fact_ids=[1, 999]` has 2 raw ids but only 1 valid one, so after `_verify_assembly`'s existing hallucination-cleanup the item's `cited` length is 1, not 2 — it must not count toward `multi_fact_counts`.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -k merge_candidate_signal -q` (from `backend/`) passes, 3 tests.
     - `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` (from `backend/`) passes in full.

### Task 7 — `test_constants.py`: assert `"merge_candidate_signal"` is whitelisted

   - Files: `backend/tests/utils/test_constants.py`
   - Dependency: land after Task 5.
   - Changes (PRD §7.3): Extend `test_observability_namespace` with one new assertion, immediately after the existing `assert "user_id" in Constants.Observability.LOG_EXTRA_KEYS` line:
     ```python
     assert "merge_candidate_signal" in Constants.Observability.LOG_EXTRA_KEYS
     ```
   - Acceptance criteria:
     - `python -m pytest tests/utils/test_constants.py -q` (from `backend/`) passes in full.

### Task 8 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-7.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors attributable to this PRD's changes.
     - `python -c "from care_plan.pipeline import _ASSEMBLE_PROMPT; assert 'circumflex' in _ASSEMBLE_PROMPT and 'left and right heart arteries' in _ASSEMBLE_PROMPT"` (from `backend/`) succeeds.
     - `grep -rn "merged: bool\|merged:bool" backend --include=*.py` returns zero hits anywhere in the repo (confirms §4.1's rejection was not accidentally re-added under any spelling).
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched (`care_plan/pipeline.py`, `care_plan/prompts/assemble_and_render.txt` is not lint-checked but confirm it's saved with no trailing-whitespace issues, `tests/care_plan/test_pipeline_assembly.py`, `tests/care_plan/test_pipeline_prompts.py`, `tests/utils/test_constants.py`, `utils/constants.py`).

---

## Summary of what requires you (not a dev agent)

Per PRD §8, these are session-local, judgement-based checks against real infrastructure and cannot be automated by a dev agent:

1. **Prompt smoke test against real notes**, once this PRD's prompt text (Task 1) is live in a deployed/runnable environment: run via ngrok + pm2, `SERVICE_MODE=combined`, against 2-3 real or realistic de-identified notes containing a genuine multi-site finding (e.g., a cardiac catheterization or angiogram report naming plaque, stenosis, or occlusion at three or more named vessels). Confirm the model actually names all affected sites in the merged item — not a collective term, and not a silent partial drop. This is the live-model half of §4.3's fixture that cannot be a deterministic `pytest` case (matches PRD 04 §8's identical two-site item, extended to three; PRD 03 §8's reasoning about a real-model judgment call applies the same way here).
2. **Spot-check the `merge_candidate_signal` log line** on the same smoke-test runs: confirm it appears in local/plain-text logs with sane `by_section` counts, and — if you have Cloud Logging access for a deployed environment at the point this eventually ships — confirm the structured JSON payload actually carries the `merge_candidate_signal` field once `K_SERVICE` is set (the exact "looks fine locally, silently vanishes in production" footgun PRD 11 §4.3 already flagged for its own key; worth re-checking rather than assuming Task 5's `LOG_EXTRA_KEYS` addition alone guarantees it end-to-end).
3. No new environment variables, credentials, or console configuration are needed for this PRD (§8) — it is prompt text, one small `pipeline.py` diff, one `constants.py` entry, and tests only.

No PRD §9 items are `[OPEN]` — the gate was clear (all live items are `[RESOLVED]` or explicitly `[DEFERRED]` with no action required of this task list). All 8 tasks above derive from `[RESOLVED]` decisions only.
