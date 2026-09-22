# Tasks: Review and Correct

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — `backend/models/ledger.py`'s `Fact`; `backend/models/care_plan/care_plan.py`'s settled `CarePlan` shape, including `source_fact_ids` on all six item models; 03 (grounding) — the verified `list[Fact]` `ground()` produces; 04 (assemble-and-render) — `CarePlanPipeline.assemble_and_render(...) -> CarePlan`, `assemble_and_render.txt`'s LANGUAGE RULES/PII text (retrofitted here per §4.4), and the citation-existence check that guarantees every surviving item's `source_fact_ids` is sound before this PRD's calls ever run. None of 01's, 03's, or 04's code exists in this repo yet; their tasks are tracked in `prds/01-schema-and-config/TASKS.md`, `prds/03-grounding/TASKS.md`, `prds/04-assemble-and-render/TASKS.md` and are **not** duplicated here. Depended on by: 06 (pipeline-orchestration, wires `review()`/`correct()` into `iter_steps`), 08 (frontend — `summary` may now be `""`).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/care_plan/test_pipeline_review.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Prerequisite check**: before starting Task 2, confirm `python -c "from care_plan.pipeline import CarePlanPipeline, _ASSEMBLE_SCHEMA, _ASSEMBLE_PROMPT; from models.ledger import Fact, FactCategory, Unit; from models.care_plan.care_plan import CarePlan; assert hasattr(CarePlanPipeline, 'assemble_and_render')"` (from `backend/`) succeeds — if it doesn't, PRD 01's Task 4, PRD 03's Tasks 1-5, and/or PRD 04's Tasks 1-4 haven't landed yet and must land first. Task 1 (the new `models/review.py` module) does not require this — it only imports `.base.JsonModel`.

---

### Task 1 — New module `backend/models/review.py`: `Correction`, `CoverageEntry`, `ReviewResult`

   - Files: `backend/models/review.py` (new file)
   - Changes (PRD §4.1): Create the file with exactly the contract specified in PRD §4.1 — module docstring, `CorrectionOp = Literal["correct", "not_stated", "remove"]`, and the three `JsonModel` subclasses:
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
     Placement mirrors 01's `ledger.py` reasoning (§4.1): a small, flat, pipeline-internal module, not nested under `care_plan/`, never persisted, never serialized to Firestore, never reaches an API response. Do not modify `backend/models/ledger.py` or `backend/models/care_plan/care_plan.py` — both are 01's settled territory, taken as given here.
   - Acceptance criteria:
     - `python -c "from models.review import Correction, CoverageEntry, ReviewResult, CorrectionOp"` (from `backend/`) succeeds.
     - `Correction(op="correct", value=None, path="x")` validates at the model level (PRD §7.1: the "value required for correct" rule is enforced by `_sanitize_review_result`, Task 5, not Pydantic — do not add a Pydantic validator for it here).
     - `ReviewResult(verdict="pass")` validates with `corrections == []` and `coverage == []` (both default to empty lists).
     - Constructing any of the three with an unknown key raises `ValidationError` (`extra="forbid"`, inherited from `JsonModel`).
     - Permanent tests land in Task 8 below.

