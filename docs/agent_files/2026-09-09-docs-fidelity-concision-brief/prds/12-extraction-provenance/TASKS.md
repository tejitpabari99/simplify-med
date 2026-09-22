# Tasks: Extraction Provenance

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config — `models/ledger.py`'s `Unit`), 02 (unitization-and-provenance — `SourceSpan`, `unitize()`, `provenance_for_pasted_text()`), 09 (input-transport — `JobInputPayload`, `upload_job_input`/`load_job_input`). All three have already landed in this repo (verified directly — see the line-number note below). Depended on by: 16/17 (technical/scientific documentation). No other sub-project in this batch reads `extraction_method`; PRD 10 (numeric-integrity) and 11 (omission-signal) are independent log-only signals living in the same files (`care_plan/pipeline.py`, `utils/constants.py`'s `LOG_EXTRA_KEYS`) — the merge seams are called out inline in Task 12 and Task 15 below. As of this writing, PRD 10's and PRD 11's own TASKS.md exist but neither's code has landed yet, so every file this PRD touches is still in its pre-10/11/12 state (confirmed by reading each file directly, not assumed).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file: `python -m pytest tests/services/test_unitizer.py -q` or `...::test_name -q`.
- Lint: `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6 — `extraction_method` never leaves the backend process boundary).
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given — later tasks depend on earlier ones landing first (each task states its dependency).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Line-number note**: verified directly against the real, current files at authoring time (PRDs 01-09 already landed): `models/provenance.py`'s `SourceSpan` class spans lines 22-38, `JobInputPayload` lines 41-54 (54 lines total). `models/ledger.py`'s `FactCategory` spans 35-44, `Unit` class 47-56 (81 lines total). `services/care_plan_input.py` (443 lines): `_get_extension` at line 73, `extract_pages_from_bytes` at 142, `resolve_uploaded_files` at 244; inside it, the per-file `SourceSpan`-building loop is at lines 347-357, `ext = _get_extension(filename)` at line 359 (immediately after, exactly as PRD §4.3 describes), the merge-candidate branch at 360-364. `services/unitizer.py` (76 lines total): `unitize()` at 17-59 (its `Unit(...)` call at 51-57), `provenance_for_pasted_text` at 62-76 (its `SourceSpan(...)` at line 76). `care_plan/pipeline.py` (972 lines): `_verify_ledger` at 234-282, `ground()` at 674-720 (`verified = _verify_ledger(drafts, units)` at line 714, `return verified` at line 720), `_format_units_for_prompt` at line 91 (confirmed unchanged, per PRD §4.10 — no task below touches it). `utils/constants.py`'s `Constants.Observability.LOG_EXTRA_KEYS` spans lines 164-171, currently exactly 26 entries, byte-for-byte matching the PRD §4.9 "before" snippet. Locate everything below by symbol/content, not by these line numbers alone — they are for orientation only.
- **Verified match between PRD snippets and real code**: every "Old" code block PRD §4.3/§4.4/§4.6/§4.8.2/§4.8.3/§4.9 shows matches the real current file byte-for-byte, confirmed by direct read — no deviation found in any of them.
- **One confirmed discrepancy in the PRD's own §7.1 table**: the table states `backend/tests/care_plan/test_pipeline_schema.py` has "6 direct `Unit(...)` calls." Direct grep/read of that file (334 lines, post PRD-04-landing) finds exactly **4**: lines 61, 62, 95, 113 (`test_ground_assigns_sequential_ids_from_array_position`'s two units, `test_ground_rejects_extra_key_on_fact`'s one, `test_ground_uses_long_form_token_budget_and_json_temperature`'s one). Task 14 below uses the real count (4), not the PRD table's stated count — this is a miscount in the PRD's prose, not a code mismatch; it does not change what needs doing, only how many lines get touched.
- **One additional file requiring a fix that the PRD's own §7.1/§7.3 tables don't enumerate**: `backend/tests/routes/test_jobs.py` (not listed in either table) contains a literal provenance dict assertion, confirmed via `grep -rn '"start_line"' tests/` (the only hit in the whole test suite): `test_post_text_job_uploads_payload_and_stores_uri` (lines 139-141) asserts `captured["provenance"] == [{"file": "text_input", "page": 1, "start_line": 0, "end_line": 1}]` — the pasted-text path, which will carry `extraction_method="pasted"` once Task 4 lands. PRD §7.3 flags this file category only as a caveat ("spot-check... before assuming zero changes needed"); direct verification confirms this one instance needs it. Task 11 below covers it. `tests/routes/test_jobs_e2e_scenarios.py`, the other file in that same §7.3 bullet, does NOT need a change — confirmed by grep: its only provenance-related assertions (lines 934-941) check `span.file == filename`, no literal dict.

---

### Task 1 — `backend/models/provenance.py`: `ExtractionMethod` + `SourceSpan.extraction_method`

   - Files: `backend/models/provenance.py`
   - Dependency: none (root of the breaking change).
   - Changes (PRD §4.1, §4.5): Add the type alias and the new required field, exactly as specified:
     ```python
     from typing import Literal

     ExtractionMethod = Literal["native", "ocr", "pasted"]
     ```
     placed above the `SourceSpan` class (after the existing `from pydantic import Field` / `from .base import JsonModel` imports). Add `extraction_method: ExtractionMethod` as a new field on `SourceSpan` (after `end_line`), with the docstring PRD §4.5 gives verbatim:
     ```python
         extraction_method: ExtractionMethod
         """How this span's text was produced -- "native" (PyPDF2/python-docx/
         BeautifulSoup/plain decode), "ocr" (Gemini vision transcription of an
         image, utils.image_ocr.extract_text_from_image), or "pasted" (typed or
         pasted directly by the user, no extraction step at all). A TRIAGE tag,
         not a confidence score (PRD 12 SS1): it records how the text was
         produced, never whether that production was accurate. Granularity is
         effectively per-file today (PRD 12 SS4.2 -- no per-page OCR fallback
         exists for PDFs), but lives on the per-(file, page) SourceSpan rather
         than a new per-file structure so a future per-page fallback would not
         require another schema change."""
     ```
     No default value. Do **not** touch `JobInputPayload` in this same file — it needs no field change (§4.5's last paragraph: `extraction_method` rides along automatically inside each serialized `SourceSpan`).
   - **Known, accepted consequence**: this task makes the test suite RED. Every existing `SourceSpan(...)` construction that doesn't pass `extraction_method` now raises `pydantic.ValidationError` for a missing required field — both production call sites (`services/care_plan_input.py:353`, `services/unitizer.py:76`) and every test fixture in `tests/models/test_provenance.py`, `tests/services/test_unitizer.py`, `tests/services/test_care_plan_input.py`. This is expected and necessary (§9 `[RESOLVED]`: no default, matching every other field on `SourceSpan`) — full green is restored incrementally by Tasks 3-4 (production) and Tasks 7, 9-11 (tests), confirmed by Task 17.
   - Acceptance criteria:
     - `python -c "from models.provenance import ExtractionMethod, SourceSpan; import typing; assert typing.get_args(ExtractionMethod) == ('native', 'ocr', 'pasted')"` (from `backend/`) succeeds.
     - `python -c "from models.provenance import SourceSpan; SourceSpan(file='f', page=1, start_line=0, end_line=1)"` raises `pydantic.ValidationError` (proves no default).
     - `python -c "from models.provenance import SourceSpan; SourceSpan(file='f', page=1, start_line=0, end_line=1, extraction_method='native')"` succeeds; the same call with `extraction_method='scanned'` raises `ValidationError`.
     - `grep -c "extraction_method" backend/models/provenance.py` returns at least 2 (the type alias + the field).
     - `python -m pytest tests/models/test_provenance.py -q` (from `backend/`) — expected to FAIL at this point (fixed by Task 7); do not attempt to fix it in this task.

### Task 2 — `backend/models/ledger.py`: `Unit.extraction_method`

   - Files: `backend/models/ledger.py`
   - Dependency: land after Task 1 (imports `ExtractionMethod` from `.provenance`).
   - Changes (PRD §4.6, model portion only — `unitize()`'s threading is Task 5): Add one import and one field:
     ```python
     from .provenance import ExtractionMethod
     ```
     (new dependency direction — `ledger.py` did not previously import from `provenance.py`; not a cycle, since `provenance.py` imports only from `.base`.) Add `extraction_method: ExtractionMethod` as the last field on `Unit` (after `text`):
     ```python
     class Unit(JsonModel):
         """One deterministically-numbered span of source text. Built by the
         unitizer (02), never by an LLM. `id` is the only handle the grounding
         LLM ever sees or cites. `extraction_method` is copied verbatim from
         the SourceSpan that produced this Unit (services.unitizer.unitize) --
         never inferred, re-derived, or defaulted here. See
         models.provenance.SourceSpan.extraction_method and PRD 12 for the
         full design; this is a pure carrier field on Unit, exactly like
         `file`/`page` already are."""

         id: int
         file: str
         page: int
         line: int
         text: str
         extraction_method: ExtractionMethod
     ```
     No default value. Do not touch `Fact`, `FactCategory`, or `quote_for` in this same file.
   - **Known, accepted consequence**: deepens the existing red state from Task 1. Every existing `Unit(...)` construction without `extraction_method` now also raises `ValidationError` — production (`services/unitizer.py`'s `unitize()`, line 51) and tests (`tests/models/test_ledger.py`, `tests/care_plan/test_pipeline_grounding.py`, `tests/care_plan/test_pipeline_schema.py`). Restored by Task 5 (production) and Tasks 8, 13-14 (tests), confirmed by Task 17.
   - Acceptance criteria:
     - `python -c "from models.ledger import Unit; Unit(id=1, file='f', page=1, line=1, text='x')"` raises `ValidationError`.
     - `python -c "from models.ledger import Unit; Unit(id=1, file='f', page=1, line=1, text='x', extraction_method='native')"` succeeds.
     - `python -c "from models.ledger import Unit; import inspect; assert 'extraction_method' in Unit.model_fields"` succeeds.
     - `grep -n "from .provenance import ExtractionMethod" backend/models/ledger.py` returns exactly one hit.
     - `python -m pytest tests/models/test_ledger.py tests/care_plan/test_pipeline_grounding.py tests/care_plan/test_pipeline_schema.py -q` — expected to FAIL at this point (fixed by Tasks 8, 13, 14); do not attempt to fix here.

### Task 3 — Producer 1: `backend/services/care_plan_input.py::resolve_uploaded_files`

   - Files: `backend/services/care_plan_input.py`
   - Dependency: land after Task 1.
   - Changes (PRD §4.3): Add the helper function (near the top of the file, alongside `_get_extension`):
     ```python
     def _extraction_method_for_ext(ext: str) -> ExtractionMethod:
         """Which extraction path backend/services/care_plan_input.py's own
         extract_pages_from_bytes dispatches `ext` to -- OCR for every image
         extension (extract_text_from_image, Gemini vision), native for
         everything else (PyPDF2 for PDF, python-docx for DOCX, BeautifulSoup
         for HTML, a plain decode for TXT). Mirrors extract_pages_from_bytes's
         own dispatch exactly rather than re-deriving it -- if that function's
         branches ever change, this one-line mapping is the only other place
         that needs to change with it."""
         return "ocr" if ext in Constants.Uploads.IMAGE_EXTENSIONS else "native"
     ```
     Add `from models.provenance import SourceSpan, JobInputPayload, ExtractionMethod` (extend the existing `from models.provenance import SourceSpan, JobInputPayload` import line at the top of the file to also import `ExtractionMethod`).

     In `resolve_uploaded_files`'s per-file loop (lines 347-364 today), move `ext = _get_extension(filename)` from its current position (line 359, after the span-building block) to immediately after `filenames.append(filename)` (line 347), and use it to compute `extraction_method` once per file before the per-page span loop:

     Old (lines 347-364, reproduced verbatim from the actual file):
     ```python
             filenames.append(filename)
             for page_num, page_text in pages:
                 page_text = page_text.strip()
                 if not page_text:
                     continue
                 page_line_count = len(page_text.split("\n"))
                 start = global_line_count
                 end = start + page_line_count - 1
                 provenance.append(SourceSpan(file=filename, page=page_num, start_line=start, end_line=end))
                 text_parts.append(page_text)
                 global_line_count = end + 1

             ext = _get_extension(filename)
             if ext in {"pdf", "txt"} or ext in Constants.Uploads.IMAGE_EXTENSIONS:
                 merge_candidates.append((file_bytes, filename))
             elif ext in {"docx", "html", "htm"} and real_content:
                 merge_candidates.append(
                     (extracted_text.encode("utf-8"), text_artifact_filename(filename))
                 )
     ```
     New:
     ```python
             filenames.append(filename)
             ext = _get_extension(filename)
             extraction_method = _extraction_method_for_ext(ext)
             for page_num, page_text in pages:
                 page_text = page_text.strip()
                 if not page_text:
                     continue
                 page_line_count = len(page_text.split("\n"))
                 start = global_line_count
                 end = start + page_line_count - 1
                 provenance.append(SourceSpan(
                     file=filename, page=page_num, start_line=start, end_line=end,
                     extraction_method=extraction_method,
                 ))
                 text_parts.append(page_text)
                 global_line_count = end + 1

             if ext in {"pdf", "txt"} or ext in Constants.Uploads.IMAGE_EXTENSIONS:
                 merge_candidates.append((file_bytes, filename))
             elif ext in {"docx", "html", "htm"} and real_content:
                 merge_candidates.append(
                     (extracted_text.encode("utf-8"), text_artifact_filename(filename))
                 )
     ```
   - This fixes the file's one production `SourceSpan(...)` call site. The suite remains RED after this task (the other production site in `services/unitizer.py`, plus all test fixtures, are still unfixed) — do not attempt to fix them here.
   - Acceptance criteria:
     - `grep -n "_extraction_method_for_ext" backend/services/care_plan_input.py` shows the function definition plus its one call site inside `resolve_uploaded_files`.
     - `_extraction_method_for_ext("png")`, `("jpg")`, `("jpeg")`, `("webp")`, `("heic")` each return `"ocr"`; `("pdf")`, `("txt")`, `("docx")`, `("html")`, `("htm")` each return `"native"`.
     - `grep -c "ext = _get_extension(filename)" backend/services/care_plan_input.py` returns 1 inside `resolve_uploaded_files` at the new (earlier) position — confirm via `grep -n` that it now appears before, not after, the `provenance.append(SourceSpan(...))` line.
     - A single-file, single-page PDF upload through `resolve_uploaded_files` (real invocation, no other production breakage in this file to route around) produces a `SourceSpan` with `extraction_method == "native"`; an image upload produces one with `extraction_method == "ocr"` — both are exercised once fixtures are updated in Task 10.

### Task 4 — Producer 2: `backend/services/unitizer.py::provenance_for_pasted_text`

   - Files: `backend/services/unitizer.py`
   - Dependency: land after Task 1.
   - Changes (PRD §4.4): the simpler producer — always exactly one method, no branching.

     Old (line 76, reproduced verbatim):
     ```python
         return [SourceSpan(file=file, page=1, start_line=0, end_line=line_count - 1)]
     ```
     New:
     ```python
         return [SourceSpan(
             file=file, page=1, start_line=0, end_line=line_count - 1,
             extraction_method="pasted",
         )]
     ```
   - This fixes this file's `provenance_for_pasted_text` production call site. `unitize()`'s own `Unit(...)` call (line 51) is untouched here — that is Task 5, kept separate per PRD §4.6's own note ("kept as a separate diff here so the 'pure copy, no inference' change reads on its own"). The suite remains RED after this task.
   - Acceptance criteria:
     - `provenance_for_pasted_text("a\nb")` returns `[SourceSpan(file="text_input", page=1, start_line=0, end_line=1, extraction_method="pasted")]`.
     - `provenance_for_pasted_text("")` still returns `[]` (unchanged early-return path).
     - `grep -n 'extraction_method="pasted"' backend/services/unitizer.py` returns exactly one hit.

### Task 5 — `backend/services/unitizer.py::unitize()`: pure copy-through of `extraction_method`

   - Files: `backend/services/unitizer.py`
   - Dependency: land after Task 2 (needs `Unit.extraction_method` to exist) and Task 4 (same file, sequential commit).
   - Changes (PRD §4.6, threading): the pure copy, no inference.

     Old (lines 51-57, reproduced verbatim):
     ```python
             units.append(Unit(
                 id=next_id,
                 file=span.file,
                 page=span.page,
                 line=offset + 1,
                 text=line_text,
             ))
     ```
     New:
     ```python
             units.append(Unit(
                 id=next_id,
                 file=span.file,
                 page=span.page,
                 line=offset + 1,
                 text=line_text,
                 extraction_method=span.extraction_method,
             ))
     ```
   - After this task, **all production code paths are fully consistent** — both producers (Tasks 3, 4) and the one consumer-side construction (`unitize()`) always populate `extraction_method`. The test suite is still RED, but only because test fixtures haven't been updated yet (Tasks 7-11, 13-14) — no further production code changes remain in this PRD's scope other than the additive logging in Task 6 and Task 12.
   - Acceptance criteria:
     - `grep -n "extraction_method=span.extraction_method" backend/services/unitizer.py` returns exactly one hit, inside `unitize()`.
     - A manual call `unitize("a", [SourceSpan(file="f", page=1, start_line=0, end_line=0, extraction_method="ocr")])` returns a `Unit` with `extraction_method == "ocr"`.
     - `python -c "import ast; ..."` not required — this is provable directly by the test above and by Task 9's permanent tests.

### Task 6 — `backend/services/unitizer.py`: `_log_extraction_signal` unit-level aggregate

   - Files: `backend/services/unitizer.py`
   - Dependency: land after Task 5.
   - Changes (PRD §4.8.1): purely additive — does not change red/green status, adds new observability.
     ```python
     import logging
     from collections import Counter
     ```
     (add these two imports at the top of the file, alongside the existing `from __future__ import annotations` / `from models.ledger import Unit` / `from models.provenance import SourceSpan` imports)
     ```python
     logger = logging.getLogger(__name__)
     ```
     Add the call `_log_extraction_signal(units)` as the last statement in `unitize()`, immediately before `return units`, and add the new function below `unitize()`:
     ```python
         _log_extraction_signal(units)
         return units


     def _log_extraction_signal(units: list[Unit]) -> None:
         """One INFO-level, per-run aggregate of how many units rest on which
         extraction method -- the earliest point this is fully known, before
         grounding (or any LLM call) has run at all. Log-only (PRD 12 SS3): does
         not affect `units` or anything downstream. No-op for an empty list
         (a job with zero units never reaches grounding anyway -- routes/
         worker.py's own MIN_MEANINGFUL_CONTENT_CHARS floor fails it first --
         so an aggregate over zero units would be pure noise, not signal)."""
         if not units:
             return
         counts = Counter(u.extraction_method for u in units)
         total = len(units)
         ocr = counts.get("ocr", 0)
         logger.info(
             "unitize: %d units (native=%d, ocr=%d, pasted=%d)",
             total, counts.get("native", 0), ocr, counts.get("pasted", 0),
             extra={"extraction_signal": {
                 "total": total,
                 "native": counts.get("native", 0),
                 "ocr": ocr,
                 "pasted": counts.get("pasted", 0),
                 "ocr_rate": ocr / total,
             }},
         )
     ```
     Also add one sentence to `unitize()`'s existing docstring noting the new logging side-effect (PRD §4.8.1's suggested addition): "Logs one INFO-level aggregate of `extraction_method` counts across the emitted units before returning -- log-only, never affects the returned list."
   - Acceptance criteria:
     - `python -c "from services.unitizer import _log_extraction_signal"` (from `backend/`) succeeds.
     - Calling `unitize(...)` on a nonempty provenance list emits exactly one `logger.info` record from `services.unitizer` (verified via `caplog` in Task 9).
     - `unitize("", [])` (empty units) emits zero records from `services.unitizer`.
     - Permanent test coverage lands in Task 9.

### Task 7 — `backend/tests/models/test_provenance.py`: fixture fix + new tests

   - Files: `backend/tests/models/test_provenance.py`
   - Dependency: land after Task 1.
   - Changes (PRD §7.1, table row 1):
     - Add `extraction_method="native"` to the `_span()` helper's default `fields` dict (line 10: `dict(file="f.pdf", page=1, start_line=0, end_line=3)` becomes `dict(file="f.pdf", page=1, start_line=0, end_line=3, extraction_method="native")`) — fixes every test using `_span(...)` in one place (`test_source_span_round_trips_through_dict`, both calls inside `test_job_input_payload_round_trips_through_to_dict_from_dict`).
     - Add `extraction_method="native"` to the direct call in `test_source_span_rejects_unknown_field` (line 23): `SourceSpan(file="f", page=1, start_line=0, end_line=1, extraction_method="native", extra="x")` — so the test asserts what it claims (rejecting an unknown key on an otherwise-valid span), not incidentally also rejecting a missing field.
     - Add `test_source_span_requires_extraction_method`: `with pytest.raises(ValidationError): SourceSpan(file="f", page=1, start_line=0, end_line=1)` (omit the field from an otherwise-valid call).
     - Add `test_source_span_rejects_invalid_extraction_method`: `with pytest.raises(ValidationError): _span(extraction_method="scanned")`.
     - Add a one-line comment on `test_job_input_payload_round_trips_through_to_dict_from_dict` noting it now exercises `extraction_method`'s round-trip through `JobInputPayload` too (no code change needed — it already goes through `_span()`).
   - Acceptance criteria: `python -m pytest tests/models/test_provenance.py -q` (from `backend/`) passes in full, including the 2 new tests; `grep -c 'extraction_method="native"' backend/tests/models/test_provenance.py` returns at least 2.

### Task 8 — `backend/tests/models/test_ledger.py`: fixture fix + new tests

   - Files: `backend/tests/models/test_ledger.py`
   - Dependency: land after Task 2.
   - Changes (PRD §7.1, table row 4):
     - Add `extraction_method="native"` to the `_unit()` helper's default `fields` dict (line 10: `dict(id=1, file="note.pdf", page=1, line=1, text="hello world")` becomes `dict(id=1, file="note.pdf", page=1, line=1, text="hello world", extraction_method="native")`) — fixes `test_unit_round_trips_through_dict` and both `_unit(...)` calls inside `test_quote_for_raises_key_error_on_unknown_unit_id`.
     - Add `extraction_method="native"` to the 2 direct `Unit(...)` calls: `test_quote_for_returns_unit_text_slice` (line 84) and (there is no second direct call beyond this one and the `_unit()` helper — confirmed by direct read; the PRD's table phrasing "2 direct calls" refers to this one plus the module using `Unit(**fields)` inside the helper, already covered above).
     - Add `test_unit_requires_extraction_method`: `with pytest.raises(ValidationError): Unit(id=1, file="f", page=1, line=1, text="x")`.
     - Add `test_unit_rejects_invalid_extraction_method`: `with pytest.raises(ValidationError): _unit(extraction_method="scanned")`.
   - Acceptance criteria: `python -m pytest tests/models/test_ledger.py -q` (from `backend/`) passes in full, including the 2 new tests.

### Task 9 — `backend/tests/services/test_unitizer.py`: fixture fix + new tests

   - Files: `backend/tests/services/test_unitizer.py`
   - Dependency: land after Task 5 (production copy-through) and Task 6 (`_log_extraction_signal`).
   - Changes (PRD §7.1 table row 2, §7.2): This file has no shared helper today (confirmed) — introduce one to make this and any future field addition a one-line change:
     ```python
     def _span(**overrides) -> SourceSpan:
         fields = dict(file="f", page=1, start_line=0, end_line=1, extraction_method="native")
         fields.update(overrides)
         return SourceSpan(**fields)
     ```
     Replace each of the file's 9 direct `SourceSpan(...)` calls (lines 9, 21, 32, 33, 48, 49, 64, 73, 83) with either `_span(...)` (overriding only the fields that differ from the default) or by adding `extraction_method="native"` directly — either is acceptable as long as every construction passes the field. Specifically:
     - `test_provenance_for_pasted_text_single_span_covers_whole_text`'s expected literal (line 83) needs `extraction_method="pasted"` added to match `provenance_for_pasted_text`'s new output (Task 4): `SourceSpan(file="text_input", page=1, start_line=0, end_line=1, extraction_method="pasted")`.
     - Every other call site (lines 9, 21, 32, 33, 48, 49, 64, 73) should use `extraction_method="native"` — none of these tests are about extraction method, so "native" is the correct default value for all of them.
     - Extend at least one assertion per existing `unitize(...)`-calling test (that isn't already about extraction_method) to additionally assert `u.extraction_method == "native"` on the resulting units, to prove the copy-through actually happened, not just that construction succeeded.
     - Add `test_unitize_copies_extraction_method_from_span_verbatim`: one span with `extraction_method="ocr"`, assert every emitted unit's `extraction_method == "ocr"`.
     - Add `test_unitize_preserves_distinct_extraction_methods_across_mixed_spans`: three spans in one `provenance` list — one `extraction_method="native"`, one `"ocr"`, one `"pasted"` — assert each emitted unit's `extraction_method` matches its own span's, not some other span's (the mixed-upload case, §4.2).
     - Add `test_unitize_logs_extraction_signal_aggregate` (§7.2): build a `provenance` list with 2 native spans and 1 ocr span producing, e.g., 5 native units and 2 ocr units; call `unitize(...)` inside `caplog.at_level(logging.INFO, logger="services.unitizer")`; assert the emitted record's `extra["extraction_signal"]` (accessible as `record.extraction_signal`) equals `{"total": 7, "native": 5, "ocr": 2, "pasted": 0, "ocr_rate": 2/7}`.
     - Add `test_unitize_empty_units_list_logs_nothing`: `unitize("", [])` (or provenance producing zero units) → `caplog.records` from `services.unitizer` is empty.
     - Add the top-of-file imports needed: `import logging` (for `caplog.at_level`); `SourceSpan` is already imported.
   - Acceptance criteria: `python -m pytest tests/services/test_unitizer.py -q` (from `backend/`) passes in full, including all new tests above; `grep -c "SourceSpan(" backend/tests/services/test_unitizer.py` shows every remaining direct construction (inside `_span`, plus any literal comparisons) carries `extraction_method`.

### Task 10 — `backend/tests/services/test_care_plan_input.py`: fixture fix + new mixed-file test

   - Files: `backend/tests/services/test_care_plan_input.py`
   - Dependency: land after Task 3.
   - Changes (PRD §7.1, table row 3):
     - Add `extraction_method="native"` to both direct `SourceSpan(...)` calls (both `.txt`-file fixtures): `test_upload_job_input_writes_json_with_text_and_provenance` (line 152) and `test_load_job_input_happy_path` (line 183).
     - Add `test_resolve_uploaded_files_multi_file_mixed_native_and_ocr_tags_spans_correctly`: reuse this file's existing `_FakeUpload` / `extract_text_from_image`-mocking pattern (see `test_resolve_uploaded_files_image_becomes_raw_merge_candidate`, lines 236-245) — one `.txt` upload plus one image upload (`_ONE_PX_PNG`) in the same `_resolve([...])` call. Assert the `.txt` file's span(s) have `extraction_method == "native"` and the image file's span has `extraction_method == "ocr"`.
   - Acceptance criteria: `python -m pytest tests/services/test_care_plan_input.py -q` (from `backend/`) passes in full, including the new mixed-file test.

### Task 11 — `backend/tests/routes/test_jobs.py`: fix literal provenance dict assertion

   - Files: `backend/tests/routes/test_jobs.py`
   - Dependency: land after Task 4 (needs `provenance_for_pasted_text` to actually emit `"pasted"`).
   - Changes (found by direct verification — not enumerated in the PRD's own §7.1/§7.3 tables, see the header note above): `test_post_text_job_uploads_payload_and_stores_uri` (lines 139-141) currently asserts:
     ```python
         assert captured["provenance"] == [
             {"file": "text_input", "page": 1, "start_line": 0, "end_line": 1}
         ]
     ```
     Update to:
     ```python
         assert captured["provenance"] == [
             {"file": "text_input", "page": 1, "start_line": 0, "end_line": 1, "extraction_method": "pasted"}
         ]
     ```
     No other line in this file needs a change (confirmed: `grep -n '"start_line"' backend/tests/routes/test_jobs.py` shows exactly this one hit).
   - Acceptance criteria: `python -m pytest tests/routes/test_jobs.py -q` (from `backend/`) passes in full; `grep -n '"extraction_method": "pasted"' backend/tests/routes/test_jobs.py` returns exactly one hit.

### Task 12 — `backend/care_plan/pipeline.py`: fact-level aggregate + extraction_method on drop warnings

   - Files: `backend/care_plan/pipeline.py`
   - Dependency: land after Task 2 (needs `Unit.extraction_method` to exist).
   - Changes, part A (PRD §4.8.2) — new function + call site inside `ground()`, immediately after the existing `_verify_ledger` call and before the existing empty-ledger check:

     Old (lines 714-720, reproduced verbatim):
     ```python
             verified = _verify_ledger(drafts, units)
             if not verified:
                 raise SimplifyError(
                     ErrorCode.PIPELINE_VALIDATION_FAILED,
                     detail="grounding produced zero verifiable facts",
                 )
             return verified
     ```
     New:
     ```python
             verified = _verify_ledger(drafts, units)
             _log_grounding_extraction_signal(verified, {u.id: u for u in units})
             if not verified:
                 raise SimplifyError(
                     ErrorCode.PIPELINE_VALIDATION_FAILED,
                     detail="grounding produced zero verifiable facts",
                 )
             return verified
     ```
     Add the new function, placed alongside `_verify_ledger` (directly below it, before `_PROMPTS_DIR = ...`):
     ```python
     def _log_grounding_extraction_signal(facts: list[Fact], units_by_id: dict[int, Unit]) -> None:
         """One INFO-level, per-run aggregate of how many VERIFIED facts cite an
         OCR-extracted unit (PRD 12 SS4.8.2) -- log-only, mirrors 11's
         _log_coverage_summary in shape/placement (one aggregate call sitting
         next to the deterministic checks it summarizes, not inside them). No-op
         for an empty ledger -- ground() raises PIPELINE_VALIDATION_FAILED for
         that case immediately after this call anyway (SS4.5, unchanged), so
         logging a 0/0 aggregate right before a hard failure would be noise."""
         if not facts:
             return
         ocr = sum(1 for f in facts if units_by_id[f.unit_id].extraction_method == "ocr")
         total = len(facts)
         logger.info(
             "grounding: %d/%d verified facts cite an OCR-extracted unit",
             ocr, total,
             extra={"extraction_signal_facts": {
                 "total": total,
                 "ocr": ocr,
                 "ocr_rate": ocr / total,
             }},
         )
     ```
     `{u.id: u for u in units}` is recomputed here rather than plumbed out of `_verify_ledger` — keeps `_verify_ledger`'s signature/return type untouched.

     Changes, part B (PRD §4.8.3) — extend exactly two of `_verify_ledger`'s three existing per-fact drop warnings with `extraction_method`; the third (`unit is None`) is unchanged, since there is no unit to read a method from in that branch.

     Old (inside `_verify_ledger`, part of lines 234-282, reproduced verbatim):
     ```python
             if not _is_verbatim_quote(draft.quote, unit.text):
                 logger.warning(
                     "grounding: dropping fact citing unit_id=%d -- quote not found "
                     "verbatim in unit text (category=%s)", draft.unit_id, draft.category,
                 )
                 continue
             if not _is_informative_quote(draft.quote):
                 logger.warning(
                     "grounding: dropping fact citing unit_id=%d -- quote fails "
                     "informativeness floor (category=%s)", draft.unit_id, draft.category,
                 )
                 continue
     ```
     New:
     ```python
             if not _is_verbatim_quote(draft.quote, unit.text):
                 logger.warning(
                     "grounding: dropping fact citing unit_id=%d -- quote not found "
                     "verbatim in unit text (category=%s, extraction_method=%s)",
                     draft.unit_id, draft.category, unit.extraction_method,
                 )
                 continue
             if not _is_informative_quote(draft.quote):
                 logger.warning(
                     "grounding: dropping fact citing unit_id=%d -- quote fails "
                     "informativeness floor (category=%s, extraction_method=%s)",
                     draft.unit_id, draft.category, unit.extraction_method,
                 )
                 continue
     ```
     This is strictly additive to the log line's diagnostic content — no behavior change, nothing about which facts get dropped changes. Do not touch the third (`unit is None`) warning, `_is_verbatim_quote`, `_is_informative_quote`, `_locate_quote_offsets`, `_format_units_for_prompt` (explicitly unchanged per §4.10), or any prompt template.
   - The test suite for this file (`tests/care_plan/test_pipeline_grounding.py`, `tests/care_plan/test_pipeline_schema.py`) is already RED from Task 2 (missing `extraction_method` on their `Unit(...)` fixtures) — this task adds no *new* breakage; it lands the code these two files' Task 13/14 fixture fixes and new tests depend on.
   - Acceptance criteria:
     - `grep -n "_log_grounding_extraction_signal(verified" backend/care_plan/pipeline.py` shows it as the line immediately after `verified = _verify_ledger(drafts, units)` and before `if not verified:`.
     - `grep -c "extraction_method=%s" backend/care_plan/pipeline.py` returns 2 (the two extended warnings).
     - `grep -c "unit is None" backend/care_plan/pipeline.py` shows that branch's warning is unchanged (no `extraction_method` added there).
     - Permanent test coverage lands in Task 13.

### Task 13 — `backend/tests/care_plan/test_pipeline_grounding.py`: fixture fix + new tests

   - Files: `backend/tests/care_plan/test_pipeline_grounding.py`
   - Dependency: land after Task 2 (model) and Task 12 (pipeline.py code this file's new tests exercise).
   - Changes (PRD §7.1, table row 5): This file has 25 direct `Unit(...)` calls (confirmed by grep: lines 31, 32, 33, 48, 49, 50, 61, 62, 74, 75, 275, 291, 312, 330, 355, 356, 357, 376, 377, 378, 407, 437, 438, 463, 487), no shared helper today.
     - Introduce a `_unit(**overrides)` helper at the top of the file (mirroring `test_ledger.py`/`test_provenance.py`'s pattern):
       ```python
       def _unit(**overrides) -> Unit:
           fields = dict(id=1, file="note.pdf", page=1, line=1, text="hello", extraction_method="native")
           fields.update(overrides)
           return Unit(**fields)
       ```
     - Add `extraction_method="native"` to all 25 existing direct `Unit(...)` calls (every fixture in this file represents a PDF-note scenario — none currently test OCR/pasted behavior, so `"native"` is correct for every existing case). Using `_unit(...)` for some/all of them is acceptable; a literal `extraction_method="native"` added in place is equally acceptable — the requirement is that all 25 construction sites pass the field.
     - Add `test_ground_logs_extraction_signal_aggregate_for_verified_facts`: mixed native/ocr units (e.g. 2 native, 1 ocr, all cited by verified facts); call `pipeline.ground(units, [])` inside `caplog.at_level(logging.INFO, logger="care_plan.pipeline")`; assert the `logger.info` call's `extra["extraction_signal_facts"]` dict (accessible as `record.extraction_signal_facts`) has the correct `total`/`ocr`/`ocr_rate`.
     - Add `test_ground_extraction_signal_omits_log_when_zero_facts_verified`: all drafts fail verification → `SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED)` raised, and no record with an `extraction_signal_facts` attribute is emitted (the `if not facts: return` guard in `_log_grounding_extraction_signal`).
     - Add `test_verify_ledger_drop_warning_includes_extraction_method_for_ocr_unit`: a unit with `extraction_method="ocr"` whose draft fails `_is_verbatim_quote`; assert (via `caplog`) the resulting `logger.warning` message contains `"extraction_method=ocr"`.
     - Add `import logging` at the top if not already present (check first — `caplog.at_level` needs it).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_grounding.py -q` (from `backend/`) passes in full, including the 3 new tests; `grep -c "extraction_method" backend/tests/care_plan/test_pipeline_grounding.py` returns at least 25.

