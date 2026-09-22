# Tasks: Grounding

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — `backend/models/ledger.py`'s `Unit`, `Fact`, `FactCategory`; 02 (unitization-and-provenance) — `list[Unit]` from `services.unitizer.unitize` / `resolve_units_from_job_doc`. Neither 01's nor 02's code exists in this repo yet; their tasks are tracked in `prds/01-schema-and-config/TASKS.md` and `prds/02-unitization-and-provenance/TASKS.md` and are **not** duplicated here. Land 01's Task 4 (`backend/models/ledger.py`) before this PRD's Task 3 below, which imports `Fact`/`FactCategory`/`Unit` from it. Depended on by: 04 (assemble-and-render, consumes `list[Fact]` via `models.ledger.quote_for`), 05 (review-and-correct, same `quote_for` dependency), 06 (pipeline-orchestration, wires `CarePlanPipeline.ground` into `iter_steps`).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/care_plan/test_pipeline_grounding.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Prerequisite check**: as of this writing, `backend/models/ledger.py` does not exist. Before starting Task 3, confirm `python -c "from models.ledger import Fact, FactCategory, Unit"` (from `backend/`) succeeds — if it doesn't, PRD 01's Task 4 hasn't landed yet and must land first.

---

### Task 1 — `backend/utils/text_normalization.py`: add `normalize_with_offsets`, redefine `normalize_text` in terms of it

   - Files: `backend/utils/text_normalization.py`
   - Changes (PRD §4.3a): Add a new function `normalize_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]` implementing the two-pass algorithm specified in full in PRD §4.3a's docstring:
     1. Per-character transliteration — for each raw character at index `i`, run it individually through the same NFKD-decompose / ASCII-encode(`errors="ignore"`) / lowercase transformation `normalize_text` currently applies to the whole string, tagging every emitted character with the raw span `(i, i+1)` of the single input character that produced it (zero emitted characters for a dropped symbol; more than one only for a rare multi-character compatibility decomposition).
     2. Whitespace collapse — mirroring `" ".join(text.split())`: replace each maximal run of whitespace-classified characters with a single `" "` tagged with `(first run member's start, last run member's end)`; drop leading/trailing whitespace runs entirely (no character emitted).
     Reproduce PRD §4.3a's full docstring on the new function (it documents the two-pass algorithm and the "cannot drift apart by construction" claim Task 8's equivalence test checks).
     Then redefine the existing `normalize_text` as a thin wrapper:
     ```python
     def normalize_text(text: str) -> str:
         """Lowercase, strip accents, and collapse whitespace."""
         return normalize_with_offsets(text)[0]
     ```
     removing its current standalone NFKD/encode/lowercase/join body (that logic now lives inside `normalize_with_offsets`). Do not change `contains_normalized_term`, `term_aliases`, `inflected_aliases`, or any pluralization/inflection helper in this file — none of them call the body being moved, only the public `normalize_text` name, which keeps its exact signature and observable behavior.
   - Acceptance criteria:
     - `python -c "from utils.text_normalization import normalize_text, normalize_with_offsets"` (from `backend/`) succeeds.
     - `normalize_text(text)` returns byte-for-byte the same output as before this change for every case already covered by `backend/tests/utils/test_text_normalization.py` — run `python -m pytest tests/utils/test_text_normalization.py -q` (from `backend/`) and confirm zero regressions (PRD §4.3a: "does not alter `normalize_text`'s existing observable behavior").
     - `len(normalize_with_offsets(text)[1]) == len(normalize_with_offsets(text)[0])` for any input (same-length invariant between normalized string and its span list).
     - `utils/term_detection.py`'s existing call to `normalize_text` (line ~15, `contains_normalized_term`/`detect_terms` path) needs no code change — confirmed by the same `test_text_normalization.py` pass above plus `python -m pytest tests/utils/test_term_detection.py -q` (from `backend/`) staying green.
     - Permanent equivalence test added in Task 8 below (`test_normalize_with_offsets_matches_normalize_text`); this task itself needs no new test file, just the zero-regression check above.

