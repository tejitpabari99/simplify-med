# Tasks: Assemble and Render

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — `backend/models/care_plan/care_plan.py`'s settled `CarePlan`/item-model shape (`status`, `source_fact_ids`, `summary_fact_ids`, nullable `WarningSign.urgency`); 03 (grounding) — `CarePlanPipeline.ground(...) -> list[Fact]`, plus `_is_informative_quote`/`_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH` (reused verbatim, same module, no import), `models.ledger.Fact`/`FactCategory`/`Unit`. Neither 01's nor 03's code exists in this repo yet; their tasks are tracked in `prds/01-schema-and-config/TASKS.md` and `prds/03-grounding/TASKS.md` and are **not** duplicated here. Depended on by: 05 (review-and-correct, re-checks this step's output against the same ledger), 06 (pipeline-orchestration, wires `assemble_and_render` into `iter_steps`), 07 (glossary, whose `render_care_plan_text`/`build_glossary_from_care_plan` re-detect against this step's `CarePlan` output), 08 (frontend, renders this step's output).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Prerequisite check**: before starting Task 3, confirm `python -c "from care_plan.pipeline import CarePlanPipeline, _is_informative_quote, _QUOTE_MIN_LENGTH, _QUOTE_LONG_WORD_MIN_LENGTH; from models.ledger import Fact, FactCategory, Unit; assert hasattr(CarePlanPipeline, 'ground')"` (from `backend/`) succeeds — if it doesn't, PRD 01's Task 4 and/or PRD 03's Tasks 1-5 haven't landed yet and must land first. Task 1 and Task 2 below do not require this (they touch only prompt files and the three doomed methods, none of which depend on 01/03).
- **Line-number note**: the current `backend/care_plan/pipeline.py` (read at authoring time, before 01/03 have landed) has `simplify_language_with_term_plan` at lines 96-114, `clarify_and_action` at 116-130, `structure_appointment_note` at 132-150, `_STRUCTURING_SCHEMA` at 60-63, and the three prompt loads at 67-69. By the time this PRD's tasks run, 03 will already have inserted `ground()` and its helpers earlier in the same file (purely additive, per 03's own task list — it does not touch these methods), which shifts these line numbers down. Locate everything below by symbol/content, not by the line numbers above — they are for orientation only.

---

### Task 1 — New prompt file `backend/care_plan/prompts/assemble_and_render.txt`

   - Files: `backend/care_plan/prompts/assemble_and_render.txt` (new file)
   - Changes (PRD §4.1): Create the file with exactly the text given in PRD §4.1's "Full proposed text" block — the four-step instruction list, the FACTS placeholder, the full eight-row MAPPING table (including the medications/side-effects routing rule and the SOURCE_FACT_IDS/STATUS/NOT STATED/MERGE/LOW PRIORITY/QUESTIONS/PII/LANGUAGE RULES sections in full, with the worked merge example and the `"Doctor Alok Singh"` → `"your doctor"` PII example), and the `{schema}`/`{facts_block}`/`{sub_block}`/`{medical_block}`/`{abbrev_block}` placeholders. Copy the block verbatim — do not paraphrase or reformat it; PRD §7.2's regression tests assert on exact substrings (e.g. `"Not stated in your note."`, `"left and right heart arteries"`, `"no minimum"`) and the exact absence of `"exactly three"`/`"exactly 3"`.
   - Acceptance criteria:
     - The file exists at `backend/care_plan/prompts/assemble_and_render.txt`, is non-empty, and contains the literal placeholders `{schema}`, `{facts_block}`, `{sub_block}`, `{medical_block}`, `{abbrev_block}` exactly once each.
     - `grep -c "Not stated in your note." backend/care_plan/prompts/assemble_and_render.txt` returns at least 1.
     - `grep -c "left and right heart arteries" backend/care_plan/prompts/assemble_and_render.txt` returns at least 1.
     - `grep -c "Doctor Alok Singh" backend/care_plan/prompts/assemble_and_render.txt` and `grep -c "your doctor" backend/care_plan/prompts/assemble_and_render.txt` both return at least 1.
     - `grep -c "no minimum" backend/care_plan/prompts/assemble_and_render.txt` returns at least 1; `grep -c "exactly three\|exactly 3" backend/care_plan/prompts/assemble_and_render.txt` returns 0.
     - Each of `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs` appears in the file's MAPPING section.
     - Covered permanently by Task 6's `test_pipeline_prompts.py` additions.