### Task 14 — `backend/tests/care_plan/test_pipeline_schema.py`: fixture fix

   - Files: `backend/tests/care_plan/test_pipeline_schema.py`
   - Dependency: land after Task 2.
   - Changes (PRD §7.1, table row 6 — **using the real count of 4, not the PRD table's stated 6; see the header note above**): Add `extraction_method="native"` to all 4 direct `Unit(...)` calls: line 61, 62 (`test_ground_assigns_sequential_ids_from_array_position`'s two units), line 95 (`test_ground_rejects_extra_key_on_fact`), line 113 (`test_ground_uses_long_form_token_budget_and_json_temperature`). Same reasoning as Task 13 — these are all native-PDF fixtures unrelated to this PRD's own subject matter, so `"native"` is correct for all four. No new tests are required in this file (this PRD adds no new schema-boundary behavior to `assemble_and_render`/`review`/`correct` — those are PRD 04/05's territory, already covered by their own tests in this same file, untouched here).
   - Acceptance criteria: `python -m pytest tests/care_plan/test_pipeline_schema.py -q` (from `backend/`) passes in full; `grep -c 'extraction_method="native"' backend/tests/care_plan/test_pipeline_schema.py` returns 4.

### Task 15 — `backend/utils/constants.py`: new `LOG_EXTRA_KEYS` entries

   - Files: `backend/utils/constants.py`
   - Dependency: land after Task 6 and Task 12 (the two `extra={...}` call sites this whitelists).
   - Changes (PRD §4.9): Add exactly two new entries to the end of the existing `LOG_EXTRA_KEYS` list (currently 26 entries, lines 164-171):
     ```python
     LOG_EXTRA_KEYS: list[str] = [
         "user_id", "function", "care_plan_version", "grading_version", "input_version",
         "operation", "metric", "metric_type", "duration_ms", "success", "outcome",
         "step_name", "status", "http_method", "http_path", "http_status",
         "http_status_code", "total_duration_ms", "saved_id", "input_chars",
         "error", "labels", "duration_ms_observed", "OpOutcome",
         "service", "environment",
         "extraction_signal", "extraction_signal_facts",
     ]
     ```
     Do not reorder or remove any existing entry. This is the whole edit.
     **Merge seam with PRD 10/11**: PRD 11 independently appends `"coverage_signal"` to this same list; PRD 10 adds no entry here (confirmed by reading PRD 10 §4.4). Neither PRD 10 nor 11's code has landed as of this writing (only their TASKS.md files exist) — whichever of 10/11/12 lands first in this list only needs to append its own key(s); whoever lands second/third does the same, without needing to touch what a prior one added. Do not assert an exact final list length in this task's acceptance criteria for that reason — assert membership and order-preservation of the existing 26, not a fixed total count, since that total depends on whether 10/11 have landed yet when this task actually runs.
   - Acceptance criteria:
     - `python -c "from utils.constants import Constants; assert 'extraction_signal' in Constants.Observability.LOG_EXTRA_KEYS; assert 'extraction_signal_facts' in Constants.Observability.LOG_EXTRA_KEYS"` (from `backend/`) succeeds.
     - `grep -c '"extraction_signal"' backend/utils/constants.py` returns 1; `grep -c '"extraction_signal_facts"' backend/utils/constants.py` returns 1.
     - Every one of the original 26 entries is still present, in its original relative order (diff should show only new lines appended, none removed or reordered).
     - Permanent test coverage lands in Task 16.