### Task 2 — New prompt file `backend/care_plan/prompts/ground.txt`

   - Files: `backend/care_plan/prompts/ground.txt` (new file)
   - Changes (PRD §4.1): Create the file with exactly the text given in PRD §4.1's "Full proposed text" block — the extraction instructions, the `category`/`unit_id`/`quote`/`text` field definitions, the full eight-category checklist table (`reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs`, each with its criteria and boundary rule exactly as written, including the `medications`/`tests`/`procedures` contrast-dye boundary rule and the `warning_signs` "extract it as part of the medication's own fact instead" addition), the abbreviation-injection instruction with the `{abbrev_block}` placeholder, the fabrication warnings, and the `{schema}`/`{units_block}` placeholders at the bottom. Copy the block verbatim — do not paraphrase or reformat it; PRD §7.1's regression test asserts on exact substrings (e.g. `"contrast dye"`) and the exact category names appearing in this file.
   - Acceptance criteria:
     - The file exists at `backend/care_plan/prompts/ground.txt`, is non-empty, and contains the literal placeholders `{schema}`, `{abbrev_block}`, `{units_block}` exactly once each.
     - `grep -c "contrast dye" backend/care_plan/prompts/ground.txt` returns at least 1.
     - Each of `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs` appears in the file; `low_priority` does not appear anywhere in the file.
     - Covered permanently by Task 6's `test_pipeline_prompts.py` additions.

### Task 3 — `backend/care_plan/pipeline.py`: imports, `_GroundedFactRaw`, `_GROUND_PROMPT`, `_GROUNDING_SCHEMA`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 2 and after PRD 01's Task 4 (`models/ledger.py` must already exist — see this file's prerequisite check above).
   - Changes (PRD §4.2):
     - Add to the existing import block:
       ```python
       from models.base import JsonModel
       from models.ledger import Fact, FactCategory, Unit
       from utils.text_normalization import normalize_text, normalize_with_offsets
       ```
     - Add a new prompt load alongside the three existing `_PROMPTS_DIR / "*.txt"` reads:
       ```python
       _GROUND_PROMPT = (_PROMPTS_DIR / "ground.txt").read_text(encoding="utf-8")
       ```
     - Add the new private model, exactly as specified in PRD §4.2 (including its full docstring — it documents why this is a separate model from `Fact` rather than a reused/excluded schema):
       ```python
       class _GroundedFactRaw(JsonModel):
           """Shape of one array element straight from the grounding LLM, before
           its quote is verified and converted to char_start/char_end offsets.
           Never constructed from anything but raw LLM JSON, never returned from
           ground(), never passed to 04 or 05 -- purely an intermediate parsing
           target local to this module (PRD 03 §4.2/§9). Its four fields are
           exactly Fact's LLM-facing fields; Fact itself additionally carries
           `id` (assigned by code, §4.4) and `char_start`/`char_end` (computed
           by code from `quote`, §4.3) in place of `quote`."""

           category: FactCategory
           unit_id: int
           quote: str
           text: str
       ```
     - Add the new schema constant, built from `_GroundedFactRaw` (not `Fact`), wrapped as a JSON array with nothing excluded:
       ```python
       _GROUNDING_SCHEMA = json.dumps(
           {"type": "array", "items": _llm_schema(_GroundedFactRaw, exclude=set())},
           indent=2,
       )
       ```
     - Do not touch `_STRUCTURING_SCHEMA`, `_SIMPLIFY_PROMPT`, `_CLARIFY_PROMPT`, `_STRUCTURE_PROMPT`, or any existing method in this class — this task only adds new module-level symbols.
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _GROUND_PROMPT, _GROUNDING_SCHEMA, _GroundedFactRaw"` (from `backend/`) succeeds.
     - `json.loads(pipeline_module._GROUNDING_SCHEMA)["type"] == "array"`, and `"category"`, `"unit_id"`, `"quote"`, `"text"` are all present in `schema["items"]["properties"]`; `"id"`, `"char_start"`, `"char_end"` are **not** present.
     - `_GroundedFactRaw(category="medications", unit_id=1, quote="x", text="y", id=1)` raises `ValidationError` (extra key `id` forbidden — `_GroundedFactRaw` has no such field).
     - Every existing test in `backend/tests/care_plan/` still passes unchanged (`python -m pytest tests/care_plan/ -q` from `backend/`) — this task is purely additive.
     - Covered permanently by Task 7's `test_pipeline_schema.py` additions.