### Task 2 — New prompt file `backend/care_plan/prompts/review.txt`

   - Files: `backend/care_plan/prompts/review.txt` (new file)
   - Changes (PRD §4.3): Create the file with exactly the text given in PRD §4.3's full text block — the two-job instruction (JOB 1 FIDELITY's three-op vocabulary description, the SUMMARY sub-rule requiring `{"op": "remove", "path": "summary"}` on drift, the QUESTIONS sub-rule requiring `remove` on a presupposing entry; JOB 2 COVERAGE's enumerate-every-fact instruction), and the `{schema}`/`{facts_block}`/`{care_plan_block}` placeholders at the bottom. Copy the block verbatim — do not paraphrase or reformat it; PRD §7.2's regression checks assert on exact substrings and the exact three-op vocabulary.
   - Dependency: none (a plain text file; does not require 01/03/04's code to exist).
   - Acceptance criteria:
     - The file exists at `backend/care_plan/prompts/review.txt`, is non-empty, and contains the literal placeholders `{schema}`, `{facts_block}`, `{care_plan_block}` exactly once each.
     - `grep -c '"correct"' backend/care_plan/prompts/review.txt`, `grep -c '"not_stated"' backend/care_plan/prompts/review.txt`, and `grep -c '"remove"' backend/care_plan/prompts/review.txt` each return at least 1.
     - `grep -c "medications\[N\].why" backend/care_plan/prompts/review.txt` (or equivalent literal occurrence of all four `why` paths — `medications[N].why`, `tests[N].why`, `procedures[N].why`, `other[N].why`) confirms all four appear.
     - `grep -c "summary_fact_ids" backend/care_plan/prompts/review.txt` returns at least 1 (the SUMMARY sub-rule).
     - Covered permanently by Task 9's `test_pipeline_prompts.py` additions.

### Task 3 — New prompt files `backend/care_plan/prompts/_style_rules.txt` (extracted) and `backend/care_plan/prompts/correct.txt`; retrofit `assemble_and_render.txt`

   - Files: `backend/care_plan/prompts/_style_rules.txt` (new file), `backend/care_plan/prompts/correct.txt` (new file), `backend/care_plan/prompts/assemble_and_render.txt` (edit, owned by 04 but retrofitted here per PRD §4.4)
   - Dependency: land after PRD 04's Task 1 (`assemble_and_render.txt` must already exist to extract from).
   - Changes (PRD §4.4 — "extract, don't duplicate"):
     - Create `backend/care_plan/prompts/_style_rules.txt` containing the LANGUAGE RULES and PII paragraphs moved **verbatim** out of `assemble_and_render.txt` (04 §4.1's text — the lines starting `PII --` through the end of `LANGUAGE RULES --`'s bullet list, excluding the `{sub_block}`/`{medical_block}`/`{abbrev_block}` substitution lines, which stay call-specific and remain in `assemble_and_render.txt`).
     - Edit `backend/care_plan/prompts/assemble_and_render.txt`: replace that same LANGUAGE RULES/PII section (now moved out) with one placeholder, `{style_rules}`. This is a small, mechanical, additive change to a file 04 already owns the content of — do not alter any other section of `assemble_and_render.txt` (the four-step instructions, the MAPPING table, the NOT STATED/MERGE/LOW PRIORITY/QUESTIONS sections all stay as 04 wrote them).
     - Create `backend/care_plan/prompts/correct.txt` with exactly the text given in PRD §4.4's full text block for `correct.txt` — the "apply exactly these corrections" instruction, the per-op application rules (`correct`/`not_stated`/`remove`, including the `summary`-clears-to-`""` special case), the PII SWEEP paragraph, and the `{corrections_block}`/`{style_rules}`/`{care_plan_block}`/`{schema}` placeholders. Copy verbatim.
   - Acceptance criteria:
     - `backend/care_plan/prompts/_style_rules.txt` exists, is non-empty, and contains the moved LANGUAGE RULES/PII text (confirm by diffing against what `assemble_and_render.txt` contained before this task, or by grepping for a distinctive phrase from 04's PII paragraph, e.g. `"your doctor"`).
     - `backend/care_plan/prompts/assemble_and_render.txt` no longer contains the LANGUAGE RULES/PII text inline; it contains the literal placeholder `{style_rules}` exactly once; it still contains `{schema}`, `{facts_block}`, `{sub_block}`, `{medical_block}`, `{abbrev_block}` exactly once each (unaffected).
     - `backend/care_plan/prompts/correct.txt` exists, is non-empty, and contains the literal placeholders `{corrections_block}`, `{style_rules}`, `{care_plan_block}`, `{schema}` exactly once each; `grep -c "Not stated in your note." backend/care_plan/prompts/correct.txt` returns at least 1; `grep -c "PII SWEEP" backend/care_plan/prompts/correct.txt` returns at least 1.
     - Covered permanently by Task 9's `test_pipeline_prompts.py` additions.

### Task 4 — `backend/care_plan/pipeline.py`: imports, prompt/schema loads, `_PATH_SEGMENT_RE`, `_resolve_path`, `_STYLE_RULES`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Tasks 1, 2, 3, and after the prerequisite check above (01/03/04's code must already exist in this module).
   - Changes (PRD §4.1, §4.2, §4.4):
     - Add to the existing import block:
       ```python
       import re
       from models.review import Correction, CoverageEntry, ReviewResult
       ```
       (`re` may already be imported for 03's helpers — if so, do not add a duplicate import line.)
     - Add the new prompt loads alongside the existing `_PROMPTS_DIR / "*.txt"` reads:
       ```python
       _REVIEW_PROMPT = (_PROMPTS_DIR / "review.txt").read_text(encoding="utf-8")
       _CORRECT_PROMPT = (_PROMPTS_DIR / "correct.txt").read_text(encoding="utf-8")
       _STYLE_RULES = (_PROMPTS_DIR / "_style_rules.txt").read_text(encoding="utf-8")
       ```
     - Update the existing `assemble_and_render` prompt-construction call (04's `.format(...)` call) to add the one new kwarg the retrofit requires: `style_rules=_STYLE_RULES`. This is the only edit to `assemble_and_render`'s body this PRD makes — everything else about that method (04's) stays untouched.
     - Add the new schema constant, built from `ReviewResult`:
       ```python
       _REVIEW_SCHEMA = json.dumps(_llm_schema(ReviewResult, exclude=set()), indent=2)
       ```
       (`_llm_schema` is already defined earlier in this module, from 04's/the original pipeline's setup — reuse it, do not redefine it.)
     - Add the JSON path resolution helper, exactly as specified in PRD §4.2, with its full docstring:
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
       (`Any` is already imported from `typing` at the top of this module — no new import needed for it.)
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _REVIEW_PROMPT, _CORRECT_PROMPT, _STYLE_RULES, _REVIEW_SCHEMA, _resolve_path"` (from `backend/`) succeeds.
     - `json.loads(pipeline_module._REVIEW_SCHEMA)` has `"verdict"`, `"corrections"`, `"coverage"` in `properties`.
     - `_resolve_path({"medications": [{"dosage": "10 mg"}]}, "medications[0].dosage") == (True, "10 mg")`.
     - `_resolve_path({"medications": []}, "medications[0].dosage") == (False, None)` (out-of-range index, no exception).
     - `_resolve_path({"medications": []}, "nonexistent_field") == (False, None)` (unknown field, no exception).
     - `assemble_and_render`'s prompt construction now passes `style_rules=_STYLE_RULES` — confirm via `grep -n "style_rules=_STYLE_RULES" backend/care_plan/pipeline.py` returning exactly one hit, inside the `assemble_and_render` method.
     - Every existing test in `backend/tests/care_plan/` still passes unchanged (`python -m pytest tests/care_plan/ -q` from `backend/`) except any 04 test that asserted `assemble_and_render.txt`'s `.format()` call takes exactly N kwargs by name and would need `style_rules` added — if such a test exists from 04's own suite, it is 04's file to have anticipated; do not edit 04's tests here beyond what this task's own additions require (Task 9 handles `test_pipeline_prompts.py`).
     - Permanent tests land in Task 10 (`test_pipeline_schema.py` additions) and Task 12 (`test_review.py`... — no, `_resolve_path` tests land in Task 11, `test_pipeline_review.py`).

### Task 5 — `CarePlanPipeline.review()` and `_sanitize_review_result()`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 4.
   - Changes (PRD §4.5): Add the method and its deterministic post-validation, exactly as specified, with full docstrings:
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
     Also add the small helper `_targets_removed_item(path: str, removed_items: set[str]) -> bool`, checking whether `path`'s leading `array[N]` segment matches one of the `removed_items` path strings (a string-prefix comparison: extract `path`'s `<array>[<N>]` prefix via `_PATH_SEGMENT_RE` or a simple split on `.`, and check whether that exact prefix is a member of `removed_items`). This function is exercised directly in Task 11's tests (PRD §4.5).

     **Whether to run `correct()` at all is driven by `len(result.corrections) > 0`, not `result.verdict`** — do not branch on `verdict` anywhere in `review()` or its caller; `verdict` is carried through for logging/observability only.

     `format_abbreviations_for_prompt`/`_format_facts_for_prompt` are already available in this module (03/04's helpers) — no new import needed.
   - Failure classification and budgets (PRD §4.8): `review()` is **non-fatal** — it raises `SimplifyError` on non-dict LLM output (`LLM_INVALID_JSON`) or a `ReviewResult` failing Pydantic validation (`PIPELINE_VALIDATION_FAILED`), and otherwise lets `LLMClient` exceptions propagate unchanged; wiring the non-fatal fallback (skip `correct()` entirely, ship `assemble_and_render()`'s output as-is) into `iter_steps` is 06's job — this task only implements the method itself. Budgets: `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536), `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2).
   - Acceptance criteria:
     - `review()` calls `self._generate_json` with `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature=Constants.Llm.TEMPERATURE_JSON`.
     - A non-dict LLM response raises `SimplifyError(ErrorCode.LLM_INVALID_JSON)`.
     - A response failing `ReviewResult.model_validate` (e.g. an extra key, or `verdict` outside `"pass"`/`"needs_correction"`) raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)`.
     - `_sanitize_review_result` drops a correction with an unresolvable path; drops `not_stated` outside the four `why` fields (and keeps it on each of the four); drops `correct` with no `value`; `remove` wins over a `correct`/`not_stated` targeting the same item; fills a coverage entry missing from the ledger as `present=False`; drops a coverage entry citing an unknown `fact_id`.
     - Running `correct()` is driven by `len(result.corrections) > 0` — asserted directly in a test that sets `verdict="pass"` with a non-empty `corrections` list (Task 11).
     - Permanent tests land in Task 10 (schema-boundary) and Task 11 (`test_pipeline_review.py`).

### Task 6 — `CarePlanPipeline.correct()`, `_verify_correction_diff()`, `_looks_like_pii_substitution()`, `_diff_item()`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 5 (uses `Correction` and shares `_resolve_path`'s path-parsing conventions).
   - Changes (PRD §4.6): Add the method and its diff-check machinery, exactly as specified, with full docstrings:
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
     Add `_format_corrections_for_prompt(corrections: list[Correction]) -> str`, a small formatting helper rendering each correction as one line, e.g. `f'{{"op": "{c.op}", "path": "{c.path}"' + (f', "value": "{c.value}"' if c.value is not None else '') + '}'` (a simple JSON-line-per-correction rendering — implement with `json.dumps({"op": c.op, "path": c.path, **({"value": c.value} if c.value is not None else {})})` per line for well-formed escaping, joined with `"\n"`). This has no PRD-cited exact text (only the surrounding `correct.txt` prompt text is quoted verbatim in the PRD) — any correct, readable one-line-per-correction JSON rendering satisfies §4.6.

     Add the diff check, exactly as specified in PRD §4.6, with full docstrings and the module-level constants:
     ```python
     import difflib

     _PII_ELIGIBLE_FIELDS = {
         "summary", "why", "description", "what_it_means_for_you", "instructions",
         "what_to_expect", "what_it_might_mean", "related_to",
         "changed_since_last_visit", "side_effects_to_watch", "preparation",
         "steps", "questions", "low_priority",
     }
     _MAX_PII_TOKEN_DELTA = 4
     _LIST_FIELDS = {"medications", "tests", "procedures", "other", "follow_up", "warning_signs",
                      "reason_for_visit", "questions", "low_priority"}


     def _looks_like_pii_substitution(old: str, new: str) -> bool:
         """True if old->new plausibly represents ONLY a name/facility swap.
         Word-level SequenceMatcher opcodes; count non-'equal' tokens on either
         side. A targeted "Doctor Alok Singh" -> "your doctor" swap stays under
         the threshold; a resummarized sentence does not."""
         old_w, new_w = old.split(), new.split()
         ops = difflib.SequenceMatcher(a=old_w, b=new_w).get_opcodes()
         changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops if tag != "equal")
         return changed <= _MAX_PII_TOKEN_DELTA


     def _split_array_path(path: str) -> tuple[str, int]:
         """"warning_signs[3]" -> ("warning_signs", 3). Used only by the diff
         check to convert a `remove` correction's path into an (array, index)
         pair (PRD 05 §4.6)."""
         m = _PATH_SEGMENT_RE.fullmatch(path)
         return m.group(1), int(m.group(3))


     def _verify_correction_diff(before: CarePlan, after: CarePlan, corrections: list[Correction]) -> None:
         before_d, after_d = before.model_dump(mode="json"), after.model_dump(mode="json")
         named = {c.path for c in corrections}
         removed_by_array: dict[str, set[int]] = {}   # e.g. "warning_signs" -> {1, 3}
         for c in corrections:
             if c.op == "remove" and c.path != "summary":
                 arr, idx = _split_array_path(c.path)
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
     Add `_check_scalar_or_nested(before_v, after_v, field: str, named: set[str]) -> None` for the non-list top-level `CarePlan` fields (`doc_type`, `version`, `summary`, `diagnosis`, `terms`, `note`): for a scalar field, compare directly and apply the same named/PII-eligible tolerance as `_diff_item`; for `summary` specifically, this is where the `remove`-clears-to-`""` and small-PII-swap cases are actually exercised (§4.2/§4.6: `summary`'s diff check only ever needs to permit `remove` or a PII-eligible small swap, never an arbitrary `correct`-style replacement, since `correct` may never target `summary` — §4.2). For `diagnosis` (a nested object, not a list), recurse one level into its own fields the same way `_diff_item` recurses into a dict item's keys, using `diagnosis.<key>` as the path prefix. Any violation raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)` with a detail naming the field — mirror `_diff_item`'s message format exactly (`f"corrector changed unnamed, non-PII field: {full_path}"`).
   - Failure classification and budgets (PRD §4.8): `correct()` is **non-fatal at the caller level** but `correct()` itself always raises on failure — it never falls back internally; the caller (06's `iter_steps`) is the one that catches `SimplifyError` from `correct()` (including a diff-check rejection) and substitutes the pre-correction `care_plan` unmodified. This task implements `correct()`'s own all-raise behavior only; wiring the caller-side fallback is 06's job. Budgets: `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` (65,536), `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2).
   - Acceptance criteria:
     - `correct(care_plan, corrections=[], ...)` returns `care_plan` unchanged without calling `self._generate_json` (§4.6's short-circuit).
     - `correct()` calls `self._generate_json` with `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature=Constants.Llm.TEMPERATURE_JSON` when `corrections` is non-empty.
     - A non-dict LLM response raises `SimplifyError(ErrorCode.LLM_INVALID_JSON)`.
     - A response failing `CarePlan.model_validate` raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)`.
     - `_verify_correction_diff` passes when only the named field changed; rejects a change to an unnamed, non-PII-eligible field; passes a small (≤4-token) PII-shaped swap on a `_PII_ELIGIBLE_FIELDS` field; rejects a large rewrite on that same field despite being PII-eligible; rejects a small-delta PII-shaped swap on a non-eligible field (e.g. `dosage`); correctly accounts for array-length shrinkage from `remove` ops (matches survivors against original indices); rejects a wrong surviving count; rejects a reordered-but-otherwise-identical array (no `remove` ops present); rejects any change to `source_fact_ids` (not a named target, not PII-eligible).
     - `correct()` itself raises on a diff-check violation rather than silently falling back — the fallback-to-pre-correction-plan behavior belongs to the caller (§4.8), not to `correct()`.
     - Permanent tests land in Task 12 (`test_pipeline_correct.py`), the load-bearing test file for this sub-project.

### Task 7 — Delete `close_coverage()` and its heuristic constants/helpers, and its test file

   - Files: `backend/care_plan/pipeline.py`, `backend/tests/care_plan/test_pipeline_coverage_close.py` (delete)
   - Dependency: this task is independent of Tasks 1-6 and may land any time after the prerequisite check, but is sequenced here to land alongside the other pipeline-module edits.
   - Changes (PRD §4.7, §9 `[RESOLVED: close_coverage() ... deleted outright]`): Delete `close_coverage()` in its entirety from `CarePlanPipeline`, along with its supporting module-level helpers and constants — `_COVERAGE_TOKEN_RE`, `_COVERAGE_OVERLAP_THRESHOLD`, `_flatten_care_plan_text`, `_fact_anchor_tokens` — and the `"From your note: <fact text>"` safety-net line-appending logic that lived inside `close_coverage()`. **Note**: as of this writing (before 01/03/04 land), none of this code exists yet in `backend/care_plan/pipeline.py` — it belongs to the prior (pre-decomposition) design this PRD supersedes. If, by the time this task is executed, 01/03/04's landed code (or any earlier revision of this branch) has reintroduced or left in place any of these five names, delete them; if none of them exist at all (the expected case, since 03/04's own task lists never reintroduce them), this task's job is only to delete the corresponding test file and confirm the grep below is already clean.
   - Delete `backend/tests/care_plan/test_pipeline_coverage_close.py` in its entirety, if it exists (the token-overlap fixture tests, `_flatten_care_plan_text`/`_fact_anchor_tokens` tests, the `_COVERAGE_OVERLAP_THRESHOLD` boundary case). No new test file replaces it (PRD §7.4) — the citation-existence property it indirectly protected is now covered by 04's own `_verify_assembly` tests (04 §7.4) and by this PRD's own `test_diff_check_rejects_change_to_source_fact_ids` (Task 12 below).
   - Acceptance criteria:
     - `grep -rn "close_coverage\|_COVERAGE_TOKEN_RE\|_COVERAGE_OVERLAP_THRESHOLD\|_flatten_care_plan_text\|_fact_anchor_tokens" backend --include=*.py` returns zero hits anywhere in the repo.
     - `backend/tests/care_plan/test_pipeline_coverage_close.py` does not exist.
     - `python -m pytest tests/care_plan/ -q` (from `backend/`) passes with no reference to the deleted names.

### Task 8 — New `backend/tests/models/test_review.py`

   - Files: `backend/tests/models/test_review.py` (new file)
   - Dependency: land after Task 1.
   - Changes (PRD §7.1): Following the conventions of `backend/tests/models/test_ledger.py` (round-trip + `extra="forbid"` pattern):
     - Round-trip `Correction`, `CoverageEntry`, and `ReviewResult` each through `.to_dict()` then `.from_dict()`; assert equality.
     - `extra="forbid"` regression guard: assert constructing each of the three with an unknown key raises `ValidationError`.
     - `test_correction_value_none_validates_at_model_level`: `Correction(op="correct", path="medications[0].dosage", value=None)` validates successfully (no `ValidationError`) — the "value required for correct" rule is enforced by `_sanitize_review_result` (Task 5's pipeline code), not by Pydantic; this test documents and pins that boundary.
     - `test_review_result_defaults_corrections_and_coverage_to_empty_list`: `ReviewResult(verdict="pass")` has `corrections == []` and `coverage == []`.
     - `test_correction_op_rejects_value_outside_vocabulary`: `Correction(op="rewrite", path="x")` (a fourth, invalid op) raises `ValidationError`.
   - Acceptance criteria: `python -m pytest tests/models/test_review.py -q` (from `backend/`) passes; all listed cases present.

### Task 9 — `backend/tests/care_plan/test_pipeline_prompts.py` additions

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Tasks 2, 3, 4. This file, at the time this task runs, already contains 03's `_GROUND_PROMPT` tests and 04's `_ASSEMBLE_PROMPT` tests — leave both blocks untouched, neither is in this PRD's scope.
   - Changes (PRD §7.2): Add, importing `_REVIEW_PROMPT`, `_CORRECT_PROMPT`, `_STYLE_RULES` from `care_plan.pipeline`:
     - `test_review_prompt_is_non_empty_string` — `isinstance(_REVIEW_PROMPT, str) and len(_REVIEW_PROMPT) > 0`.
     - `test_review_prompt_accepts_all_keys` — `.format(schema="{}", facts_block="[1] medications: x", care_plan_block="{}")`; assert all three substitutions appear.
     - `test_review_prompt_raises_on_missing_key` — omit `care_plan_block`; assert `KeyError`.
     - `test_review_prompt_names_the_three_op_vocabulary` — assert `'"correct"'`, `'"not_stated"'`, `'"remove"'` all appear in `_REVIEW_PROMPT`.
     - `test_review_prompt_scopes_not_stated_to_four_why_fields` — assert each of `"medications[N].why"`, `"tests[N].why"`, `"procedures[N].why"`, `"other[N].why"` (or their equivalent literal occurrence) appears in `_REVIEW_PROMPT`.
     - `test_correct_prompt_is_non_empty_string` — `isinstance(_CORRECT_PROMPT, str) and len(_CORRECT_PROMPT) > 0`.
     - `test_correct_prompt_accepts_all_keys` — `.format(corrections_block="c", style_rules="s", care_plan_block="{}", schema="{}")`; assert all four substitutions appear.
     - `test_correct_prompt_raises_on_missing_key` — omit `corrections_block`; assert `KeyError`.
     - `test_correct_prompt_contains_pii_sweep_instruction` — assert `"PII SWEEP"` appears in `_CORRECT_PROMPT`.
     - `test_correct_prompt_contains_not_stated_sentinel` — assert `"Not stated in your note."` appears in `_CORRECT_PROMPT`.
     - `test_style_rules_is_non_empty_and_shared` — `isinstance(_STYLE_RULES, str) and len(_STYLE_RULES) > 0`; assert `_ASSEMBLE_PROMPT` (imported alongside, from 04) contains the literal placeholder `{style_rules}` and does **not** contain the raw LANGUAGE RULES/PII text that now lives only in `_STYLE_RULES` (pick a distinctive phrase from `_STYLE_RULES` and assert its absence from `_ASSEMBLE_PROMPT`'s own text, confirming the extraction actually moved the text rather than copying it).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full, including the preserved `_GROUND_PROMPT`/`_ASSEMBLE_PROMPT` tests and the 11 new tests above.

### Task 10 — `backend/tests/care_plan/test_pipeline_schema.py` additions

   - Files: `backend/tests/care_plan/test_pipeline_schema.py`
   - Dependency: land after Tasks 4, 5, 6. This file already contains 03's and 04's schema tests — leave them untouched.
   - Changes (PRD §7.1, §7.2): Add, following the file's `CarePlanPipeline.__new__(CarePlanPipeline)` + monkeypatched `_generate_json` convention:
     - `test_review_schema_is_generated_from_review_result` — `json.loads(pipeline_module._REVIEW_SCHEMA)`; assert `"verdict"`, `"corrections"`, `"coverage"` present in `properties`.
     - `test_review_uses_long_form_token_budget_and_json_temperature` — capture kwargs, mirroring `test_assemble_and_render_uses_long_form_token_budget_and_json_temperature`; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.
     - `test_review_rejects_non_dict_llm_output` — `_generate_json` returns a `list`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
     - `test_review_rejects_invalid_verdict_value` — canned response has `verdict: "maybe"`; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
     - `test_correct_uses_long_form_token_budget_and_json_temperature_when_corrections_present` — capture kwargs; assert budget/temperature match.
     - `test_correct_short_circuits_on_empty_corrections` — call `correct(care_plan, corrections=[], ...)`; assert `_generate_json` is never called and the same `care_plan` object (or an equal one) is returned.
     - `test_correct_rejects_non_dict_llm_output` — `_generate_json` returns a `list`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
     - `test_correct_rejects_extra_llm_key` — output carries an unexpected key; assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
     - Each of these tests needs a minimal valid `CarePlan` dict/instance and a minimal `Fact` list — construct them the same way 04's `test_pipeline_schema.py` additions do (a minimal `{"doc_type": "care_plan", "version": Constants.Schema.CARE_PLAN_VERSION, "summary": "..."}` dict, one `Fact(id=1, category="medications", unit_id=1, char_start=0, char_end=1, text="x")`).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_schema.py -q` (from `backend/`) passes in full, including all preserved 03/04 tests and the 8 new tests above.

### Task 11 — New `backend/tests/care_plan/test_pipeline_review.py`

   - Files: `backend/tests/care_plan/test_pipeline_review.py` (new file)
   - Dependency: land after Task 5 (and Task 4 for `_resolve_path`).
   - Changes (PRD §7.2): Create the file with real `Fact`/`CarePlan`/`ReviewResult` fixtures. Include every case below:
     - `_resolve_path`:
       - `test_resolve_path_finds_nested_scalar` — `"medications[1].dosage"` on a two-medication `CarePlan` dict; returns `(True, <value>)`.
       - `test_resolve_path_returns_false_on_out_of_range_index` — never raises.
       - `test_resolve_path_returns_false_on_unknown_field_name` — never raises.
     - `_sanitize_review_result`:
       - `test_sanitize_drops_correction_with_unresolvable_path`.
       - `test_sanitize_drops_not_stated_outside_four_why_fields` — parametrized to also assert it **keeps** `not_stated` on each of the four (`medications[N].why`, `tests[N].why`, `procedures[N].why`, `other[N].why`).
       - `test_sanitize_drops_correct_with_no_value`.
       - `test_sanitize_remove_wins_over_correct_on_same_item` — a `remove` and a `correct` both targeting `medications[0]`/`medications[0].dosage`; assert only the `remove` survives.
       - `test_sanitize_remove_wins_over_not_stated_on_same_item` — same shape, with `not_stated` instead of `correct`.
       - `test_sanitize_fills_missing_coverage_entry_as_not_present` — a 3-fact ledger, `coverage` list omits one `fact_id`; assert the result's `coverage` includes that id with `present=False`.
       - `test_sanitize_drops_coverage_entry_citing_unknown_fact_id`.
     - `review()`:
       - `test_review_runs_correct_from_corrections_length_not_verdict` — canned `ReviewResult` has `verdict="pass"` but a non-empty `corrections` list; assert (at the call-site level this test controls, e.g. by checking the returned `ReviewResult.corrections` is non-empty and documenting/asserting that a caller would compute `len(result.corrections) > 0` as `True` regardless of `verdict`) — do not have `review()` itself branch on `verdict` anywhere; this test's real job is to prove `review()` never drops or reinterprets `corrections` based on `verdict`.
       - `test_review_uses_long_form_token_budget_and_json_temperature` (may already be covered in Task 10 at the schema-boundary level; if so, do not duplicate here — keep the ledger/coverage-level behavior tests in this file and the budget/temperature capture test in `test_pipeline_schema.py`).
       - `test_review_rejects_non_dict_llm_output` (same note as above — keep the schema-boundary version in Task 10; this file may skip it or keep a single shared case, avoid literal duplication).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_review.py -q` (from `backend/`) passes; every case listed above is present as its own test function (parametrized where noted).

### Task 12 — New `backend/tests/care_plan/test_pipeline_correct.py` — the load-bearing test file

   - Files: `backend/tests/care_plan/test_pipeline_correct.py` (new file)
   - Dependency: land after Task 6.
   - Changes (PRD §7.3): the single most load-bearing test group in this sub-project. Use real `CarePlan`/`Correction` fixtures (import `CarePlan` and its item models from `models.care_plan.care_plan`, `Correction` from `models.review`). Include every case below:

     **Correction application on fixtures** (parsing/formatting correctness, not model judgment):
     - `test_correct_applies_correct_op_to_exactly_the_named_field` — one `correct` on `medications[0].dosage`; canned LLM output changes exactly that field; assert the returned `CarePlan` has the new value and every other field unchanged.
     - `test_correct_applies_not_stated_to_exact_sentinel_text` — a `not_stated` on `medications[0].why`; canned output sets it to exactly `"Not stated in your note."`; assert equality.
     - `test_correct_applies_remove_on_array_item` — a `remove` on `warning_signs[1]` (of 2); canned output has 1 item; assert the array is one shorter and the right item is gone.
     - `test_correct_applies_remove_on_summary` — a `remove` on `"summary"`; canned output has `summary == ""`; assert equality.
     - `test_correct_short_circuits_and_returns_input_unchanged_when_corrections_empty` — `corrections=[]`; assert `_generate_json` is never called (mirrors Task 10's schema-level version — keep this one focused on returning the exact same `care_plan` object/content, not on the mock-not-called assertion if that's already covered there; avoid literal duplication of the same assertion in both files).

     **The corrector-diff check:**
     - `test_diff_check_passes_when_only_named_field_changes` — one `correct` on `medications[0].dosage`; output changes exactly that field; no exception.
     - `test_diff_check_rejects_change_to_unnamed_unrelated_field` — corrections name `medications[0].dosage`; output *also* changes `medications[1].frequency`-equivalent field (untouched, not PII-shaped); `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
     - `test_diff_check_passes_small_pii_substitution_on_eligible_field` — `medications[0].why` goes `"Prescribed by Doctor Alok Singh"` → `"Prescribed by your doctor"` (a 4-token delta), no correction naming it; passes under `_looks_like_pii_substitution`.
     - `test_diff_check_rejects_large_rewrite_disguised_as_pii` — same field, a wholly different longer sentence; delta exceeds `_MAX_PII_TOKEN_DELTA`; rejected despite being PII-eligible.
     - `test_diff_check_rejects_pii_substitution_on_non_eligible_field` — a small-delta change to `medications[0].dosage` (not in `_PII_ELIGIBLE_FIELDS`); rejected — dosage/status/severity/urgency must never be "PII-swept".
     - `test_diff_check_accounts_for_removed_array_length` — `remove` on `warning_signs[1]` and `warning_signs[3]` (of 4); output has 2 items; survivors are matched against original indices 0 and 2 and pass if otherwise unchanged.
     - `test_diff_check_rejects_wrong_surviving_count` — same setup, output has 3 items (one expected removal didn't happen); rejected, message names the array.
     - `test_diff_check_rejects_reordered_items` — no `remove` ops; same items, swapped order; rejected (positional diff reads a swap as "every field differs").
     - `test_diff_check_rejects_change_to_source_fact_ids` — corrections name `medications[0].dosage` only; output *also* changes `medications[0].source_fact_ids` (e.g. drops an id); `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED` — the regression guard for PRD §4.7's "no second coverage pass is needed after `correct()`" argument; `source_fact_ids` is neither a named correction target nor in `_PII_ELIGIBLE_FIELDS`.
     - `test_correct_raises_on_diff_violation_rather_than_silently_falling_back` — `correct()` itself raises; assert no fallback value is returned — the fallback-to-pre-correction-plan behavior belongs to the *caller* (§4.8), not to `correct()`.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_correct.py -q` (from `backend/`) passes; every case listed above is present as its own test function.

### Task 13 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-12 (and after PRD 01's, 03's, and 04's tasks have landed in this repo, since this PRD's imports and reused helpers depend on all three).
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors attributable to this PRD's changes. Any remaining failures must trace only to PRD 01/02/03/04 (or later sub-projects') scope, or to 04's own accepted `AttributeError`-on-real-invocation gap (04 §3/§9) — list exactly which test functions and why if any remain.
     - `python -c "from care_plan.pipeline import CarePlanPipeline, _REVIEW_PROMPT, _CORRECT_PROMPT, _STYLE_RULES, _REVIEW_SCHEMA; from models.review import Correction, CoverageEntry, ReviewResult; assert hasattr(CarePlanPipeline, 'review'); assert hasattr(CarePlanPipeline, 'correct')"` (from `backend/`) succeeds — a single smoke import proving every new symbol this PRD introduces is wired together correctly.
     - `grep -rn "self.review(\|self.correct(\|\.review(facts\|\.correct(care_plan" backend/care_plan/pipeline.py` shows only the two method definitions, no call site inside `iter_steps` — confirms this PRD's "no pipeline wiring" boundary (§3 Non-Goals) held through to the end of its own work.
     - `grep -rn "close_coverage\|_COVERAGE_TOKEN_RE\|_COVERAGE_OVERLAP_THRESHOLD\|_flatten_care_plan_text\|_fact_anchor_tokens" backend --include=*.py` returns zero hits (Task 7's deletion held).
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched.

---

## Handed off to other sub-projects (specified here, not implemented here — do not action as part of this task list)

Per PRD §3 Non-Goals and its header cross-references, the following are **out of scope for this PRD's tasks** even though this PRD's own text specifies exactly what they must do:

- **To 06 (pipeline-orchestration)**: wiring `CarePlanPipeline.review()` then `CarePlanPipeline.correct()` into `iter_steps`, assigning both a `Constants.Pipeline.PIPELINE_STEPS` entry and progress-event step numbers, and implementing the two non-fatal fallback contracts this PRD specifies but does not itself wire — `review()` failing skips `correct()` entirely and ships `assemble_and_render()`'s output as-is; `correct()` failing, raising, or its diff check rejecting falls back to the pre-correction `care_plan`. No pipeline call site for `review()`/`correct()` exists anywhere in the codebase after this PRD's own tasks land — confirmed by Task 13's grep.
- **To 06**: `Constants.Pipeline.PIPELINE_STEPS` renumbering and the module docstring's `Steps:` list — untouched by this PRD, exactly as 03/04 left them.
- **To 06**: stripping `summary_fact_ids`/`source_fact_ids` before persistence (`_strip_internal_provenance` in `routes/worker.py`) — already flagged as 06's job by PRD 01's and 04's own hand-off sections; this PRD does not touch persistence at all.
- **To 08 (frontend)**: `summary` may now legitimately come back as `""` (a drifted summary that `correct()` cleared) — 08 should render an empty "What You Need to Know" card the same way it already handles an empty `questions` array (hide the card, don't show an empty shell). No frontend file is touched by this PRD's own tasks.
- Empirically measuring the reviewer's actual catch rate against injected errors (PRD §7.5's protocol) is a manual/scriptable step, not a `pytest` task — see the summary below.

## Summary of what requires you (not a dev agent)

Per PRD §8, these items are session-local, judgment-based checks against real infrastructure or real model behavior, and cannot be automated by a dev agent:

1. **Prompt smoke test against real notes**, once 06 wires `review()`/`correct()` into the live pipeline (ngrok + pm2, `SERVICE_MODE=combined`): (a) confirm a deliberately-broken dose in a test note gets a `correct` op with the right value, not silently ignored; (b) confirm a fabricated warning sign gets `remove`d; (c) confirm the PII sweep catches a clinician name that slipped past 04's own rendering; (d) confirm a realistic ledger + care plan does not hit `LLM_MAX_TOKENS` at 65,536 on either call.
2. **Run the injected-error catch-rate protocol** (PRD §7.5 — take 5-10 real/realistic de-identified notes already run through grounding + assembly, programmatically inject a dropped medication / a plausible wrong-dose mutation / a fabricated follow-up item into each, run the real `review()` call, and score catch rate per category) as a manual script (`backend/tests/care_plan/manual_reviewer_catch_rate.py` or similar), not part of CI — and decide whether the resulting rate is acceptable before treating review as a trustworthy fidelity backstop in production. This is an explicit product judgment call, not a pass/fail this task list can encode.
3. **Tune `_MAX_PII_TOKEN_DELTA` (4)** against real notes once the corrector is exercised end-to-end — a disclosed, reasoned starting point (PRD §9), not empirically derived.

No new environment variables, credentials, or console configuration are needed for this PRD — it is prompt + pure Python only (PRD §8).

No PRD §9 items are `[OPEN]` — the gate was clear; all 13 tasks above derive from `[RESOLVED]` decisions only. One `[DEFERRED]` item (the reviewer's empirical catch rate) is recorded above as a hand-off/manual step, not a task, since the PRD itself defers it as a follow-up, not a gate.