### Task 2 — Delete the three old prompt files, the three old pipeline methods, their prompt loads, and `_STRUCTURING_SCHEMA`; update the module docstring

   - Files: `backend/care_plan/pipeline.py`; delete `backend/care_plan/prompts/simplify_language.txt`, `backend/care_plan/prompts/clarify_and_action.txt`, `backend/care_plan/prompts/structure_note.txt`
   - Changes (PRD §4.2):
     - Delete the three methods `simplify_language_with_term_plan`, `clarify_and_action`, `structure_appointment_note` from `CarePlanPipeline` in their entirety (currently, pre-01/03, at `pipeline.py:96-150` — see this file's line-number note above).
     - Delete the three prompt-load lines:
       ```python
       _SIMPLIFY_PROMPT  = (_PROMPTS_DIR / "simplify_language.txt").read_text(encoding="utf-8")
       _CLARIFY_PROMPT   = (_PROMPTS_DIR / "clarify_and_action.txt").read_text(encoding="utf-8")
       _STRUCTURE_PROMPT = (_PROMPTS_DIR / "structure_note.txt").read_text(encoding="utf-8")
       ```
     - Delete the `_STRUCTURING_SCHEMA` constant:
       ```python
       _STRUCTURING_SCHEMA = json.dumps(
           _llm_schema(CarePlan, exclude={"terms", "raw", "note"}),
           indent=2,
       )
       ```
       (By the time this task lands, 01 has already deleted `CarePlan.raw`, so this exclude set may already read `exclude={"terms", "note"}` — either form, delete the whole constant; it is being replaced by Task 3's `_ASSEMBLE_SCHEMA`, not edited in place.)
     - Delete the three prompt files: `backend/care_plan/prompts/simplify_language.txt`, `backend/care_plan/prompts/clarify_and_action.txt`, `backend/care_plan/prompts/structure_note.txt`.
     - Update the module docstring (currently `pipeline.py:1-14`): change the sentence "Deterministic term detection (AHRQ + Michigan + abbreviations) via JSON, followed by three LLM steps that simplify, clarify, and structure the note into a typed CarePlan." to describe the new shape — PRD §4.2's suggested wording: "...followed by one grounding step that extracts evidence-linked facts and one assembly step that renders them into a typed CarePlan." Leave the numbered `Steps: 1-5` list immediately below it completely untouched — renumbering it against the real `Constants.Pipeline.PIPELINE_STEPS` enum is 06's job (PRD §4.2, explicitly out of scope here).
   - **Known, accepted consequence (PRD §3, §9 `[RESOLVED]`)**: after this task lands, `CarePlanPipeline.iter_steps()`/`.run()` will raise `AttributeError` on any real (non-mocked) invocation, because `iter_steps` (untouched here — 06's job) still calls `self.simplify_language_with_term_plan(...)`, `self.clarify_and_action(...)`, `self.structure_appointment_note(...)` by name. This is expected and does not block this task — nothing is deployed in the interim (global no-deploy constraint), and no test in this repo calls these methods without stubbing them first (confirmed: `tests/care_plan/test_pipeline_streaming.py` and `tests/care_plan/test_pipeline_executors.py` always assign instance-level mocks before calling `iter_steps`/`run`, so they stay green). Do not attempt to fix `iter_steps` in this task.
   - Acceptance criteria:
     - `grep -rn "simplify_language_with_term_plan\|clarify_and_action\|structure_appointment_note\|_SIMPLIFY_PROMPT\|_CLARIFY_PROMPT\|_STRUCTURE_PROMPT\|_STRUCTURING_SCHEMA" backend/care_plan/pipeline.py` returns zero hits.
     - `backend/care_plan/prompts/simplify_language.txt`, `backend/care_plan/prompts/clarify_and_action.txt`, `backend/care_plan/prompts/structure_note.txt` no longer exist.
     - `python -m pytest tests/care_plan/test_pipeline_streaming.py tests/care_plan/test_pipeline_executors.py -q` (from `backend/`) still passes in full (proves the accepted breakage above is confined to real invocation, not test coverage).
     - The module docstring no longer says "three LLM steps that simplify, clarify, and structure"; the numbered `Steps:` list is byte-for-byte unchanged.

### Task 3 — `backend/care_plan/pipeline.py`: `_ASSEMBLE_PROMPT`, `_ASSEMBLE_SCHEMA`, `_FACT_CATEGORY_ORDER`, `_format_facts_for_prompt`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 1 (prompt file must exist) and Task 2 (removes the constant this replaces), and after the prerequisite check above (`Fact` import already present in this file from 03's Task 3 — no new import needed for it).
   - Changes (PRD §4.3): Add, alongside 03's `_GROUND_PROMPT` load and `_format_units_for_prompt` helper:
     ```python
     _ASSEMBLE_PROMPT = (_PROMPTS_DIR / "assemble_and_render.txt").read_text(encoding="utf-8")
     ```
     ```python
     _ASSEMBLE_SCHEMA = json.dumps(
         _llm_schema(CarePlan, exclude={"terms", "note"}),
         indent=2,
     )
     ```
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
     `json` and `_llm_schema` are already used/defined earlier in this module — no new imports needed for this task. Do not touch `ground()`, `_GROUND_PROMPT`, `_GROUNDING_SCHEMA`, or any of 03's helper functions.
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _ASSEMBLE_PROMPT, _ASSEMBLE_SCHEMA, _FACT_CATEGORY_ORDER, _format_facts_for_prompt"` (from `backend/`) succeeds.
     - `json.loads(pipeline_module._ASSEMBLE_SCHEMA)` has `"terms"` and `"note"` absent from `properties`, `"summary_fact_ids"` and `"medications"` present, and `"source_fact_ids"` present under `properties["medications"]["items"]["properties"]`.
     - `_format_facts_for_prompt` groups facts by `_FACT_CATEGORY_ORDER`'s order regardless of input order, and each output line matches `f"[{id}] {category}: {text}"`.
     - Every existing test in `backend/tests/care_plan/` still passes unchanged (`python -m pytest tests/care_plan/ -q` from `backend/`) — this task is purely additive to the module (on top of Task 2's deletions).
     - Covered permanently by Task 7's `test_pipeline_schema.py` addition and Task 8's `test_pipeline_assembly.py` mapping tests.

### Task 4 — `CarePlanPipeline.assemble_and_render()`, `_verify_assembly()`, `_log_thin_fields()`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 3.
   - Changes (PRD §4.4, §4.5): Add the method to `CarePlanPipeline`, exactly as specified (including its full docstring, which documents the fatal-failure contract 06 will wire and why the return type is `CarePlan` not `dict`):
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
     `format_substitution_candidates_for_prompt`, `format_medical_terms_for_prompt`, `format_abbreviations_for_prompt` are already imported at the top of this file — no new import needed.

     Add the module-level constants and functions, alongside 03's `_verify_ledger`, again with full docstrings reproduced verbatim (each documents a specific, cited decision):
     ```python
     _ITEM_LIST_FIELDS = ("medications", "tests", "procedures", "other", "follow_up", "warning_signs")

     _RICHNESS_CHECKS: tuple[tuple[str, str], ...] = (
         ("reason_for_visit", "description"),
         ("medications", "why"),
         ("tests", "why"),
         ("tests", "description"),
         ("procedures", "why"),
         ("other", "why"),
         ("other", "description"),
     )


     def _log_thin_fields(model: CarePlan) -> None:
         """Logs (never mutates or drops) a why/description field that fails
         03's _is_informative_quote floor (PRD 04 §9). Observability only: unlike
         NOT STATED, there is no fallback value to substitute for a field the
         model DID fill in, and dropping an otherwise-backed item over one thin
         field would remove genuine content the brief's "remove nothing"
         principle protects. "Not stated in your note." (25 chars) always clears
         the length rule on its own, so the sentinel is never flagged here."""
         for field, attr in _RICHNESS_CHECKS:
             for item in getattr(model, field):
                 value = getattr(item, attr, "")
                 if value and not _is_informative_quote(value):
                     logger.warning(
                         "assemble_and_render: thin %s.%s field (%r) -- below "
                         "the content-richness floor; not corrected or dropped, "
                         "logged for prompt-quality review", field, attr, value,
                     )
         for detail in model.diagnosis.details:
             if detail.description and not _is_informative_quote(detail.description):
                 logger.warning(
                     "assemble_and_render: thin diagnosis.details[].description "
                     "field (%r) -- below the content-richness floor",
                     detail.description,
                 )


     def _verify_assembly(model: CarePlan, facts: list[Fact]) -> CarePlan:
         """Three deterministic, LLM-free guards on the assembled CarePlan (PRD 04
         §4.5), plus one LLM-free observability pass (content-richness, above).
         None of the three guards is fatal -- each corrects, filters, or drops in
         place and logs, matching 03's drop-and-continue policy for a fact that
         fails a per-item check (PRD 03 §4.5): a model deviation on one field, or
         one unbacked item, is not a reason to fail the whole step."""
         _log_thin_fields(model)
         updates: dict = {}

         if len(model.questions) > 3:
             logger.warning(
                 "assemble_and_render: truncating %d questions to 3", len(model.questions)
             )
             updates["questions"] = model.questions[:3]

         valid_ids = {fact.id for fact in facts}

         bad_summary_ids = [i for i in model.summary_fact_ids if i not in valid_ids]
         if bad_summary_ids:
             logger.warning(
                 "assemble_and_render: dropping summary_fact_ids not present in the "
                 "ledger: %s", bad_summary_ids,
             )
             updates["summary_fact_ids"] = [i for i in model.summary_fact_ids if i in valid_ids]

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
     `_is_informative_quote` is 03's function, already defined earlier in this same module — do not import it, do not redefine it.
   - Failure classification and budgets (PRD §4.5): `assemble_and_render` is fatal — no fallback, matching `ground()` (03) — because after this PRD lands there is no whole-document prose anywhere in the pipeline to fall back to. It raises `SimplifyError` on non-dict LLM output, on a `CarePlan` that fails Pydantic validation, or on an empty input ledger, and otherwise lets `LLMClient` exceptions propagate unchanged. Budgets: `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536), `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2). Wiring this fatal classification into `iter_steps` is 06's job — this task only implements the method itself.
   - Acceptance criteria:
     - `assemble_and_render` calls `self._generate_json` with `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature=Constants.Llm.TEMPERATURE_JSON`.
     - `assemble_and_render(facts=[], ...)` raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)` without calling `_generate_json`.
     - A non-dict LLM response raises `SimplifyError(ErrorCode.LLM_INVALID_JSON)`.
     - A response failing `CarePlan.model_validate` (e.g. an extra key) raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)`.
     - `_verify_assembly` truncates `questions` to the first 3 when the model returns more; leaves 0-2 unchanged.
     - `_verify_assembly` filters `summary_fact_ids` to ids present in the input `facts` list.
     - `_verify_assembly` drops any of the six `_ITEM_LIST_FIELDS` items whose `source_fact_ids` is empty or fully hallucinated; keeps an item with a partially-valid `source_fact_ids`, trimmed to only the valid ids; never applies this check to `reason_for_visit` or `diagnosis`.
     - `_log_thin_fields` logs a warning (never mutates or drops) for any `_RICHNESS_CHECKS` field or `diagnosis.details[].description` that fails `_is_informative_quote`; the sentinel `"Not stated in your note."` never triggers a warning.
     - `_verify_assembly` returns the same model unmodified (no spurious `model_copy`) when nothing needs correcting.
     - Permanent tests land in Task 7 (schema-boundary tests) and Task 8 (assembly-level tests).

### Task 5 — Rewrite `backend/tests/care_plan/test_pipeline_structure.py`

   - Files: `backend/tests/care_plan/test_pipeline_structure.py`
   - Dependency: land after Task 1 and Task 2 (needs the new prompt file to exist and the three old ones to be gone).
   - Changes (PRD §7.1): In `test_pipeline_is_flattened_to_a_single_non_versioned_module`, replace the three `assert (prompts_dir / "...").is_file()` lines with:
     ```python
     prompts_dir = BACKEND_DIR / "care_plan" / "prompts"
     assert not (prompts_dir / "simplify_language.txt").exists()
     assert not (prompts_dir / "clarify_and_action.txt").exists()
     assert not (prompts_dir / "structure_note.txt").exists()
     assert (prompts_dir / "assemble_and_render.txt").is_file()
     ```
     Everything else in the file (`test_old_simplify_folder_is_gone`, the `no v1/v1_1/v1_2 packages, no ABC, no SimplifyPipeline` assertions in the same test) is unaffected — leave unchanged.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_structure.py -q` (from `backend/`) passes in full.

### Task 6 — `backend/tests/care_plan/test_pipeline_prompts.py`: delete simplify/clarify/structure tests, add assemble tests

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 1, Task 2, Task 3.
   - Changes (PRD §7.2): This file, at the time this task runs, already contains 03's `_GROUND_PROMPT` tests (`test_ground_prompt_is_non_empty_string`, `test_ground_prompt_accepts_all_keys`, `test_ground_prompt_raises_on_missing_key`, `test_ground_prompt_contains_contrast_dye_boundary_rule`, `test_ground_prompt_lists_all_eight_categories`) alongside the original simplify/clarify/structure block — **leave every `_GROUND_PROMPT` test untouched**, this PRD does not own them. Delete every test referencing `_SIMPLIFY_PROMPT`, `_CLARIFY_PROMPT`, `_STRUCTURE_PROMPT`, or `_STRUCTURING_SCHEMA` — that is the entire original file content as it stood before 03 landed: `test_simplify_prompt_is_non_empty_string`, `test_clarify_prompt_is_non_empty_string`, `test_structure_prompt_is_non_empty_string`, `test_simplify_prompt_accepts_all_keys`, `test_simplify_prompt_raises_on_missing_key`, `test_clarify_prompt_accepts_all_keys`, `test_clarify_prompt_raises_on_missing_key`, `test_structure_prompt_accepts_all_keys`, `test_structure_prompt_raises_on_missing_key`, `test_clarify_prompt_with_empty_abbreviation_section_consumes_placeholder`, `test_clarify_prompt_with_abbreviation_section_present`, `test_simplify_prompt_parity_with_inline_fstring`, `test_clarify_prompt_parity_no_abbreviations`, `test_clarify_prompt_parity_with_abbreviations`, `test_structure_prompt_parity_with_inline_fstring`. Also update the top import line to drop `_CLARIFY_PROMPT, _SIMPLIFY_PROMPT, _STRUCTURE_PROMPT, _STRUCTURING_SCHEMA` and add `_ASSEMBLE_PROMPT`.

     Add, mirroring 03's `ground.txt` pattern (PRD §7.2):
     - `test_assemble_prompt_is_non_empty_string` — `isinstance(_ASSEMBLE_PROMPT, str) and len(_ASSEMBLE_PROMPT) > 0`.
     - `test_assemble_prompt_accepts_all_keys` — `.format(schema="{}", facts_block="[1] medications: x", sub_block="s", medical_block="m", abbrev_block="a")`; assert all five substitutions appear in the result.
     - `test_assemble_prompt_raises_on_missing_key` — omit `facts_block`; assert `KeyError`.
     - `test_assemble_prompt_contains_not_stated_sentinel` — assert the literal substring `"Not stated in your note."` appears in `_ASSEMBLE_PROMPT`.
     - `test_assemble_prompt_contains_merge_example` — assert `"left and right heart arteries"` appears in `_ASSEMBLE_PROMPT`.
     - `test_assemble_prompt_contains_pii_rule_for_clinicians` — assert `"Doctor Alok Singh"` and `"your doctor"` both appear in `_ASSEMBLE_PROMPT`.
     - `test_assemble_prompt_questions_rule_has_no_minimum` — assert `"no minimum"` appears in `_ASSEMBLE_PROMPT` and that `"exactly three"` / `"exactly 3"` do **not**.
     - `test_assemble_prompt_lists_all_eight_mapping_rows` — assert each of `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs` appears in the MAPPING section of `_ASSEMBLE_PROMPT`.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full, including the 5 preserved `_GROUND_PROMPT` tests and the 7 new `_ASSEMBLE_PROMPT` tests; `grep -n "_SIMPLIFY_PROMPT\|_CLARIFY_PROMPT\|_STRUCTURE_PROMPT\|_STRUCTURING_SCHEMA" backend/tests/care_plan/test_pipeline_prompts.py` returns no hits.

### Task 7 — `backend/tests/care_plan/test_pipeline_schema.py`: delete structure_appointment_note tests, add assemble tests

   - Files: `backend/tests/care_plan/test_pipeline_schema.py`
   - Dependency: land after Task 3 and Task 4. This file, at the time this task runs, already contains 03's grounding-schema tests (`test_grounding_schema_is_a_json_array_of_grounded_fact_raw`, `test_ground_assigns_sequential_ids_from_array_position`, `test_ground_rejects_non_list_llm_output`, `test_ground_rejects_extra_key_on_fact`, `test_ground_uses_long_form_token_budget_and_json_temperature`) and the pre-existing `test_llm_schema_excludes_terms_and_raw` / `test_llm_schema_excludes_note` / `test_llm_schema_model_validate_without_terms_and_raw` — **leave all of these untouched**, none is in this PRD's scope.
   - Changes (PRD §7.3): Delete `test_structuring_schema_is_generated_from_structured_llm_model`, `test_structure_appointment_note_validates_and_returns_json_model_dump`, `test_structure_appointment_note_uses_long_form_token_budget`, `test_structure_appointment_note_rejects_extra_llm_key`, `test_run_returns_care_plan_model_without_internal_scores`. Add:
     - `test_assemble_schema_is_generated_from_care_plan_minus_terms_and_note` — `json.loads(pipeline_module._ASSEMBLE_SCHEMA)`; assert `"terms" not in properties`, `"note" not in properties`, `"summary_fact_ids" in properties`, `"medications" in properties`, and `"source_fact_ids"` appears in `properties["medications"]["items"]["properties"]`.
     - `test_assemble_and_render_returns_care_plan_instance` — monkeypatch `_generate_json` to return a minimal valid dict; assert `isinstance(result, CarePlan)`.
     - `test_assemble_and_render_uses_long_form_token_budget_and_json_temperature` — capture kwargs, mirroring `test_ground_uses_long_form_token_budget_and_json_temperature`; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.
     - `test_assemble_and_render_rejects_non_dict_llm_output` — `_generate_json` returns a `list`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
     - `test_assemble_and_render_rejects_extra_llm_key` — output carries an unexpected key (e.g. `"importance"`); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
     - `test_assemble_and_render_raises_on_empty_fact_list` — call with `facts=[]`; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`, and assert `_generate_json` mock is not called.
     - Each of these tests needs a valid minimal `CarePlan` dict/instance to work with — construct the minimal dict as `{"doc_type": "care_plan", "version": Constants.Schema.CARE_PLAN_VERSION, "summary": "You came in for care."}` (matches the pattern already used by the deleted `test_structure_appointment_note_validates_and_returns_json_model_dump`), and a minimal `Fact` list (e.g. one `Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")`) for tests that call `assemble_and_render` directly.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_schema.py -q` (from `backend/`) passes in full, including the 5 preserved grounding tests, the 3 preserved `_llm_schema` tests, and the 6 new assemble tests; `grep -n "structure_appointment_note\|_STRUCTURING_SCHEMA" backend/tests/care_plan/test_pipeline_schema.py` returns no hits.

### Task 8 — New `backend/tests/care_plan/test_pipeline_assembly.py`

   - Files: `backend/tests/care_plan/test_pipeline_assembly.py` (new file)
   - Dependency: land after Task 3 and Task 4 (needs `_format_facts_for_prompt`, `assemble_and_render`, `_verify_assembly`, `_log_thin_fields`).
   - Changes (PRD §7.4): the load-bearing tests for this sub-project — the four areas the task calls out by name, plus the soundness and content-richness passes. Use the file's established convention: direct construction via `CarePlanPipeline.__new__(CarePlanPipeline)` plus monkeypatched `_generate_json`, building `Fact`/`CarePlan` fixtures directly (import `Fact`, `FactCategory` from `models.ledger`; `CarePlan` and its item models from `models.care_plan.care_plan`). Include every case below:

     **Category→field mapping**:
     - `test_format_facts_for_prompt_groups_by_category_in_fixed_order` — facts fed in shuffled category order; assert output lines appear in `_FACT_CATEGORY_ORDER`'s order, not input order.
     - `test_format_facts_for_prompt_includes_fact_id_and_category` — assert each line matches `f"[{id}] {category}: {text}"`.
     - `test_assemble_prompt_construction_includes_fact_for_each_category` — parametrized over all eight categories: monkeypatch `_generate_json` to capture the prompt string; assert the fact's id and text appear in `facts_block` for each category in turn.

     **"Not stated" rendering**:
     - `test_assemble_and_render_accepts_not_stated_why` — canned LLM response with `medications[0].why == "Not stated in your note."`; assert it round-trips unchanged through `assemble_and_render` (also give the item a valid `source_fact_ids` so it survives the soundness check).
     - `test_assemble_prompt_not_stated_rule_names_all_four_why_fields` — assert `"medications"`, `"tests"`, `"procedures"`, `"other"` all appear in `_ASSEMBLE_PROMPT`'s NOT STATED section.

     **Merge rule preserving variants**:
     - `test_assemble_and_render_preserves_merged_diagnosis_variants` — canned LLM response with `diagnosis.details[0].description` containing `"left and right heart arteries"`; assert the returned `CarePlan.diagnosis.details[0].description` contains both `"left"` and `"right"` substrings (proves the pipeline layer doesn't post-process or strip a correctly-merged field).

     **Questions cap** (`_verify_assembly` level):
     - `test_verify_assembly_truncates_questions_over_three` — a `CarePlan` with 5 questions; assert `_verify_assembly` returns exactly 3, and that they are the *first* 3 (order-preserving truncation).
     - `test_verify_assembly_leaves_questions_under_three_unchanged` — 0, 1, and 2-question cases; assert unchanged.
     - `test_verify_assembly_drops_summary_fact_ids_not_in_ledger` — `CarePlan.summary_fact_ids = [1, 2, 999]`, ledger has facts with ids `1, 2`; assert result is `[1, 2]`.
     - `test_verify_assembly_returns_same_object_when_no_correction_needed` — no truncation, no bad ids; assert the function still returns a valid, unmodified-in-content `CarePlan` (guards against the `model_copy` branch firing when `updates` is empty).

     **Soundness: `source_fact_ids`** (the load-bearing group for the citation-existence check — the sole place this property is enforced in the whole pipeline, per PRD §4.4):
     - `test_verify_assembly_drops_item_with_empty_source_fact_ids` — a `medications[0]` with `source_fact_ids=[]`; assert it is absent from the result.
     - `test_verify_assembly_drops_item_with_all_hallucinated_source_fact_ids` — `source_fact_ids=[999]`, ledger has facts `1, 2`; assert the item is dropped, not kept with an empty list.
     - `test_verify_assembly_filters_partial_hallucination_without_dropping_item` — `source_fact_ids=[1, 999]`, ledger has fact `1`; assert the item survives with `source_fact_ids == [1]`.
     - `test_verify_assembly_keeps_fully_valid_source_fact_ids_unchanged` — no-op path, mirrors `test_verify_assembly_returns_same_object_when_no_correction_needed`.
     - `test_verify_assembly_enforces_source_fact_ids_on_every_item_type` — parametrized over `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`; proves the check is wired for all six.
     - `test_verify_assembly_leaves_reason_for_visit_and_diagnosis_untouched` — regression guard that the check is not applied to the two item families with no `source_fact_ids` field.

     **Content-richness floor**:
     - `test_verify_assembly_logs_warning_for_thin_why_field` — `medications[0].why == "for BP"` (no digit, no 7+ char word, under 12 chars); assert a warning is logged (`caplog`) and the field's value is unchanged in the returned `CarePlan`.
     - `test_verify_assembly_does_not_flag_not_stated_sentinel_as_thin` — `medications[0].why == "Not stated in your note."`; assert no warning is logged.
     - `test_verify_assembly_does_not_flag_informative_why_field` — `medications[0].why == "for high blood pressure"` (contains a word ≥ 7 chars, "pressure"); assert no warning.
     - `test_verify_assembly_content_richness_check_never_mutates_or_drops` — a `CarePlan` with multiple thin fields across several item types; assert the returned `CarePlan` is otherwise identical to the input (only the `questions`/`summary_fact_ids`/`source_fact_ids` guards may change it, never this one).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_assembly.py -q` (from `backend/`) passes; every case listed above is present as its own test function (the parametrized ones may use `pytest.mark.parametrize` to satisfy "one case per category/item-type" without literal duplication).

### Task 9 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-8 (and after PRD 01's and 03's tasks have landed in this repo, since `assemble_and_render`'s imports and reused helpers depend on both).
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors attributable to this PRD's changes. Any remaining failures must trace only to PRD 01/02/03 (or later sub-projects') scope, or to the accepted `AttributeError`-on-real-invocation gap this PRD's §3/§9 documents (which, per Task 2's acceptance criteria, no test in this repo actually triggers) — list exactly which test functions and why if any remain.
     - `python -c "from care_plan.pipeline import CarePlanPipeline, _ASSEMBLE_PROMPT, _ASSEMBLE_SCHEMA; assert hasattr(CarePlanPipeline, 'assemble_and_render'); assert not hasattr(CarePlanPipeline, 'simplify_language_with_term_plan'); assert not hasattr(CarePlanPipeline, 'clarify_and_action'); assert not hasattr(CarePlanPipeline, 'structure_appointment_note')"` (from `backend/`) succeeds — a single smoke check proving the swap landed cleanly.
     - `grep -rn "simplify_language_with_term_plan\|clarify_and_action\|structure_appointment_note" backend --include=*.py` returns zero hits anywhere in the repo (confirms no stray reference survives outside `pipeline.py`/its tests, which is what Task 2 already checked file-locally).
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched.

---

## Handed off to other sub-projects (specified here, not implemented here — do not action as part of this task list)

Per PRD §3 Non-Goals and its header cross-references, the following are **out of scope for this PRD's tasks** even though this PRD's own text specifies exactly what they must do:

- **To 06 (pipeline-orchestration)**: wiring `CarePlanPipeline.ground()` (03) then `assemble_and_render()` (this PRD) into `iter_steps`, assigning `assemble_and_render` a `Constants.Pipeline.PIPELINE_STEPS` entry and progress-event step number, implementing the fatal-step wrapping this PRD specifies (§4.5) but does not itself implement, renumbering the module docstring's `Steps:` list, and resolving the transient `AttributeError` gap this PRD's Task 2 knowingly introduces (PRD §3, §9).
- **To 06/07**: how `CarePlan.terms` gets populated now that there is no more "simplified/clarified" whole-document prose string to re-detect terms against. This PRD's `assemble_and_render` always returns `terms == {}`; 07 defines `render_care_plan_text(care_plan: CarePlan) -> str` and 06 wires `care_plan.model_copy(update={"terms": glossary})` after calling `assemble_and_render` (PRD §9, confirmed already resolved by reading both 06 and 07's PRDs).
- **To 06**: stripping `summary_fact_ids`/`source_fact_ids` before persistence via a `_strip_internal_provenance` helper in `routes/worker.py` (already flagged as 06's job by PRD 01's own hand-off section; this PRD is the one that actually starts populating these fields, making that stripping now load-bearing rather than a no-op).
- **To 05 (review-and-correct)**: does not re-implement the `source_fact_ids` citation-existence check this PRD's `_verify_assembly` performs (PRD §4.4's ownership note) — 05 relies on the invariant already holding by the time it sees a `CarePlan`.
- Deletion of `structure_note.txt`'s forced-inference rules is this PRD's own job (Task 2) — nothing here is deferred to another sub-project on that point; recorded only for completeness against PRD §4.6's provenance table, which is documentation, not a task.

## Summary of what requires you (not a dev agent)

Per PRD §8, this item is a session-local, judgement-based check against real infrastructure and cannot be automated by a dev agent:

1. **Prompt smoke test against real notes.** No automated test in this sub-project (or anywhere in this repo) checks clinical fidelity. Once 06 wires `assemble_and_render()` into the live pipeline, run it via ngrok + pm2 (`SERVICE_MODE=combined`) against 2-3 real or realistic de-identified notes, specifically checking: (a) a clinician or facility name in the source note renders as "your doctor" / "the hospital" in every field, not just `summary`; (b) a medication with no stated reason in the note renders `why` as exactly `"Not stated in your note."`, not silently blank and not a fabricated reason; (c) a note with two findings at different anatomical sites merges to one item naming both sites, not two items or one item naming only one site; (d) a note that answers every plausible question produces zero `questions`, not three padded ones; (e) a realistic multi-fact ledger does not hit `LLM_MAX_TOKENS` at the 65,536-token output budget; (f) spot-check a sample of `source_fact_ids` against the facts they cite, confirming each id genuinely supports its item's content and not merely that the id exists in the ledger (existence is mechanically checked by Task 4's `_verify_assembly`; relevance is not, and can't be without a model judgment call — 05's review step is the LLM-side fidelity check that complements this).

No new environment variables, credentials, or console configuration are needed for this PRD — it is prompt + pure Python only (PRD §8).

No PRD §9 items are `[OPEN]` — the gate was clear; all 9 tasks above derive from `[RESOLVED]` decisions only.