### Task 16 — `backend/tests/utils/test_constants.py`: assert the two new keys

   - Files: `backend/tests/utils/test_constants.py`
   - Dependency: land after Task 15.
   - Changes (PRD §7.3): Extend `test_observability_namespace` (or add a new test alongside it) mirroring the file's existing `assert "user_id" in Constants.Observability.LOG_EXTRA_KEYS` pattern:
     ```python
     assert "extraction_signal" in Constants.Observability.LOG_EXTRA_KEYS
     assert "extraction_signal_facts" in Constants.Observability.LOG_EXTRA_KEYS
     ```
   - Acceptance criteria: `python -m pytest tests/utils/test_constants.py -q` (from `backend/`) passes in full.

### Task 17 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-16.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors. This PRD's changes are the only ones landing in this pass (PRD 10/11's code has not landed as of this task list), so a clean run here fully closes the breaking-change gap opened in Task 1.
     - `grep -rn "SourceSpan(" backend --include=*.py | grep -v "extraction_method"` returns zero hits (every remaining construction — including inside any `_span()` helper — passes the field; a helper's own single definition line naturally won't contain the literal string `extraction_method=` if it builds the dict separately, so also manually confirm each helper's `fields = dict(...)` line includes it).
     - `grep -rn "Unit(" backend --include=*.py | grep -v "class Unit\|extraction_method"` returns zero hits outside of `_unit()`-style helper definitions (spot-check those helpers' `fields = dict(...)` lines directly for `extraction_method`).
     - `python -c "from models.provenance import SourceSpan; from models.ledger import Unit; assert 'extraction_method' in SourceSpan.model_fields; assert 'extraction_method' in Unit.model_fields"` (from `backend/`) succeeds.
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched (`models/provenance.py`, `models/ledger.py`, `services/care_plan_input.py`, `services/unitizer.py`, `care_plan/pipeline.py`, `utils/constants.py`, and the 8 test files listed in Tasks 7-11, 13-14, 16).
     - `backend/care_plan/prompts/` directory is unchanged — no prompt file added, removed, or edited by this PRD (§3, §4.10): `git status` (or equivalent) shows no diff under that directory.

---

## Summary of what requires you (not a dev agent)

Per PRD §8, nothing here is blocking; two items are worth your awareness, not your action:

1. **Log volume.** This adds two `logger.info` calls per successful job run (one in `unitize()`, one in `ground()`) plus, occasionally, an extra field on two pre-existing `logger.warning` calls. Negligible relative to this pipeline's existing per-run log volume, but a permanent, always-on addition to every run's Cloud Logging footprint, not sampled or opt-in.
2. **Optional real-world smoke test** (not required for this PRD to be considered complete — no automated clinical-fidelity check is in scope anywhere in this initiative): once this PRD's code is live, run a real end-to-end job via ngrok + pm2 (`SERVICE_MODE=combined`) with a photographed document, and confirm in the local logs that `extraction_signal`/`extraction_signal_facts` show a nonzero `ocr`/`ocr_rate`, and that a native-only upload in the same session shows all-zero `ocr` counts. This is a smoke test of the wiring, not of OCR accuracy.

No new environment variables, credentials, or console configuration are needed for this PRD — it is model/pure-Python + logging only (PRD §8).

No PRD §9 items are `[OPEN]` — the gate was clear; all 17 tasks above derive from `[RESOLVED]` decisions only.
