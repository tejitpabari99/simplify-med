# Tasks: Numeric Integrity

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (`backend/models/ledger.py` — `Fact{id, category, unit_id, char_start, char_end, text}`, `quote_for()`; `backend/models/care_plan/care_plan.py` — the six item models' `source_fact_ids`), 03 (grounding's `Fact.text` semantics), 04 (`_verify_assembly`, `_format_facts_for_prompt`, `_STYLE_RULES` extraction — already landed, verified below), 05 (`correct.txt` also consumes `_STYLE_RULES`, so this PRD's prompt change reaches both call sites automatically). Depended on by: none — a leaf sub-project in this batch. PRD 11 (omission-signal) edits the same file (`pipeline.py`) for an unrelated signal; §4.7 states the shared-file seam this task list honors (Task 3's call must stay the last statement in `_verify_assembly`).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). Single file: `python -m pytest tests/care_plan/test_pipeline_numeric_parity.py -q`; single test: `...::test_name -q`.
- Lint: `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given.
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited. Non-goals (§3) are binding: log-only, no gate, no new LLM call, no signature changes, no frontend, no new `ErrorCode`.
- **Line-number note (verified against the actual current `backend/care_plan/pipeline.py` at authoring time, PRDs 01-09 already landed):** `_QUOTE_MIN_LENGTH = 12` at line 132; `_STYLE_RULES` load at line 291; `_format_facts_for_prompt` at line 334; `_ITEM_LIST_FIELDS` at line 349; `_RICHNESS_CHECKS` at line 356; `_log_thin_fields` at line 367; `_verify_assembly` at line 394, ending with `return model.model_copy(update=updates) if updates else model` (the last line of the function, immediately followed by `_WHY_PATH_RE = re.compile(...)` for PRD 05's territory); the two `style_rules=_STYLE_RULES` call sites (`assemble_and_render`, `correct`) at lines 747 and 809. These match the PRD's own citations exactly. `re` and `logger = logging.getLogger(__name__)` are already imported/defined at the top of `pipeline.py` (lines 21 and 55) — no new imports needed for this PRD's pure-Python additions. Locate everything below by symbol, not by these line numbers, since later edits in this same batch may shift them further — these are for orientation only.
- **Verified against real code, not assumed** (per this task's own authoring instructions): `backend/care_plan/prompts/_style_rules.txt`'s current text matches the PRD's quoted PII paragraph and LANGUAGE RULES bullets **byte-for-byte**, including the exact existing "Never invent a number..." bullet with no added clause yet. `_NUMERIC_PARITY_FIELDS` (PRD §4.4) was checked attribute-by-attribute against `backend/models/care_plan/care_plan.py`'s six item models — every field name in the PRD's map exists on its model exactly as written (`Medication.plain_name`/`side_effects_to_watch`/`change`, `OtherInstruction.steps`, `FollowUp.time_frame`, `WarningSign.related_to`, etc.); **no corrections were needed**. Task 2 below reproduces the map verbatim from the PRD on this basis.

---

### Task 1 — Insert the `NUMERACY` paragraph into `backend/care_plan/prompts/_style_rules.txt`

   - Files: `backend/care_plan/prompts/_style_rules.txt`
   - Changes (PRD §4.1): The file today reads, verbatim (confirmed by direct read — this is the file's entire current content):
     ```
     PII -- replace every person's name and every facility's name with a generic form: a clinician's name becomes "your doctor" (or "your surgeon" / "your cardiologist" / etc. if the fact itself names that specialty); a hospital or clinic name becomes "the hospital" or "the clinic." Example: "Doctor Alok Singh" becomes "your doctor." This is the one case where you do not preserve a fact's exact wording -- a generic form loses the patient no clinical information. The patient's own name, date of birth, address, and insurance details must never appear either.

     LANGUAGE RULES -- apply to every field you write:
     - Active voice. Address the patient as "you."
     - One idea per sentence. Keep sentences under about 20 words.
     - Expand every abbreviation. Never print "BID", "HTN", "f/u", or similar -- use the plain words.
     - Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number.
     - Never add urgency, prognosis, or medical advice beyond what a fact states.
     - Start every patient action (in medications, tests, procedures, other, follow_up) with a clear verb: Take / Call / Schedule / Ask / Bring / Watch / Avoid / Continue / Stop.
     ```
     Make exactly two edits, both from PRD §4.1's proposed diff, preserving every other byte of the file unchanged:
     1. **Insert** a new `NUMERACY` paragraph between the `PII` paragraph and the `LANGUAGE RULES` heading (i.e., after the `PII` paragraph's final sentence and its blank line, before `LANGUAGE RULES --`):
        ```
        NUMERACY -- a number is the easiest place to silently add a judgement the source never made, so give every one in this document the same verbatim discipline PII gets for names, plus one allowance: copy a value and its unit exactly as the fact states them ("A1c 7.2%" stays "your A1c was 7.2%"), changing only spacing or spelling the way LANGUAGE RULES below already permits ("metoprolol 25mg" -> "metoprolol 25 mg" is fine; the number and the unit itself are not). Never add a normal/abnormal/elevated/low/high label to a bare value unless the fact itself uses that word -- a fact giving "blood pressure 158/96" is a number, not a verdict; do not write "high blood pressure" for it unless a fact says so. Never add a reference range that isn't in the fact -- "A1c 7.2%" does not become "A1c 7.2% (normal range 4.0-5.6%)." Never round, truncate, or otherwise adjust an already-exact number -- "ejection fraction 42%" stays "42%," never "about 40%" or "40%." Never convert a unit -- "creatinine 1.4 mg/dL" stays mg/dL, never becomes a value you compute yourself in µmol/L. Never reframe a percentage as a frequency or a frequency as a percentage -- "occurs in 30% of patients" does not become "happens 3 out of 10 times you take it," and "taken twice daily" does not become "100% compliance." Never attach a severity, urgency, or color ("critical," "dangerously high," "mild") to a number the fact does not itself grade. You may add an interpretation of a number ONLY when the fact itself already states that interpretation in its own words -- a fact reading "A1c 7.2%, indicating poor control" may carry "indicating poor control" into the rendered field, because the source made that judgement, not you.
        ```
     2. **Replace** the existing "Never invent a number..." bullet with the same sentence plus one appended clause (do not touch any other bullet):
        - Old: `- Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number.`
        - New: `- Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number -- see NUMERACY above for the rest of this document's numeric rules.`
     - Do not touch `assemble_and_render.txt` or `correct.txt` — both already consume `_STYLE_RULES` via the `{style_rules}` placeholder; this is purely additive text in one shared file (PRD §4.1's final paragraph).
   - Acceptance criteria:
     - `grep -c "^NUMERACY --" backend/care_plan/prompts/_style_rules.txt` returns `1`.
     - The `NUMERACY` paragraph appears strictly after the `PII` paragraph and strictly before the `LANGUAGE RULES` heading: `grep -n "^PII --\|^NUMERACY --\|^LANGUAGE RULES --" backend/care_plan/prompts/_style_rules.txt` lists them in that order, one per line.
     - `grep -c "see NUMERACY above" backend/care_plan/prompts/_style_rules.txt` returns `1`, and it is on the same line as the existing "Never invent a number" bullet (`grep -n "Never invent a number" backend/care_plan/prompts/_style_rules.txt` shows both substrings on one line).
     - The file still contains exactly one `PII --` paragraph and one `LANGUAGE RULES --` heading (`grep -c "^PII --" ...` and `grep -c "^LANGUAGE RULES --" ...` both return `1`), and the five bullets other than "Never invent a number" are byte-for-byte unchanged (`grep -c "Active voice. Address the patient" backend/care_plan/prompts/_style_rules.txt` etc. each return `1`).
     - `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) still passes in full — this task does not yet add the new prompt-content tests (Task 4 does), but must not break `test_style_rules_is_non_empty_and_shared` or any existing `_STYLE_RULES`/`_ASSEMBLE_PROMPT`/`_CORRECT_PROMPT` test.
     - Covered permanently by Task 4's new tests.

### Task 2 — `backend/care_plan/pipeline.py`: the tokenizer (`_UNIT_WORD_RE`, `_NUMBER_TOKEN_RE`, `_normalize_number`, `_TIME_OF_DAY_RE`, `_BARE_DATE_RE`, `_MONTH_NAMES`, `_WRITTEN_DATE_RE`, `_excluded_spans`, `_extract_number_tokens`)

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: none (pure additions; does not depend on Task 1). Land before Task 3 (the parity check calls `_extract_number_tokens`).
   - Changes (PRD §4.2): Add the following module-level constants and functions verbatim, placed immediately after `_verify_assembly` and its existing helpers (next to `_QUOTE_MIN_LENGTH` et al., matching this file's "same-file call, not an import" precedent for reusing constants across sub-projects — PRD 04 §9). Do not place these inside `_verify_assembly`'s own block or ahead of it; §4.7's seam requires `_verify_assembly` itself to stay a stable call site for Task 3's one-line wiring.
     ```python
     _UNIT_WORD_MAX_LENGTH = 15  # reasoned, not calibrated (PRD 10 §4.2): long enough
     # for the longest realistic compound lab unit (mmol/L, mIU/mL), short enough
     # that it can't silently swallow the start of the next clinical word if a
     # unit is missing.

     _UNIT_WORD_RE = r"%|[A-Za-z][A-Za-z%/]{0,14}"

     _NUMBER_TOKEN_RE = re.compile(
         r"""
         (?P<num>
             \d{1,3}(?:,\d{3})+(?:\.\d+)?        # 1,000 or 1,000.5
           | \d+/\d+                             # fraction OR ratio/date shape: 1/2, 158/96, 4/12
           | \d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?   # range: 5-10, 5.5-10.2
           | \d+(?:\.\d+)?                       # plain integer or decimal
         )
         [ ]?
         (?P<unit>""" + _UNIT_WORD_RE + r""")?
         """,
         re.VERBOSE,
     )


     def _normalize_number(raw: str) -> str:
         """Canonicalize one bare number's own digits -- leading zeros, thousands
         separators, and a trailing decimal zero are formatting, not value, per
         the same principle assemble_and_render.txt's own worked example applies
         to unit spacing ("25mg" -> "25 mg" is a style change). Called on each
         component of a range/fraction separately, never on the whole thing."""
         raw = raw.replace(",", "")
         if "." in raw:
             integer_part, _, frac_part = raw.partition(".")
             frac_part = frac_part.rstrip("0")
             integer_part = integer_part.lstrip("0") or "0"
             return f"{integer_part}.{frac_part}" if frac_part else integer_part
         return raw.lstrip("0") or "0"


     _TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
     _BARE_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b(?![ \t]*[A-Za-z%])")
     _MONTH_NAMES = (
         "january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december",
         "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
     )
     _WRITTEN_DATE_RE = re.compile(
         r"\b(?:" + "|".join(_MONTH_NAMES) + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
         re.IGNORECASE,
     )


     def _excluded_spans(text: str) -> list[tuple[int, int]]:
         """Date/time-shaped spans, dropped from BOTH sides of every numeric-
         parity comparison (PRD 10 §4.2's disclosed blind spot -- see there for
         why). _BARE_DATE_RE's negative lookahead is what lets a unit-bearing
         slash pair ("158/96 mmHg", "1/2 tablet") fall through untouched --
         only a slash pair with nothing unit-shaped after it is excluded."""
         spans = [m.span() for m in _TIME_OF_DAY_RE.finditer(text)]
         spans += [m.span() for m in _BARE_DATE_RE.finditer(text)]
         spans += [m.span() for m in _WRITTEN_DATE_RE.finditer(text)]
         return spans


     def _extract_number_tokens(text: str) -> set[tuple[str, str]]:
         """Tokenize every number-with-optional-unit out of `text` into a set of
         (normalized_number, normalized_unit) pairs; unit is "" when none is
         attached. Excludes date/time-shaped spans entirely (see above)."""
         excluded = _excluded_spans(text)
         tokens: set[tuple[str, str]] = set()
         for m in _NUMBER_TOKEN_RE.finditer(text):
             if any(m.start() >= s and m.end() <= e for s, e in excluded):
                 continue
             num, unit = m.group("num"), (m.group("unit") or "").lower()
             if "/" in num:
                 num_norm = "/".join(_normalize_number(p) for p in num.split("/"))
             elif "-" in num:
                 num_norm = "-".join(_normalize_number(p.strip()) for p in num.split("-"))
             else:
                 num_norm = _normalize_number(num)
             tokens.add((num_norm, unit))
         return tokens
     ```
     `_UNIT_WORD_MAX_LENGTH` is declared for documentation/tunability per PRD §4.2/§8 ("tune `_UNIT_WORD_MAX_LENGTH` (15) if real notes surface..."); it is not referenced by the regex literal above (the `{0,14}` in `_UNIT_WORD_RE` already encodes "up to 14 more characters after the first" = 15 total) — keep the constant as documentation of that number's derivation, matching the PRD's own text; do not attempt to parameterize the regex from the constant, since the PRD does not specify that refactor.
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _extract_number_tokens, _normalize_number, _excluded_spans, _UNIT_WORD_MAX_LENGTH"` (from `backend/`) succeeds.
     - `_extract_number_tokens("25mg")  == _extract_number_tokens("25 mg")` and both equal `{("25", "mg")}`.
     - `_extract_number_tokens("25MG") == _extract_number_tokens("25mg")`.
     - `_normalize_number("025") == "25"`; `_normalize_number("7.20") == "7.2"`; `_normalize_number("7.0") == "7"`.
     - `_extract_number_tokens("1,000 units") == _extract_number_tokens("1000 units")`.
     - `_extract_number_tokens("5-10 days")` contains exactly one token whose number component is `"5-10"`.
     - `_extract_number_tokens("158/96 mmHg")` and `_extract_number_tokens("1/2 tablet")` each yield a non-empty token set (kept, not excluded as a date).
     - `_extract_number_tokens("4/12")` (no trailing unit) returns `set()`.
     - `_extract_number_tokens("April 12")` returns `set()`.
     - `_extract_number_tokens("7:30 AM")` returns `set()`.
     - `_extract_number_tokens("twice a day")` returns `set()`.
     - Every existing test in `backend/tests/care_plan/` still passes (`python -m pytest tests/care_plan/ -q`) — this task is purely additive to the module.
     - Covered permanently by Task 5's tokenizer tests.

### Task 3 — `backend/care_plan/pipeline.py`: `_NUMERIC_PARITY_FIELDS`, `_check_numeric_parity`, wired into `_verify_assembly`

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 2 (`_check_numeric_parity` calls `_extract_number_tokens`).
   - Changes (PRD §4.3, §4.4, §4.6, §4.7): Add, immediately after Task 2's tokenizer block:
     ```python
     _NUMERIC_PARITY_FIELDS: dict[str, tuple[str, ...]] = {
         "medications": ("title", "plain_name", "why", "dosage", "frequency",
                          "timing", "duration", "instructions",
                          "side_effects_to_watch", "change"),
         "tests": ("title", "plain_name", "why", "description", "preparation"),
         "procedures": ("title", "plain_name", "why", "what_to_expect", "timeframe"),
         "other": ("title", "why", "description", "frequency", "duration"),  # steps[] handled separately
         "follow_up": ("time_frame", "description"),
         "warning_signs": ("symptom", "what_it_might_mean", "what_to_do", "related_to"),
     }


     def _check_numeric_parity(model: CarePlan, facts: list[Fact]) -> None:
         """R3 (PRD 10 §4.3/§4.4): log-only, model-free check that every number
         a rendered field states was present in at least one fact the item
         cites. Never mutates or drops anything -- unlike the citation-existence
         guards above it, a numeric mismatch has no safe deterministic repair
         (which side is right is exactly the judgement call this check cannot
         make), so logging is this PRD's entire, LOCKED contract."""
         facts_by_id = {f.id: f for f in facts}
         mismatches = 0

         def _backing_tokens(fact_ids: list[int]) -> set[tuple[str, str]]:
             tokens: set[tuple[str, str]] = set()
             for fid in fact_ids:
                 fact = facts_by_id.get(fid)
                 if fact is not None:
                     tokens |= _extract_number_tokens(fact.text)
             return tokens

         def _check_field(field: str, index: int | str, attr: str, value: str,
                           backing: set[tuple[str, str]], num_cited: int) -> int:
             if not value:
                 return 0
             backing_numbers = {num for num, _unit in backing}
             found = 0
             for num, unit in _extract_number_tokens(value):
                 if (num, unit) in backing:
                     continue
                 found += 1
                 if num in backing_numbers:
                     logger.warning(
                         "assemble_and_render: numeric parity -- %s[%s].%s has a "
                         "value matching a cited fact's number but with a "
                         "different or missing unit (unit=%r)",
                         field, index, attr, unit,
                     )
                 else:
                     logger.warning(
                         "assemble_and_render: numeric parity -- %s[%s].%s "
                         "contains a number not found in any of its %d cited "
                         "fact(s)", field, index, attr, num_cited,
                     )
             return found

         for field, attrs in _NUMERIC_PARITY_FIELDS.items():
             for index, item in enumerate(getattr(model, field)):
                 backing = _backing_tokens(item.source_fact_ids)
                 num_cited = len(item.source_fact_ids)
                 for attr in attrs:
                     mismatches += _check_field(field, index, attr, getattr(item, attr, ""), backing, num_cited)
                 if field == "other":
                     for step_idx, step in enumerate(item.steps):
                         mismatches += _check_field(field, index, f"steps[{step_idx}]", step, backing, num_cited)

         if model.summary:
             mismatches += _check_field("summary", "-", "summary", model.summary,
                                         _backing_tokens(model.summary_fact_ids),
                                         len(model.summary_fact_ids))

         if mismatches:
             logger.warning(
                 "assemble_and_render: numeric parity check flagged %d mismatch(es) "
                 "in this care plan", mismatches,
             )
     ```
     **Field map validated against the real models (this task's own verification, not an assumption):** every attribute named above was checked against `backend/models/care_plan/care_plan.py` and exists exactly as written — `Medication.plain_name`/`side_effects_to_watch`/`change`, `OtherInstruction.steps`/`why`/`description`/`frequency`/`duration`, `FollowUp.time_frame`/`description`, `WarningSign.symptom`/`what_it_might_mean`/`what_to_do`/`related_to`. No field name needed correction. Do not add `status` or `source_fact_ids` to any tuple (neither is free text), and do not add `urgency` to `warning_signs`' tuple (it is a nullable enum, not free text) — these three deliberate omissions match the PRD's map exactly.

     Then wire the call at the very end of `_verify_assembly` (PRD §4.4's "Wired at the very end of `_verify_assembly`" / §4.7's seam requirement that this stay the *last* statement). Change:
     ```python
         return model.model_copy(update=updates) if updates else model
     ```
     to:
     ```python
         result = model.model_copy(update=updates) if updates else model
         _check_numeric_parity(result, facts)   # PRD 10 R3 -- log-only, never mutates `result`
         return result
     ```
     This is the only edit to `_verify_assembly`'s existing body — do not touch `_log_thin_fields`, the `questions` truncation, the `summary_fact_ids` filter, or the `_ITEM_LIST_FIELDS` loop above it. Per §4.7, if PRD 11 also touches `_verify_assembly`, this call must remain the last statement before the `return`, since it depends on the fully-`updates`-applied `result`, not the pre-guard `model`.
   - Acceptance criteria:
     - `python -c "from care_plan.pipeline import _NUMERIC_PARITY_FIELDS, _check_numeric_parity"` (from `backend/`) succeeds.
     - `grep -n "_check_numeric_parity(result, facts)" backend/care_plan/pipeline.py` shows it as the line immediately before `_verify_assembly`'s `return result` and after `result = model.model_copy(...)`.
     - `_verify_assembly` never raises and never changes `result`'s field values because of this check (only the pre-existing three guards may change `result`).
     - A `CarePlan` with a `medications[0].dosage` value whose number matches none of its cited fact's numbers produces exactly one `WARNING` log record naming `medications[0].dosage`; the returned model's `dosage` field is untouched.
     - A same-number-different-unit case produces the "different or missing unit" message, not the "not found in any cited fact" message.
     - `python -m pytest tests/ -q` (from `backend/`) passes with zero new failures.
     - Covered permanently by Task 5's `test_pipeline_numeric_parity.py`.

### Task 4 — `backend/tests/care_plan/test_pipeline_prompts.py`: `NUMERACY` content-regression tests

   - Files: `backend/tests/care_plan/test_pipeline_prompts.py`
   - Dependency: land after Task 1 (needs the `NUMERACY` text in place). Independent of Tasks 2/3.
   - Changes (PRD §7.1): Add the following tests, mirroring the file's existing `test_style_rules_is_non_empty_and_shared` / `test_assemble_prompt_accepts_all_keys` / `test_correct_prompt_accepts_all_keys` pattern (all three already exist in this file — reuse them, do not redefine). No new imports needed (`_STYLE_RULES`, `_ASSEMBLE_PROMPT`, `_CORRECT_PROMPT` are already imported at the top of this file).
     ```python
     def test_style_rules_contains_numeracy_block():
         assert "NUMERACY" in _STYLE_RULES


     def test_style_rules_numeracy_forbids_added_label():
         assert "blood pressure 158/96" in _STYLE_RULES
         assert "unless the fact itself uses that word" in _STYLE_RULES


     def test_style_rules_numeracy_forbids_reference_range():
         assert "normal range 4.0-5.6%" in _STYLE_RULES


     def test_style_rules_numeracy_forbids_rounding():
         assert "ejection fraction 42%" in _STYLE_RULES


     def test_style_rules_numeracy_forbids_unit_conversion():
         assert "creatinine 1.4 mg/dL" in _STYLE_RULES


     def test_style_rules_numeracy_forbids_percentage_frequency_reframe():
         assert "3 out of 10 times" in _STYLE_RULES


     def test_style_rules_numeracy_permits_source_stated_interpretation():
         assert "indicating poor control" in _STYLE_RULES


     def test_assemble_and_correct_prompts_both_receive_numeracy_block():
         assembled = _ASSEMBLE_PROMPT.format(
             schema="{}",
             facts_block="[1] medications: x",
             style_rules=_STYLE_RULES,
             sub_block="s",
             medical_block="m",
             abbrev_block="a",
         )
         corrected = _CORRECT_PROMPT.format(
             corrections_block="c",
             style_rules=_STYLE_RULES,
             care_plan_block="{}",
             schema="{}",
         )
         assert "NUMERACY" in assembled
         assert "NUMERACY" in corrected
     ```
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_prompts.py -q` (from `backend/`) passes in full, including all 8 new tests above alongside every pre-existing test in the file (`_GROUND_PROMPT`, `_ASSEMBLE_PROMPT`, `_CORRECT_PROMPT`, `_STYLE_RULES` tests untouched).

### Task 5 — New file: `backend/tests/care_plan/test_pipeline_numeric_parity.py`

   - Files: `backend/tests/care_plan/test_pipeline_numeric_parity.py` (new file)
   - Dependency: land after Task 2 and Task 3 (needs `_extract_number_tokens`, `_check_numeric_parity`, and the `_verify_assembly` wiring).
   - Changes (PRD §7.2): the load-bearing tests for this sub-project's tokenizer and parity check. Follow `test_pipeline_assembly.py`'s established fixture conventions — import `Fact` from `models.ledger`; import `CarePlan` and the item models from `models.care_plan.care_plan`; reuse (or copy locally) a `_make_item`-style helper for building minimal item instances with `source_fact_ids` and a `status`/`urgency` default, matching `test_pipeline_assembly.py`'s existing `_make_item` (field `warning_signs` needs `urgency=None`; every other item field needs `status="to_do"`). Import from `care_plan.pipeline`: `_extract_number_tokens`, `_normalize_number`, `_excluded_spans`, `_check_numeric_parity`, `_verify_assembly`.

     **Tokenizer (`_extract_number_tokens`, `_normalize_number`, `_excluded_spans`)** — PRD §7.2:
     - `test_extract_number_tokens_normalizes_attached_vs_spaced_unit` — `"25mg"` and `"25 mg"` produce the identical token.
     - `test_extract_number_tokens_is_case_insensitive_on_unit` — `"25MG"` and `"25mg"` match.
     - `test_normalize_number_strips_leading_zeros` — `"025"` -> `"25"`.
     - `test_normalize_number_strips_trailing_decimal_zeros` — `"7.20"` and `"7.0"` normalize to `"7.2"` and `"7"` respectively.
     - `test_extract_number_tokens_handles_thousands_separator` — `"1,000 units"` and `"1000 units"` match.
     - `test_extract_number_tokens_matches_range` — `"5-10 days"` extracts one range token.
     - `test_extract_number_tokens_keeps_slash_pair_with_trailing_unit` — `"158/96 mmHg"` (blood pressure) and `"1/2 tablet"` (fraction) are both kept as real tokens.
     - `test_extract_number_tokens_excludes_bare_slash_pair_with_no_unit` — `"4/12"` alone yields no token.
     - `test_extract_number_tokens_excludes_written_month_and_day` — `"April 12"` yields no token for `12`.
     - `test_extract_number_tokens_excludes_time_of_day` — `"7:30 AM"` yields no token for either `7` or `30`.
     - `test_extract_number_tokens_returns_empty_set_for_pure_word_frequency` — `"twice a day"` (the "BID" rewrite target) yields the empty set.

     **Parity check (`_check_numeric_parity`, exercised through `_verify_assembly`)** — PRD §7.2:
     - `test_numeric_parity_passes_silently_when_dosage_matches_cited_fact` — fact `text="metoprolol 25 mg"`, item `dosage="25 mg"`; no numeric-parity warning logged.
     - `test_numeric_parity_logs_when_dosage_drifts_from_cited_fact` — fact `text="metoprolol 25mg"`, item `dosage="250 mg"`; asserts a `WARNING` naming `medications[0].dosage`, and asserts the model returned by `_verify_assembly` is otherwise unchanged (log-only — no drop, no mutation of the field itself).
     - `test_numeric_parity_logs_unit_mismatch_as_a_distinct_message_from_missing_value` — fact `text="warfarin 5 mg"`, item `dosage="5 mL"`; asserts the "different or missing unit" message, not the "not found in any cited fact" message.
     - `test_numeric_parity_checks_union_of_multiple_cited_facts` — item cites two facts, each supplying half of a merged rendering's numbers; no false positive.
     - `test_numeric_parity_ignores_field_with_no_digits` — a `why` field with ordinary prose and a fact with a number in a different field; no warning tied to the digit-free field.
     - `test_numeric_parity_flags_added_reference_range_not_in_any_cited_fact` — fact `text="A1c 7.2%"`, item `description="A1c 7.2% (normal range 4.0-5.6%)"`; the injected range's numbers are flagged even though `7.2` itself matches.
     - `test_numeric_parity_does_not_flag_bid_to_twice_daily_rewrite` — fact `text="metoprolol twice daily"` (grounding already expands "BID" per `ground.txt` line 11), item `frequency="twice a day"`; no digits on either side, no warning.
     - `test_numeric_parity_does_not_flag_date_reformatted_to_month_name` — fact `text="follow-up 4/12"`, item `time_frame="Follow up on April 12."`; no warning (the disclosed blind spot, asserted as intended behavior, not an accident).
     - `test_numeric_parity_summary_checked_against_summary_fact_ids` — a drifted number in `summary` against `summary_fact_ids`' facts is flagged the same way an item field is.
     - `test_numeric_parity_skips_diagnosis_and_reason_for_visit` — a numeric mismatch planted in `diagnosis.details[0].description` (which has no `source_fact_ids` to check against) produces no warning and no error — documents the structural non-coverage rather than silently relying on it.
     - `test_numeric_parity_log_never_contains_the_raw_digits_or_field_text` — the PHI-adjacent guard, mirroring `test_verify_assembly_thin_field_log_never_contains_clinical_text` directly: plant a distinctive dosage value (e.g. `"777 mg"` with no matching fact), assert it (and its `repr()`) never appears in any `caplog` record, while the field path (`medications[0].dosage`) does.
     - `test_numeric_parity_never_mutates_or_drops_the_care_plan` — parametrized across a mismatch and a match case; `_verify_assembly`'s returned model is field-for-field identical to what assembly produced (aside from the pre-existing three guards), regardless of what the parity check logged.
   - Acceptance criteria:
     - `python -m pytest tests/care_plan/test_pipeline_numeric_parity.py -q` (from `backend/`) passes in full; every test named above is present as its own test function (parametrized cases may use `pytest.mark.parametrize` for the two "never mutates" scenarios rather than duplicating the whole test body).
     - `python -m pytest tests/ -q` (from `backend/`) passes with zero failures and zero errors attributable to this PRD.

### Task 6 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-5.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors.
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched (`care_plan/pipeline.py`, `care_plan/prompts/_style_rules.txt` is not lint-checked, `tests/care_plan/test_pipeline_prompts.py`, `tests/care_plan/test_pipeline_numeric_parity.py`).
     - `python -c "from care_plan.pipeline import _check_numeric_parity, _NUMERIC_PARITY_FIELDS, _extract_number_tokens; from models.care_plan.care_plan import CarePlan; from models.ledger import Fact; assert set(_NUMERIC_PARITY_FIELDS) == {'medications','tests','procedures','other','follow_up','warning_signs'}"` (from `backend/`) succeeds — a single smoke check proving the field map covers exactly the six item families and no more.
     - `grep -n "_check_numeric_parity(result, facts)" backend/care_plan/pipeline.py` shows exactly one call site, positioned as the last statement in `_verify_assembly` before its `return`.
     - No test anywhere in `backend/tests/` asserts on the *value* of a mismatched number or field text appearing in a log record (PHI-adjacent guard, §4.4) — spot-check `grep -n "caplog" backend/tests/care_plan/test_pipeline_numeric_parity.py` matches only the tests listed in Task 5.

---

## Summary of what requires you (not a dev agent)

Per PRD §8, none of the following can be automated by a dev agent:

1. **Prompt smoke test against real notes**, once this lands (ngrok + pm2, `SERVICE_MODE=combined` — no separate wiring step needed, since `_verify_assembly` is already live in `iter_steps`): confirm the `NUMERACY` block doesn't make the model *more* conservative in an unintended way (e.g., refusing to render a value at all rather than copying it verbatim), and spot-check the parity check's log volume on 5-10 real/realistic notes for false positives from the disclosed blind spots (§4.2, §9) — particularly standalone ordinal dates and any note with an unusual number format not anticipated here.
2. **Decide whether the false-positive rate is low enough to eventually promote a numeric-parity failure into a pre-seeded reviewer correction** (feeding it into `review()`/`correct()`'s corrections list rather than only logging it) — explicitly out of scope for this PRD per the batch's locked log-only instruction, but the natural next step once real log data exists (§9).
3. **Tune `_UNIT_WORD_MAX_LENGTH` (15)** if real notes surface a legitimate compound unit longer than 15 characters that gets truncated, or a false unit-match shorter than that gets over-captured.

No new environment variables, credentials, or console configuration are needed — this sub-project is prompt + pure Python only (PRD §8). No PRD §9 items are `[OPEN]` — the gate was clear; all 6 tasks above derive from `[RESOLVED]` decisions only.
</content>