### Task 4 — `backend/care_plan/pipeline.py`: helper functions (`_format_units_for_prompt`, `_is_verbatim_quote`, `_is_informative_quote`, `_locate_quote_offsets`, `_verify_ledger`)

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 1 (`normalize_with_offsets`) and Task 3 (`_GroundedFactRaw`, imports).
   - Changes (PRD §4.3): Add each function exactly as specified in PRD §4.3, with its full docstring (each docstring documents a specific decision —§4.5's drop-and-log policy, §9's resolved quote-informativeness floor, the multiple-occurrence/whitespace-span/dropped-character edge cases — do not shorten them):
     - `_format_units_for_prompt(units: list[Unit]) -> str` — renders the numbered source block, grouping consecutive units sharing `(file, page)` under one `=== file, page N ===` header; each unit line is `[<id>] <text>`.
     - `_is_verbatim_quote(quote: str, unit_text: str) -> bool` — the D1 check: `normalize_text(quote) in normalize_text(unit_text)`, with a blank/whitespace-only quote always returning `False` (guards `"" in x` always being `True`).
     - The two named constants `_QUOTE_MIN_LENGTH = 12` and `_QUOTE_LONG_WORD_MIN_LENGTH = 7`.
     - `_is_informative_quote(quote: str) -> bool` — the D2 check: `True` if the quote contains any digit, OR contains a word of `_QUOTE_LONG_WORD_MIN_LENGTH`+ characters, OR is `_QUOTE_MIN_LENGTH`+ characters long outright; otherwise `False`.
     - `_locate_quote_offsets(quote: str, unit_text: str) -> tuple[int, int]` — recovers `(char_start, char_end)` via `normalize_with_offsets(unit_text)`, finding the first occurrence of `normalize_text(quote)` in the normalized string and mapping the match's start/end back through the returned spans; raises `AssertionError` with the exact message in PRD §4.3 if the normalized quote isn't found (this function must only ever be called on a `(quote, unit_text)` pair that already passed `_is_verbatim_quote`).
     - `_verify_ledger(drafts: list[_GroundedFactRaw], units: list[Unit]) -> list[Fact]` — runs all three checks (unit exists, verbatim, informative) per draft, dropping and logging (`logger.warning`, exact messages in PRD §4.3) any draft that fails one, computing `char_start`/`char_end` via `_locate_quote_offsets` for survivors, and renumbering survivors to a contiguous `1..N` id sequence via `enumerate(verified, start=1)` (order of survivors preserved from the input order, not resorted).
   - Acceptance criteria:
     - `_is_verbatim_quote("Metoprolol 25mg", "cont. metoprolol  25mg BID")` is `True` (case + whitespace tolerance); `_is_verbatim_quote("", "any text")` is `False`.
     - `_is_informative_quote("40 mg")` is `True` (digit rule); `_is_informative_quote("warfarin")` is `True` (long-word rule, 8 ≥ 7); `_is_informative_quote("with")` is `False`.
     - `_locate_quote_offsets` on a quote already proven verbatim recovers offsets such that `unit_text[char_start:char_end]`, once normalized, equals the normalized quote — including across a raw double-space/tab and a case difference.
     - `_verify_ledger` drops a draft citing an unknown `unit_id`, drops one with a fabricated quote, drops one failing the informativeness floor, and renumbers survivors contiguously starting at 1, preserving input order.
     - Every check in this task is exercised without any LLM mock — pure functions. Permanent tests for all of the above land in Task 8.

### Task 5 — `CarePlanPipeline.ground()` method

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Tasks 2, 3, 4.
   - Changes (PRD §4.4, §4.6, §4.7): Add the method to `CarePlanPipeline`, exactly as specified in PRD §4.4, including its full docstring (documents the fatal-failure contract this method exposes for 06 to wire, and the long-form token-budget reasoning):
     ```python
     def ground(self, units: list[Unit], abbreviations: list[dict]) -> list[Fact]:
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

         drafts: list[_GroundedFactRaw] = []
         for idx, item in enumerate(raw, start=1):
             if not isinstance(item, dict):
                 raise SimplifyError(
                     ErrorCode.PIPELINE_VALIDATION_FAILED,
                     detail=f"grounding item {idx} is not a JSON object",
                 )
             try:
                 drafts.append(_GroundedFactRaw.model_validate(item))
             except ValidationError as e:
                 raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail=str(e), original=e)

         verified = _verify_ledger(drafts, units)
         if not verified:
             raise SimplifyError(
                 ErrorCode.PIPELINE_VALIDATION_FAILED,
                 detail="grounding produced zero verifiable facts",
             )
         return verified
     ```
     `format_abbreviations_for_prompt` is already imported from `utils.term_detection` at the top of this file (used by `simplify_language_with_term_plan`) — no new import needed for it. Do not add this method to `iter_steps`, `Constants.Pipeline.PIPELINE_STEPS`, or any progress-event wiring — that is 06's job (PRD §3 Non-Goals, §4.6). `ground()` does not catch its own exceptions; `LLMClient` exceptions (`LLM_MAX_TOKENS`, `VertexAPIError`, etc.) propagate unchanged.
   - Acceptance criteria:
     - `ground()` calls `self._generate_json` with `max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature=Constants.Llm.TEMPERATURE_JSON`.
     - A non-list LLM response raises `SimplifyError(ErrorCode.LLM_INVALID_JSON)`.
     - An array element failing `_GroundedFactRaw` validation (extra key, wrong type, missing field) raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)`.
     - A fully-verified-empty result (every draft fails `_verify_ledger`) raises `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)` with a detail mentioning the ledger was empty.
     - A response with at least one verifiable fact returns `list[Fact]` with sequential `id`s starting at 1.
     - `ground()` is not called anywhere in `iter_steps` after this task — `grep -n "self.ground(\|\.ground(" backend/care_plan/pipeline.py` shows only the method definition, no call site.
     - Permanent tests land in Task 7 (schema-boundary tests) and Task 8 (ledger-level tests).

### Task 6 — `backend/tests/care_plan/test_pipeline_prompts.py` additions

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 2 (and Task 3, since the import comes from `care_plan.pipeline`).
   - Changes (PRD §7.1): Add, alongside the three existing prompts' smoke/format-key tests, importing `_GROUND_PROMPT` from `care_plan.pipeline`:
     - `test_ground_prompt_is_non_empty_string` — `isinstance(_GROUND_PROMPT, str) and len(_GROUND_PROMPT) > 0`.
     - `test_ground_prompt_accepts_all_keys` — `.format(schema="{}", abbrev_block="abbr", units_block="[1] text")`; assert `"abbr"` and `"[1] text"` and `"{}"` all appear in the result.
     - `test_ground_prompt_raises_on_missing_key` — omit `units_block`; assert `KeyError`.
     - `test_ground_prompt_contains_contrast_dye_boundary_rule` — assert the literal substring `"contrast dye"` appears in `_GROUND_PROMPT` (regression guard tying the prompt directly to the bug this sub-project exists to fix).
     - `test_ground_prompt_lists_all_eight_categories` — assert each of `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`, `other`, `follow_up`, `warning_signs` appears in `_GROUND_PROMPT`, and that `low_priority` does not.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full, including the five new tests and all pre-existing ones.

### Task 7 — `backend/tests/care_plan/test_pipeline_schema.py` additions

   - Files: `backend/tests/care_plan/test_pipeline_schema.py`
   - Dependency: land after Tasks 3 and 5.
   - Changes (PRD §7.2): Add, following the file's existing `CarePlanPipeline.__new__(CarePlanPipeline)` + monkeypatched `_generate_json` convention:
     - `test_grounding_schema_is_a_json_array_of_grounded_fact_raw` — `json.loads(pipeline_module._GROUNDING_SCHEMA)`; assert `["type"] == "array"`, `"category"`/`"unit_id"`/`"quote"`/`"text"` present in `schema["items"]["properties"]`; assert `"id"`, `"char_start"`, `"char_end"` are **not** present.
     - `test_ground_assigns_sequential_ids_from_array_position` — monkeypatch `_generate_json` to return a two-element list, each matching `_GroundedFactRaw`'s exact shape (`category`/`unit_id`/`quote`/`text`, no `id` key); call `ground()` with two `Unit`s whose text contains each element's quote verbatim; assert the returned facts have `id == 1` and `id == 2` in order.
     - `test_ground_rejects_non_list_llm_output` — `_generate_json` returns a `dict`; assert `SimplifyError` with `error_code == ErrorCode.LLM_INVALID_JSON`.
     - `test_ground_rejects_extra_key_on_fact` — one array element carries an unexpected key (e.g. `"importance"`); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED`.
     - `test_ground_uses_long_form_token_budget_and_json_temperature` — capture kwargs like `test_structure_appointment_note_uses_long_form_token_budget` already does; assert `max_tokens == Constants.Llm.MAX_TOKENS_LONG_FORM` and `temperature == Constants.Llm.TEMPERATURE_JSON`.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_schema.py -q` (from `backend/`) passes in full, including the five new tests and all pre-existing ones (`test_structuring_schema_is_generated_from_structured_llm_model`, `test_structure_appointment_note_*`, `test_run_returns_care_plan_model_without_internal_scores`, `test_llm_schema_*`, all unaffected by this PRD).

### Task 8 — New `backend/tests/care_plan/test_pipeline_grounding.py`

   - Files: `backend/tests/care_plan/test_pipeline_grounding.py` (new file)
   - Dependency: land after Tasks 1, 3, 4, 5 (needs `normalize_with_offsets`, `_GroundedFactRaw`, all helper functions, and `ground()` itself).
   - Changes (PRD §7.3): Create the file with real `Unit`/`Fact`/`_GroundedFactRaw` fixtures (no LLM mock needed for most of these — only the prompt-construction tests touch `_generate_json`). Include every case below:
     - Prompt-construction tests:
       - `test_format_units_for_prompt_groups_consecutive_same_page_units_under_one_header` — three units, all `(file="note.pdf", page=1)`; assert exactly one `"=== note.pdf, page 1 ==="` line and three bracketed `[id]` lines.
       - `test_format_units_for_prompt_emits_new_header_on_page_change` — two units on page 1, one on page 2 of the same file; assert two header lines.
       - `test_format_units_for_prompt_emits_new_header_on_file_change` — two different files, both `page=1`; assert two header lines.
       - `test_ground_builds_prompt_with_abbreviations_and_units` — monkeypatch `self._generate_json` to capture the prompt string it's called with (not just return a canned value); assert the prompt contains the formatted abbreviation block and every unit's bracketed `[id]`.
     - Deterministic post-check tests (D1 — no LLM mock):
       - `test_is_verbatim_quote_exact_match` — `True`.
       - `test_is_verbatim_quote_tolerates_whitespace_noise` — unit text `"cont.  metoprolol"` (double space), quote `"cont. metoprolol"` (single space); `True`.
       - `test_is_verbatim_quote_tolerates_case_difference` — quote differs only in case from unit text; `True`.
       - `test_is_verbatim_quote_rejects_fabricated_quote` — unit text `"Pt to cont. metoprolol 25mg BID"`, quote `"increase metoprolol to 50mg"`; `False`. **This is the fabricated-quote case the PRD calls out explicitly — do not omit it.**
       - `test_is_verbatim_quote_rejects_blank_quote` — quote `""` or whitespace-only; `False`.
     - Quote informativeness floor tests (D2):
       - `test_is_informative_quote_accepts_short_numeric_quote` — quote `"40 mg"`; `True` via the digit rule.
       - `test_is_informative_quote_accepts_short_drug_name` — quote `"warfarin"` (8 chars, no digit); `True` via the long-word rule.
       - `test_is_informative_quote_rejects_short_common_word` — quote `"with"`; `False`.
       - `test_is_informative_quote_boundary_at_min_length` — a 12-char phrase built entirely from words under 7 characters (e.g. a `"see doctor  "`-style fixture with no word ≥ 7 chars); `True`. The same construction one character shorter; `False`.
     - Offset-recovery tests:
       - `test_locate_quote_offsets_exact_match` — assert `unit_text[char_start:char_end] == quote`.
       - `test_locate_quote_offsets_recovers_full_span_across_whitespace_noise` — unit text has a double space or tab where the quote has a single space; assert the recovered raw slice reproduces the raw double-space/tab form, not the quote's own spacing.
       - `test_locate_quote_offsets_recovers_span_despite_case_difference` — assert the recovered raw slice matches `unit_text`'s own casing, not the quote's.
       - `test_locate_quote_offsets_uses_first_occurrence_when_quote_repeats` — unit text contains the same (normalized) quote text twice; assert offsets point at the first occurrence.
       - `test_normalize_with_offsets_matches_normalize_text` — property/equivalence test: for a representative set of inputs (reuse `test_text_normalization.py`'s existing fixtures/cases — accented characters, mixed case, whitespace runs, leading/trailing whitespace, a dropped non-ASCII symbol), assert `normalize_with_offsets(text)[0] == normalize_text(text)` and `len(normalize_with_offsets(text)[1]) == len(normalize_with_offsets(text)[0])`.
     - `_verify_ledger`-level tests (drafts are `_GroundedFactRaw`, results are `Fact`):
       - `test_verify_ledger_drops_fact_citing_unknown_unit_id` — one draft cites `unit_id=999`; assert absent from result.
       - `test_verify_ledger_drops_fact_with_fabricated_quote` — one good draft, one with a quote not in its cited unit; assert only the good one survives.
       - `test_verify_ledger_drops_fact_failing_informativeness_floor` — one draft with a verbatim-but-uninformative quote (e.g. `"with"`), one good draft; assert only the good one survives.
       - `test_verify_ledger_populates_char_start_and_char_end_from_quote` — assert `Fact.char_start`/`Fact.char_end` are present `int`s, `unit.text[fact.char_start:fact.char_end]` recovers the draft's quote (normalize-tolerant comparison), and the resulting `Fact` object has no `quote` attribute (`hasattr(fact, "quote") is False`).
       - `test_verify_ledger_renumbers_surviving_facts_contiguously` — three drafts, the second is dropped (bad `unit_id`); assert survivors come back with ids `1` and `2`, not `1` and `3`.
       - `test_verify_ledger_preserves_order_of_surviving_facts` — order of survivors matches input order, not resorted by category or anything else.
     - `ground()`-level fatal-failure test:
       - `test_ground_raises_when_verified_ledger_is_empty` — monkeypatch `_generate_json` to return facts that all fail verification (e.g. all cite nonexistent unit ids); assert `SimplifyError` with `error_code == ErrorCode.PIPELINE_VALIDATION_FAILED` and a detail mentioning the ledger was empty.
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_grounding.py -q` (from `backend/`) passes; every case listed above is present as its own test function.

### Task 9 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-8 (and after PRD 01's and 02's tasks have landed in this repo, since `ground()`'s imports depend on both).
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors attributable to this PRD's changes. Any remaining failures must trace only to PRD 01/02 (or later sub-projects') scope — list exactly which test functions and why if any remain.
     - `python -c "from care_plan.pipeline import CarePlanPipeline, _GROUND_PROMPT, _GROUNDING_SCHEMA; from utils.text_normalization import normalize_text, normalize_with_offsets; assert hasattr(CarePlanPipeline, 'ground')"` (from `backend/`) succeeds — a single smoke import proving every new symbol this PRD introduces is wired together correctly.
     - `grep -n "self.ground(\|\.ground(units" backend/care_plan/pipeline.py` shows no call site inside `iter_steps` — confirms Task 5's "no wiring" boundary held through to the end of this PRD's own work.
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched.

---

## Handed off to other sub-projects (specified here, not implemented here — do not action as part of this task list)

Per PRD §3 Non-Goals and its header cross-references, the following are **out of scope for this PRD's tasks** even though this PRD's own text specifies exactly what they must do:

- **To 04 (assemble-and-render)**: consumes `list[Fact]` (this PRD's `ground()` output) to populate `CarePlan` fields — the category→field mapping, plain-language rendering, `summary`/`summary_fact_ids`, `low_priority` assignment, `questions` generation, near-duplicate merging. Must call `models.ledger.quote_for(fact, units_by_id)` (01) wherever it needs the evidence text, since `Fact.quote` does not exist (§9).
- **To 05 (review-and-correct)**: re-checks the ledger for fidelity correction and citation soundness (every output item's `source_fact_ids` cites a real fact id). Same `quote_for()` dependency as 04.
- **To 06 (pipeline-orchestration)**: wiring `CarePlanPipeline.ground` into `iter_steps` — assigning it a `Constants.Pipeline.PIPELINE_STEPS` entry and progress-event step number, and implementing the fatal-step wrapping this PRD specifies (§4.6: grounding has no fallback, must be treated like `STRUCTURE_DOCUMENT` is today) but does not itself implement. No pipeline call site for `ground()` exists anywhere in the codebase after this PRD's own tasks land — confirmed by Task 9's grep.
- Deletion of `simplify_language.txt`, `clarify_and_action.txt`, `structure_note.txt`, or the two prose-pipeline methods they back is explicitly **not** this PRD's job (04's, when assembly replaces them) — none of this PRD's tasks touch those files or methods.
- The measurement of extraction recall on raw vs. pre-simplified text (brief §5's Open Risks table) is an explicit follow-up, not gated on anything in this task list (PRD §9, final `[DEFERRED]` item).

## Summary of what requires you (not a dev agent)

Per PRD §8, one item is a session-local, judgement-based check against real infrastructure and cannot be automated by a dev agent:

1. **Prompt smoke test against real notes.** No automated test in this sub-project (or anywhere in this repo) checks clinical fidelity. Once 06 wires `ground()` into the live pipeline, run it via ngrok + pm2 (`SERVICE_MODE=combined`) against 2-3 real or realistic de-identified notes, specifically checking: (a) a contrast-dye-during-imaging sentence lands in `tests`/`procedures`, not `medications` — the bug this whole category table exists to fix; (b) a dense abbreviation line (e.g. `f/u cards 4/12`) produces a `text` field with the expansion while `quote` stays verbatim; (c) a realistic multi-page note does not hit `LLM_MAX_TOKENS` at the 65,536-token output budget.

No new environment variables, credentials, or console configuration are needed for this PRD — it is prompt + pure Python only (PRD §8).

No PRD §9 items are `[OPEN]` — the gate was clear; all 9 tasks above derive from `[RESOLVED]` decisions only. One `[DEFERRED]` item (recall measurement) is recorded above as a hand-off, not a task, since the PRD itself defers it as a follow-up, not a gate.
