# Tasks: Unitization and Provenance

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — specifically `backend/models/ledger.py`'s `Unit` model. 01's own tasks are tracked in `prds/01-schema-and-config/TASKS.md` and are **not** duplicated here; land 01's Task 4 (creates `backend/models/ledger.py`) before Task 5 below, which imports `Unit` from it. Depended on by: 03 (grounding, cites `Unit.id`), 06 (pipeline-orchestration, wires this sub-project's output into the pipeline run).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/services/test_unitizer.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- No frontend changes in this PRD (§6, §3 Non-Goals) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Prerequisite check**: as of this writing, none of `backend/models/provenance.py`, `backend/services/unitizer.py`, or `backend/models/ledger.py` exist yet, and `backend/services/care_plan_input.py`/`backend/utils/pdf.py`/`backend/utils/misc.py`/`backend/models/input.py`/`backend/models/job.py`/`backend/utils/firebase.py` are all still in their PRD-"old" shape — every snippet below was verified against the actual current file contents. Before starting Task 5, confirm `python -c "from models.ledger import Unit"` (from `backend/`) succeeds — if it doesn't, PRD 01's Task 4 hasn't landed yet and must land first.

---

### Task 1 — New module `backend/models/provenance.py`: `SourceSpan`

   - Files: `backend/models/provenance.py` (new file)
   - Changes (PRD §4.3): Create the file with exactly the contract specified — module docstring and:
     ```python
     from __future__ import annotations

     from .base import JsonModel


     class SourceSpan(JsonModel):
         file: str
         page: int
         start_line: int
         end_line: int
     ```
     Use the full module/class docstrings given in PRD §4.3 (they document why this model is persisted to Firestore while `Unit`/`Fact` never are, and why `start_line`/`end_line` are 0-indexed while `Unit.line` is a separate, 1-indexed, page-relative convention — §9's two `[RESOLVED]` entries on placement and indexing). Do not place this inside `models/ledger.py` or `models/care_plan/` (§4.3, §9).
   - Acceptance criteria:
     - `python -c "from models.provenance import SourceSpan"` (from `backend/`) succeeds.
     - `SourceSpan(file="f.pdf", page=1, start_line=0, end_line=3)` constructs; `SourceSpan(file="f.pdf", page=1, start_line=0, end_line=3, extra="x")` raises `ValidationError` (inherited `extra="forbid"` from `JsonModel`).
     - Covered permanently by the new `test_provenance.py` in Task 13.

### Task 2 — `backend/utils/pdf.py`: replace `extract_text_from_pdf` with page-segmented `extract_pages_from_pdf`

   - Files: `backend/utils/pdf.py`
   - Changes (PRD §4.4, §9 `[RESOLVED: deleted outright, not kept as a wrapper]`): Delete the current `extract_text_from_pdf` (lines 20-30) and replace it with:
     ```python
     def extract_pages_from_pdf(pdf_content: bytes) -> list[tuple[int, str]]:
         """Extract text from a PDF, segmented by page. Returns (page_number,
         page_text) pairs, 1-indexed in document order, for every page that
         yields non-empty extracted text -- a page with none (e.g. a scanned
         page with no text layer) is omitted, NOT renumbered: if page 2 of a
         3-page PDF is blank, this returns [(1, ...), (3, ...)], preserving the
         real page numbers so provenance built from this list points at the
         actual page a reader would count.

         Supersedes the old extract_text_from_pdf, which computed page_num
         internally, logged it at debug level, and then discarded it by joining
         every page into one flat string (brief brainstorm.v1.md §3.2). Page
         boundaries are the whole point of this function's return shape now --
         there is no longer a flat-string variant (see PRD 02 §9 on why the
         old flat-text function is deleted outright rather than kept as a
         thin wrapper).

         Note: a page whose extracted text is present but whitespace-only is
         also omitted (page_text.strip() check) -- the old code's `if
         page_text:` check on the *unstripped* string would have appended an
         empty entry to text_parts for such a page (visible only as an extra
         "\n\n" in the old flat output, otherwise harmless). This is a small,
         deliberate tightening: a whitespace-only page should not get its own
         SourceSpan any more than a whitespace-only TXT/DOCX/HTML file does
         (see extract_pages_from_bytes, PRD 02 §4.7).
         """
         reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
         pages: list[tuple[int, str]] = []
         for page_num, page in enumerate(reader.pages):
             page_text = page.extract_text()
             if page_text and page_text.strip():
                 pages.append((page_num + 1, page_text.strip()))
         total_chars = sum(len(t) for _, t in pages)
         logger.info(
             "pdf_extract: %d total chars from %d of %d pages",
             total_chars, len(pages), len(reader.pages),
         )
         return pages
     ```
     Leave `_txt_to_pdf`, `_image_to_pdf`, `_append_pdf`, and `merge_pdfs` byte-for-byte unchanged.
   - Acceptance criteria:
     - `grep -n "def extract_text_from_pdf" backend/utils/pdf.py` returns no hits; `grep -n "def extract_pages_from_pdf" backend/utils/pdf.py` returns one hit.
     - A 2-page PDF with real text on both pages: `extract_pages_from_pdf(pdf_bytes)` returns `[(1, "..."), (2, "...")]`.
     - A PDF with a genuinely blank page 2 of 3: returns `[(1, ...), (3, ...)]` (page 2 omitted, not renumbered).
     - Covered permanently in Task 11's rewritten `test_pdf.py`.

### Task 3 — `backend/utils/image_ocr.py`: raise OCR downscale ceiling 2048 → 4096

   - Files: `backend/utils/image_ocr.py`
   - Changes (PRD §4.5): Change line 12 from `_MAX_LONG_EDGE_PX = 2048` to `_MAX_LONG_EDGE_PX = 4096`. No other change in this file — `IMAGE_OCR_PROMPT` (in `utils/constants.py`, not this file) is explicitly left unchanged per the brief.
   - Acceptance criteria:
     - `python -c "from utils.image_ocr import _MAX_LONG_EDGE_PX; assert _MAX_LONG_EDGE_PX == 4096"` (from `backend/`) succeeds.
     - `python -m pytest tests/utils/test_image_ocr.py -q` (from `backend/`) still passes in full before Task 16 adds new tests (existing tests don't assert a specific ceiling value, per PRD §7.2).

### Task 4 — `backend/utils/misc.py`: delete `source_separator`

   - Files: `backend/utils/misc.py`
   - Changes (PRD §4.6, §9): Delete the function (currently lines 106-107):
     ```python
     def source_separator(filename: str) -> str:
         return f"\n\n--- Source: {filename} ---\n"
     ```
     No replacement, no deprecation shim. Leave the surrounding `# --- String formatting ---` comment header and `text_artifact_filename` untouched.
   - Dependency: land before or together with Task 8 (which removes the only caller); order between Task 4 and Task 8 doesn't matter as long as both land before Task 12's tests run, since an intermediate state where `care_plan_input.py` still imports the now-deleted `source_separator` would break imports. Landing them in the same commit, or Task 4 immediately before Task 8, is simplest.
   - Acceptance criteria:
     - `grep -rn "source_separator" backend --include=*.py` returns zero hits once Task 8 also lands (this task alone will transiently break `care_plan_input.py`'s import if landed as a separate commit before Task 8 — acceptable per PRD 01's own precedent of transient mid-pass invalidity, or land Tasks 4+8 as one commit).
     - `backend/tests/utils/test_misc.py` has and needs zero references to `source_separator` (confirmed already true, PRD §7.2).

### Task 5 — New module `backend/services/unitizer.py`: `unitize`, `provenance_for_pasted_text`

   - Files: `backend/services/unitizer.py` (new file)
   - Dependency: **requires PRD 01's `backend/models/ledger.py` (`Unit`) to already exist.** Also depends on Task 1 (`SourceSpan`) landing first.
   - Changes (PRD §4.8): Create the file with exactly:
     ```python
     """services/unitizer.py -- the deterministic unitizer (brainstorm.v1.md
     §3.2): turns already-extracted text plus its SourceSpan provenance into a
     numbered list[Unit], the only thing the grounding LLM call (03) ever
     cites.

     Pure, deterministic, and network-free by construction -- the same (text,
     provenance) pair always produces an identical unit list, which is what
     makes evidence citation by integer id reproducible (brief §3.2: "the
     model cites one integer... file and page are recovered by lookup").
     """
     from __future__ import annotations

     from models.ledger import Unit
     from models.provenance import SourceSpan


     def unitize(text: str, provenance: list[SourceSpan]) -> list[Unit]:
         """Split `text` into Units using the (file, page, start_line, end_line)
         boundaries in `provenance`.

         `provenance` must be in document order, and its spans' line ranges
         must partition [0, len(text.split("\\n"))) with no gaps or overlaps --
         guaranteed by construction when `provenance` comes from
         resolve_uploaded_files or provenance_for_pasted_text (see their
         docstrings and tests/services/test_unitizer.py). This function does
         NOT re-validate that invariant on the hot path; a span whose range
         runs past the end of `text`'s lines is handled defensively (the loop
         below simply stops early) rather than raising, matching this
         codebase's existing "belt-and-suspenders, don't crash the request"
         posture elsewhere in the input path.

         Blank/whitespace-only lines are dropped silently -- no Unit is created
         for them -- but they still occupy a slot in the global line count, so
         `Unit.line` (1-indexed, reset at each span) matches what a human
         counting lines in the original page/file would call that line.
         `Unit.id` is assigned only to emitted (non-blank) units, sequentially
         starting at 1, in (span order, then line order within a span) -- i.e.
         document reading order. Same (text, provenance) in -> same list[Unit]
         out, every time (unit IDs are stable and reproducible; see PRD 02 §7).
         """
         lines = text.split("\n")
         units: list[Unit] = []
         next_id = 1
         for span in provenance:
             for offset, global_idx in enumerate(range(span.start_line, span.end_line + 1)):
                 if global_idx >= len(lines):
                     break  # defensive: malformed provenance: stop rather than crash
                 line_text = lines[global_idx]
                 if not line_text.strip():
                     continue
                 units.append(Unit(
                     id=next_id,
                     file=span.file,
                     page=span.page,
                     line=offset + 1,
                     text=line_text,
                 ))
                 next_id += 1
         return units


     def provenance_for_pasted_text(text: str, *, file: str = "text_input") -> list[SourceSpan]:
         """Build the single-span provenance for pasted text (routes/jobs.py's
         text path -- no file at all, PRD 02 §4.2). `file="text_input"` matches
         the existing sentinel filename already used for pasted-text jobs
         (routes/jobs.py's input_source_filename, and utils.misc.
         derive_output_name's special-cased skip for that exact string) --
         reusing it means no new sentinel convention to keep in sync.

         Returns [] for empty text (no lines to span), consistent with an
         upload path that contributes no spans for a file with no usable text.
         """
         if not text:
             return []
         line_count = len(text.split("\n"))
         return [SourceSpan(file=file, page=1, start_line=0, end_line=line_count - 1)]
     ```
   - Acceptance criteria:
     - `python -c "from services.unitizer import unitize, provenance_for_pasted_text"` (from `backend/`) succeeds.
     - `unitize("a\n\nb", [SourceSpan(file="f", page=1, start_line=0, end_line=2)])` returns two `Unit`s with `id=1,line=1,text="a"` and `id=2,line=3,text="b"` (the blank middle line consumes a line slot but gets no unit).
     - `provenance_for_pasted_text("")` returns `[]`; `provenance_for_pasted_text("a\nb")` returns one `SourceSpan(file="text_input", page=1, start_line=0, end_line=1)`.
     - Fully covered by the new `test_unitizer.py` in Task 14.

### Task 6 — `backend/models/input.py`: add `ResolvedInput.provenance`

   - Files: `backend/models/input.py`
   - Dependency: land after Task 1.
   - Changes (PRD §4.9): Add `from .provenance import SourceSpan` to the imports (alongside the existing `from .base import JsonModel`). Add a new field to `ResolvedInput`, after `skipped_files`:
     ```python
     provenance: list[SourceSpan] = Field(default_factory=list)   # NEW
     ```
     `Field` is already imported from `pydantic`. No other field changes in this file.
   - Acceptance criteria:
     - `ResolvedInput(text="x", source_description="d", source_filename="f")` constructs with `provenance == []` (default applies since `resolve_uploaded_files` is the only production constructor today, per PRD §4.9, and Task 8 hasn't wired the explicit value in yet at this point in the sequence).
     - `python -c "from models.input import ResolvedInput"` (from `backend/`) succeeds.

### Task 7 — `backend/models/job.py`: add `JobDoc.input_provenance`

   - Files: `backend/models/job.py`
   - Dependency: land after Task 1.
   - Changes (PRD §4.10): Add `from .provenance import SourceSpan` to the imports. Add a new field to `JobDoc`, in the "Input provenance" section, after `input_pdf_gcs_uri`:
     ```python
     input_provenance: list[SourceSpan] = Field(default_factory=list)   # NEW
     ```
     Update `for_single`'s docstring from:
     ```
     input_fields dict must contain:
       input_source_kind, input_text, input_source_filename,
       input_pdf_gcs_uri, input_version, grading_enabled
     ```
     to:
     ```
     input_fields dict must contain:
       input_source_kind, input_text, input_source_filename,
       input_pdf_gcs_uri, input_provenance, input_version, grading_enabled
     ```
     No other change to `for_single` itself — it already forwards `**input_fields` directly into the constructor, so adding the `input_provenance` key to the caller's dict (Task 9) is sufficient. Do not touch the unrelated `shared`/`skipped_files` fields (01's job, tracked separately).
   - Acceptance criteria:
     - `python -c "from models.job import JobDoc"` (from `backend/`) succeeds.
     - Constructing a `JobDoc` via `for_single` with an `input_fields` dict that omits `input_provenance` still succeeds (default `[]` applies) — confirming this task alone doesn't require Task 9 to land first, even though Task 9 is the real production wiring.
     - `JobDoc.to_firestore()`/`JobDoc.from_firestore()` round-trip a doc containing a non-empty `input_provenance` list without error (nested `SourceSpan` list, `extra="ignore"` posture unchanged — PRD §4.10's note on the existing `output_data: Optional[CarePlanInternal]` precedent).

### Task 8 — `backend/services/care_plan_input.py`: `extract_pages_from_bytes`, rewritten `resolve_uploaded_files`, new `resolve_units_from_job_doc`

   - Files: `backend/services/care_plan_input.py`
   - Dependency: land after Tasks 2, 4, 5, 6 (needs `extract_pages_from_pdf`, `source_separator` gone, `unitize`/`SourceSpan` importable, and `ResolvedInput.provenance`).
   - Changes (PRD §4.7):
     - **Imports** — replace:
       ```python
       from utils.misc import extract_text_from_html, source_separator, text_artifact_filename
       from utils.pdf import merge_pdfs, extract_text_from_pdf
       from models.input import ResolvedInput
       ```
       with:
       ```python
       from utils.misc import extract_text_from_html, text_artifact_filename
       from utils.pdf import merge_pdfs, extract_pages_from_pdf
       from models.input import ResolvedInput
       from models.ledger import Unit
       from models.provenance import SourceSpan
       from services.unitizer import unitize
       ```
     - **Replace `extract_text_from_bytes` (currently lines 130-211) with `extract_pages_from_bytes`**, return shape changed from `str` to `list[tuple[int, str]]`, every branch's error handling preserved verbatim:
       ```python
       def extract_pages_from_bytes(file_bytes: bytes, filename: str) -> list[tuple[int, str]]:
           """Extract text from file bytes, segmented into (page_number, page_text)
           pairs, 1-indexed, in document order.

           Every format except PDF has no intrinsic paging concept and yields at
           most one entry, (1, whole_file_text) -- omitted entirely (returns [])
           if that text is empty/whitespace-only. PDFs yield one entry per page
           that has extractable text; a page with none is omitted, not
           renumbered (see utils.pdf.extract_pages_from_pdf).

           This is the extraction entry point resolve_uploaded_files calls: it
           needs page boundaries to build per-(file, page) SourceSpan provenance
           (see services.unitizer). There is no flat-text variant any more (see
           PRD 02 §9) -- a caller that only wants whole-file text can compute
           "\\n\\n".join(text for _, text in extract_pages_from_bytes(...)).
           """
           ext = _get_extension(filename)

           if not ext:
               raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail=f"filename has no extension: {filename}")

           if ext == "txt":
               text = file_bytes.decode("utf-8", errors="replace")
               return [(1, text)] if text.strip() else []

           if ext == "pdf":
               try:
                   return extract_pages_from_pdf(file_bytes)
               except PyPDF2.errors.FileNotDecryptedError as exc:
                   raise SimplifyError(
                       ErrorCode.FILE_PARSE_FAILED,
                       detail=f"{filename} appears to be password-protected. Please upload an unencrypted PDF.",
                       original=exc,
                   ) from exc
               except PyPDF2.errors.PyPdfError as exc:
                   raise SimplifyError(
                       ErrorCode.FILE_PARSE_FAILED,
                       detail=f"{filename} could not be read -- it may be corrupted, empty, "
                              f"or not actually a PDF file ({type(exc).__name__}).",
                       original=exc,
                   ) from exc

           if ext == "docx":
               try:
                   from docx import Document
               except ImportError as exc:
                   raise RuntimeError(
                       "python-docx is not installed. Add 'python-docx' to requirements.txt."
                   ) from exc

               try:
                   doc = Document(io.BytesIO(file_bytes))
                   text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
               except RuntimeError:
                   raise
               except Exception as exc:
                   raise SimplifyError(
                       ErrorCode.FILE_PARSE_FAILED,
                       detail=f"{filename} could not be read as a DOCX file -- it may be "
                              f"corrupted or not actually a DOCX file ({type(exc).__name__}).",
                       original=exc,
                   ) from exc
               return [(1, text)] if text.strip() else []

           if ext in {"html", "htm"}:
               try:
                   text = extract_text_from_html(file_bytes)
               except Exception as exc:
                   raise SimplifyError(
                       ErrorCode.FILE_PARSE_FAILED,
                       detail=f"{filename} could not be read as an HTML file ({type(exc).__name__}).",
                       original=exc,
                   ) from exc
               return [(1, text)] if text.strip() else []

           if ext in Constants.Uploads.IMAGE_EXTENSIONS:
               text = extract_text_from_image(file_bytes, ext)
               return [(1, text)] if text.strip() else []

           raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail=f"extension: {ext}")
       ```
     - **Rewrite `resolve_uploaded_files`** (same overall control flow, now builds `SourceSpan`s instead of prefixing `source_separator` text):
       ```python
       def resolve_uploaded_files(
           uploads,
           *,
           max_file_count: int,
           max_aggregate_bytes: int,
           tolerate_unusable_files: bool = False,
       ) -> tuple[ResolvedInput, bytes | None]:
           """... (docstring unchanged from today, plus:) `ResolvedInput.provenance`
           carries one SourceSpan per (file, page) that contributed non-blank
           text, in document order -- the compact map services.unitizer.unitize
           later expands into list[Unit] (see PRD 02 §4.1). No `--- Source: ... ---`
           marker is written into `text` any more; file identity is carried
           structurally by `provenance` instead (PRD 02 §4.6).
           """
           files = [upload for upload in uploads if upload and upload.filename]
           if not files:
               raise ValueError("Uploaded file is missing a filename")
           if len(files) > max_file_count:
               raise ValueError(f"Upload supports at most {max_file_count} files")

           text_parts: list[str] = []          # one entry per (file, page) block, pre-stripped
           provenance: list[SourceSpan] = []
           global_line_count = 0
           merge_candidates: list[tuple[bytes, str]] = []
           filenames: list[str] = []
           skipped_files: list[str] = []
           skipped_errors: list[Exception] = []
           aggregate_bytes = 0

           for upload in files:
               filename = upload.filename

               if not is_allowed_extension(filename):
                   exc = ValueError("File must be PDF, TXT, DOCX, HTML, or an image (PNG/JPG/WEBP/HEIC)")
                   if tolerate_unusable_files:
                       logger.warning("care_plan_input: skipping unusable file %s: %s", filename, exc)
                       skipped_files.append(filename)
                       skipped_errors.append(exc)
                       continue
                   raise exc

               file_bytes = upload.read()
               aggregate_bytes += len(file_bytes)
               if aggregate_bytes > max_aggregate_bytes:
                   limit_mb = max_aggregate_bytes / (1024 * 1024)
                   raise ValueError(f"Combined file size is too large (max {limit_mb:g} MB total)")

               try:
                   pages = extract_pages_from_bytes(file_bytes, filename)
                   for page_num, page_text in pages:
                       validate_text_storable(page_text, field=f"{filename} (page {page_num})'s extracted text")
                   extracted_text = "\n\n".join(t for _, t in pages)
                   real_content = extracted_text.strip()
                   if len(real_content) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
                       raise SimplifyError(
                           ErrorCode.EMPTY_DOCUMENT,
                           detail=f"{filename} produced no meaningful extractable text (likely a "
                                  "scanned image with no text layer, or a blank/empty file).",
                       )
               except (SimplifyError, ValueError) as exc:
                   if tolerate_unusable_files:
                       logger.warning("care_plan_input: skipping unusable file %s: %s", filename, exc)
                       skipped_files.append(filename)
                       skipped_errors.append(exc)
                       continue
                   raise

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

           if not filenames:
               if len(files) == 1 and skipped_errors:
                   raise skipped_errors[0]
               raise SimplifyError(
                   ErrorCode.EMPTY_DOCUMENT,
                   detail="None of the uploaded files contained readable text.",
               )

           combined_text = "\n".join(text_parts)
           validate_extracted_text_length(combined_text)

           combined_pdf_bytes = None
           if merge_candidates:
               try:
                   combined_pdf_bytes = merge_pdfs(merge_candidates)
               except Exception:
                   logger.exception("care_plan_input: failed to merge input files - continuing without combined PDF")

           file_count = len(files)
           file_types = sorted({ext for f in files if (ext := _get_extension(f.filename))})

           source_filename = ", ".join(filenames)
           combined_pdf_size = float(len(combined_pdf_bytes)) if combined_pdf_bytes is not None else None
           return ResolvedInput(
               text=combined_text,
               source_description=source_filename,
               source_filename=source_filename,
               combined_pdf_size=combined_pdf_size,
               file_count=file_count,
               file_types=file_types,
               skipped_files=skipped_files,
               provenance=provenance,
           ), combined_pdf_bytes
       ```
       **Critical, deliberate detail (do not "fix" it back)**: `combined_text = "\n".join(text_parts)` has **no trailing `.strip()`**, unlike the old code. Each `page_text` is already individually stripped before being appended, and parts are joined by exactly one `"\n"` — stripping the joined string here would shift line indices relative to the `SourceSpan`s just computed, breaking the exact invariant `unitize` depends on (PRD §4.7, verified by the property test in Task 12). Also note `validate_text_storable` now runs once per page (not once per file) — strictly more precise, not a behavior change in what gets rejected.
     - **Add `resolve_units_from_job_doc` as a new sibling to the unchanged `resolve_input_from_job_doc`** (leave `resolve_input_from_job_doc` exactly as-is — it still returns `job.input_text or ""`):
       ```python
       def resolve_units_from_job_doc(job) -> list[Unit]:  # job: models.job.JobDoc
           """Reconstruct the deterministic unit list for a job from its persisted
           (input_text, input_provenance) pair. Call once, in the worker,
           immediately before grounding (03) -- this is the read side of the
           provenance-map design (PRD 02 §4.1): the API computed and persisted
           input_provenance at job-creation time; this is where it gets spent,
           materializing the (larger, per-line) Unit list only in memory, never
           back to Firestore. The actual call site inside the pipeline run is
           06's (pipeline-orchestration) to wire up.
           """
           return unitize(job.input_text or "", job.input_provenance)
       ```
   - Acceptance criteria:
     - `grep -n "def extract_text_from_bytes\b" backend/services/care_plan_input.py` returns no hits; `grep -n "def extract_pages_from_bytes" backend/services/care_plan_input.py` returns one hit.
     - `grep -n "source_separator\|--- Source:" backend/services/care_plan_input.py` returns no hits.
     - `python -c "from services.care_plan_input import resolve_units_from_job_doc"` (from `backend/`) succeeds.
     - A single-file, 2-page-PDF upload through `resolve_uploaded_files` produces `resolved.provenance == [SourceSpan(file=<name>, page=1, start_line=0, end_line=N), SourceSpan(file=<name>, page=2, start_line=N+1, end_line=M)]` for the actual line counts of each page's text.
     - Fully covered by Task 12's rewritten/new tests.

### Task 9 — `backend/routes/jobs.py::_resolve_job_input`: wire `input_provenance` into both branches

   - Files: `backend/routes/jobs.py`
   - Dependency: land after Tasks 5, 7, 8.
   - Changes (PRD §4.11):
     - Add the import: `from services.unitizer import provenance_for_pasted_text`.
     - Pasted-text branch — add one new key to the returned dict, immediately after `input_pdf_gcs_uri`:
       ```python
       "input_provenance": provenance_for_pasted_text(text_input),   # NEW
       ```
       (full branch becomes: `input_source_kind`, `input_text`, `input_source_filename`, `input_pdf_gcs_uri`, `input_provenance`, `input_version`, `grading_enabled`, in that order).
     - Upload branch — add one new key, immediately after `input_pdf_gcs_uri`:
       ```python
       "input_provenance": resolved.provenance,   # NEW
       ```
   - Acceptance criteria:
     - `POST /jobs` with `{"text": "line one\nline two"}`: the created `JobDoc`'s `input_provenance` is `[SourceSpan(file="text_input", page=1, start_line=0, end_line=1)]` (one span covering both lines).
     - `POST /jobs` with a multi-file upload: the created `JobDoc`'s `input_provenance` is non-empty and matches `resolve_uploaded_files`'s returned `provenance`.
     - Spot-check `backend/tests/routes/test_jobs.py` (PRD §7.2: no test there does full-dict equality on the `create_job_doc` payload, so no rewrite is expected) — run `python -m pytest tests/routes/test_jobs.py -q` (from `backend/`) and confirm it still passes unchanged.

### Task 10 — `backend/utils/firebase.py`: clean up `input_provenance` at job termination

   - Files: `backend/utils/firebase.py`
   - Dependency: land after Task 7 (the field must exist on `JobDoc` before this task's `DELETE_FIELD` reference is meaningful, though `firestore.DELETE_FIELD` itself doesn't require the field to exist at write time — land after Task 7 for logical ordering).
   - Changes (PRD §4.12): In `complete_job`, add one line to `update_fields`, immediately after the existing `"input_text": firestore.DELETE_FIELD,`:
     ```python
     "input_provenance": firestore.DELETE_FIELD,   # NEW
     ```
     Do the identical addition in `fail_job`'s `update_fields`. Update both functions' docstrings' "Always clears input_text" language to "Always clears input_text and input_provenance."
   - Acceptance criteria:
     - `grep -n "input_provenance" backend/utils/firebase.py` returns two hits (one in `complete_job`, one in `fail_job`), each paired with `firestore.DELETE_FIELD`.
     - After a job completes or errors, `fake_db.raw_doc("care_plan_outputs", job_id)` has no `input_provenance` key (verified permanently by Task 16's e2e assertions).

### Task 11 — Rewrite `backend/tests/utils/test_pdf.py` against `extract_pages_from_pdf`; add one new test

   - Files: `backend/tests/utils/test_pdf.py`
   - Dependency: land after Task 2.
   - Changes (PRD §7.1 rows 1-2, §7.3):
     - Replace `test_extract_text_from_two_page_pdf`:
       ```python
       def test_extract_text_from_two_page_pdf():
           from utils.pdf import extract_pages_from_pdf

           pdf_bytes = _make_pdf(["First page content", "Second page content"])
           pages = extract_pages_from_pdf(pdf_bytes)

           assert len(pages) == 2
           assert pages[0][0] == 1
           assert pages[1][0] == 2
           assert "First page content" in pages[0][1]
           assert "Second page content" in pages[1][1]
       ```
     - Replace `test_extract_text_from_empty_pdf_returns_empty_string`:
       ```python
       def test_extract_pages_from_pdf_blank_page_returns_empty_list():
           from utils.pdf import extract_pages_from_pdf
           import PyPDF2

           writer = PyPDF2.PdfWriter()
           writer.add_blank_page(width=612, height=792)
           buffer = io.BytesIO()
           writer.write(buffer)
           pdf_bytes = buffer.getvalue()

           assert extract_pages_from_pdf(pdf_bytes) == []
       ```
     - Add the new test from §7.3:
       ```python
       def test_extract_pages_from_pdf_page_numbers_are_one_indexed_in_document_order():
           from utils.pdf import extract_pages_from_pdf

           pdf_bytes = _make_pdf(["Alpha", "Beta", "Gamma"])
           pages = extract_pages_from_pdf(pdf_bytes)

           assert [p[0] for p in pages] == [1, 2, 3]
       ```
     - Leave every other test in this file (merge_pdfs, `_image_to_pdf`, EXIF, HEIC tests) untouched — none reference the deleted function.
   - Acceptance criteria: `python -m pytest tests/utils/test_pdf.py -q` (from `backend/`) passes in full; `grep -n "extract_text_from_pdf" backend/tests/utils/test_pdf.py` returns no hits.

### Task 12 — Rewrite breaking tests and add new tests in `backend/tests/services/test_care_plan_input.py`

   - Files: `backend/tests/services/test_care_plan_input.py`
   - Dependency: land after Tasks 5, 6, 7, 8.
   - Changes (PRD §7.1 rows 3-10, §7.3):
     - Update the import block: replace `extract_text_from_bytes` with `extract_pages_from_bytes` in the `from services.care_plan_input import (...)` list.
     - Rewrite each of these breaking tests against the new function/shape (same assertions, new call site):
       - `test_extract_text_from_bytes_dotless_filename_raises_simplify_error` → rename to `test_extract_pages_from_bytes_dotless_filename_raises_simplify_error`, call `extract_pages_from_bytes(b"some bytes", "noextension")`, same `SimplifyError`/`ErrorCode.UNSUPPORTED_FILE_TYPE` assertion.
       - `test_extract_text_from_bytes_still_works_for_txt` → rename to `test_extract_pages_from_bytes_still_works_for_txt`, assert `extract_pages_from_bytes(b"hello world", "notes.txt") == [(1, "hello world")]`.
       - `test_extract_text_from_bytes_dispatches_image_extensions_to_ocr` → rename to `test_extract_pages_from_bytes_dispatches_image_extensions_to_ocr`; keep the `mock_extract_image.return_value = "ocr text"` mock; assert `extract_pages_from_bytes(b"bytes", "photo.png") == [(1, "ocr text")]`.
       - `test_extract_text_from_bytes_corrupt_pdf_raises_file_parse_failed` → rename, call `extract_pages_from_bytes(b"not a real pdf, just garbage bytes", "notes.pdf")`, same assertion.
       - `test_extract_text_from_bytes_empty_pdf_raises_file_parse_failed` → rename, call `extract_pages_from_bytes(b"", "empty.pdf")`, same assertion.
       - `test_extract_text_from_bytes_corrupt_docx_raises_file_parse_failed` → rename, call `extract_pages_from_bytes(b"not a real docx, just garbage bytes", "notes.docx")`, same assertion.
       - `test_resolve_uploaded_files_rejects_extracted_text_containing_lone_surrogate` — its `@patch("services.care_plan_input.extract_text_from_bytes", ...)` decorator must become `@patch("services.care_plan_input.extract_pages_from_bytes", ...)`, with the mock's return value changed from a bare string to `[(1, "hello \ud800 world -- padding so this clears MIN_MEANINGFUL_CONTENT_CHARS")]`.
     - Add `assert "--- Source:" not in resolved.text` to `test_resolve_uploaded_files_image_becomes_raw_merge_candidate` (the PRD's suggested regression-guard host test) — do not duplicate it into every other `_resolve(...)`-calling test.
     - Add these new tests (§7.3):
       ```python
       def test_resolve_uploaded_files_single_file_produces_one_span_per_page():
           # a 2-page PDF upload should yield exactly 2 SourceSpans, page 1 and 2
           ...

       def test_resolve_uploaded_files_multi_file_produces_contiguous_non_overlapping_spans_in_order():
           # walk resolved.provenance: spans[0].start_line == 0; each
           # spans[i].start_line == spans[i-1].end_line + 1; and
           # spans[-1].end_line == len(resolved.text.split("\n")) - 1
           ...

       def test_resolve_uploaded_files_pdf_blank_page_omitted_not_renumbered():
           # a synthetic 3-page PDF (reportlab) with a genuinely blank middle
           # page; assert [s.page for s in resolved.provenance] == [1, 3]
           ...

       def test_resolve_uploaded_files_omits_source_separator_marker_from_combined_text():
           assert "--- Source:" not in resolved.text

       def test_resolve_units_from_job_doc_round_trips_through_a_job_doc_shaped_object():
           # build a minimal object (or real JobDoc) with input_text/
           # input_provenance from a resolve_uploaded_files() call; assert
           # resolve_units_from_job_doc(job) == unitize(job.input_text, job.input_provenance)
           ...
       ```
       Use `_one_page_pdf`/`_make_pdf`-style reportlab helpers (mirror `test_pdf.py`'s helpers, or import them) to build the synthetic multi-page/blank-page PDFs; use `_FakeUpload` (already in this file) to drive `resolve_uploaded_files` in each new test, following the existing tests' pattern.
   - Acceptance criteria:
     - `python -m pytest tests/services/test_care_plan_input.py -q` (from `backend/`) passes in full, including every renamed/rewritten test and all 5 new tests above.
     - `grep -n "extract_text_from_bytes" backend/tests/services/test_care_plan_input.py` returns no hits.

### Task 13 — New `backend/tests/models/test_provenance.py`

   - Files: `backend/tests/models/test_provenance.py` (new file)
   - Dependency: land after Task 1.
   - Changes (PRD §7.3): Create tests covering `SourceSpan` from Task 1:
     - Round-trip: construct a `SourceSpan`, call `.to_dict()` then `.from_dict()`, assert equality.
     - `extra="forbid"` regression guard: assert constructing `SourceSpan(file="f", page=1, start_line=0, end_line=1, extra="x")` raises `ValidationError`.
   - Acceptance criteria: `python -m pytest tests/models/test_provenance.py -q` (from `backend/`) passes.

### Task 14 — New `backend/tests/services/test_unitizer.py`

   - Files: `backend/tests/services/test_unitizer.py` (new file)
   - Dependency: land after Task 5.
   - Changes (PRD §7.3): Create the following tests, exactly as specified:
     - `test_unitize_assigns_sequential_ids_skipping_blank_lines` — a span whose text has blank lines interspersed produces contiguous `id`s (1, 2, 3, ...) with no gaps, while `line` numbers do skip across the blank lines.
     - `test_unitize_is_deterministic_across_repeated_calls` — call `unitize(text, provenance)` twice with the same arguments; assert the two `list[Unit]` results are element-wise equal (same ids, same order).
     - `test_unitize_line_numbers_reset_per_page` — two spans (two pages of the same file); assert the second span's first unit has `line == 1`, not a continuation of the first span's line count.
     - `test_unitize_multi_file_preserves_distinct_file_identity` — two spans with different `file` values; assert each emitted `Unit.file` matches its own span, not the other's.
     - `test_unitize_empty_provenance_returns_empty_list`.
     - `test_unitize_preserves_verbatim_line_text_including_internal_whitespace` — a line with leading/trailing spaces mid-document is preserved exactly in `Unit.text` (only whole-line-blank lines are dropped, not whitespace trimmed from real lines).
     - `test_unitize_tolerates_span_past_end_of_text` — a deliberately malformed span whose `end_line` exceeds `len(text.split("\n"))`; assert `unitize` returns the units it *can* build rather than raising or crashing (the defensive `break`).
     - `test_provenance_for_pasted_text_single_span_covers_whole_text`.
     - `test_provenance_for_pasted_text_empty_string_returns_empty_list`.
   - Acceptance criteria: `python -m pytest tests/services/test_unitizer.py -q` (from `backend/`) passes; all nine listed cases present.

### Task 15 — `backend/tests/utils/test_image_ocr.py`: add ceiling-change tests

   - Files: `backend/tests/utils/test_image_ocr.py`
   - Dependency: land after Task 3.
   - Changes (PRD §7.3):
     ```python
     def test_max_long_edge_is_4096():
         from utils.image_ocr import _MAX_LONG_EDGE_PX
         assert _MAX_LONG_EDGE_PX == 4096

     def test_maybe_downscale_leaves_image_between_old_and_new_ceiling_unchanged():
         # a ~3000px-long-edge image: under the new 4096 ceiling, _maybe_downscale
         # must return it unchanged (regression-proof the ceiling actually moved --
         # under the OLD 2048 ceiling this image would have been downscaled)
         ...

     def test_maybe_downscale_still_downscales_image_over_new_ceiling():
         # an image over 4096px long edge is thumbnailed to <= 4096
         ...
     ```
     Follow the file's existing `PIL.Image.new(...)` pattern (as in `test_maybe_downscale_returns_unchanged_for_small_image`) to build the synthetic images at the needed sizes.
   - Acceptance criteria: `python -m pytest tests/utils/test_image_ocr.py -q` (from `backend/`) passes in full, including the 3 new tests.

### Task 16 — `backend/tests/routes/test_jobs_e2e_scenarios.py`: `input_provenance` lifecycle assertions

   - Files: `backend/tests/routes/test_jobs_e2e_scenarios.py`
   - Dependency: land after Tasks 7, 9, 10.
   - Changes (PRD §7.3):
     - In `TestScenario1TypicalDischargeSummary::test_full_chain_completes_and_final_doc_is_safe_and_small`, add `assert "input_provenance" not in doc` immediately alongside the existing `assert "input_text" not in doc` (line ~476).
     - In `TestScenario4MultibyteNearLimits::test_mixed_multibyte_just_under_both_caps_completes_and_stays_under_1mib`, add the same `assert "input_provenance" not in doc` alongside its existing `assert "input_text" not in doc` (line ~668).
     - Add one new test proving the **processing-state** doc actually carries `input_provenance` before the worker cleans it up — mirror the existing pattern at line ~528 (`doc = fake_db.raw_doc("care_plan_outputs", job_id)` read immediately after `_post_job`, before `_run_worker`), e.g. inside `TestScenario2PhonePhotosOCR` or as a small standalone test using the same 3-image multipart upload fixture:
       ```python
       def test_multi_file_upload_processing_doc_has_non_empty_input_provenance(self, client_jobs, fake_db, auth_anon):
           # POST /jobs with a multi-file upload; before running the worker,
           # read the raw processing-state doc via fake_db.raw_doc(...) and
           # assert doc["input_provenance"] is a non-empty list.
           ...
       ```
     - Do **not** touch the doc-size-budget thresholds (`_doc_size_bytes`, `_max_leaf_string_bytes`, `< 1_048_576`, `< 1500`) or `_build_care_plan` — both are out of scope for this PRD (§3 Non-Goals; `_build_care_plan`'s drift is PRD 01's concern, tracked in its own TASKS.md).
   - Acceptance criteria:
     - `python -m pytest tests/routes/test_jobs_e2e_scenarios.py -q` (from `backend/`) — the specific tests touched by this task pass. (Other tests in this file may still show `_build_care_plan`-related failures inherited from PRD 01 not having landed yet in this repo state — not this task's concern; do not edit `_build_care_plan` to force them green.)
     - `grep -n "input_provenance" backend/tests/routes/test_jobs_e2e_scenarios.py` returns at least 3 hits (the 2 completed-doc assertions plus the new processing-state test).

### Task 17 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-16 (and after PRD 01's tasks have landed, since several tests in `test_jobs_e2e_scenarios.py` and `test_care_plan.py` depend on 01's schema changes independently of this PRD).
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/ -q` passes with zero failures and zero errors attributable to this PRD's changes. Any remaining failures must trace only to PRD 01 (or later sub-projects') scope — list exactly which test functions and why if any remain, don't silently mark this task done if an unrelated-but-real regression is present.
     - `grep -rn "extract_text_from_pdf\b\|extract_text_from_bytes\b\|source_separator" backend --include=*.py` (excluding this TASKS.md/PRD.md) returns zero hits anywhere in the codebase — confirms all three retired names are fully gone, not just from their primary call sites.
     - `python -c "from models.provenance import SourceSpan; from services.unitizer import unitize, provenance_for_pasted_text; from services.care_plan_input import extract_pages_from_bytes, resolve_units_from_job_doc; from utils.pdf import extract_pages_from_pdf; from utils.image_ocr import _MAX_LONG_EDGE_PX; assert _MAX_LONG_EDGE_PX == 4096"` (from `backend/`) succeeds — a single smoke import proving every new/renamed symbol this PRD introduces is wired together correctly.

---

## Handed off to other sub-projects (specified here, not implemented here — do not action as part of this task list)

- **To 03 (grounding)**: consumes `list[Unit]` (via `resolve_units_from_job_doc`/`unitize`) as its evidence-citation input. No prompt text, no grounding-LLM call, no citation logic is this PRD's job (§3 Non-Goals).
- **To 06 (pipeline-orchestration)**: the actual call site of `resolve_units_from_job_doc()`/`unitize()` inside a real pipeline run (wiring it into `care_plan/pipeline.py` / `services/care_plan_pipeline.py`) is 06's job, not this PRD's — this PRD only builds the function and proves it's correct in isolation (§3 Non-Goals, §4.1, §4.7's docstring cross-reference).
- **To 09 (input-transport)**: PRD 09 is a later, independent follow-on that supersedes the Firestore-based transport mechanism built in Tasks 6, 7, 9, 10 above (`JobDoc.input_provenance` as a Firestore field, and its `firestore.DELETE_FIELD` cleanup) — PRD 09 moves `input_text` and `input_provenance` together into one GCS object per job instead, and deletes `resolve_units_from_job_doc` outright, having the worker call `services.unitizer.unitize(text, provenance)` directly (PRD 02 §9's `[RESOLVED]` cross-reference to PRD 09 §4.1/§4.9/§4.11). This PRD's own tasks above still build the Firestore-field version exactly as PRD 02 specifies it — PRD 09's task list (generated separately) is responsible for the migration/deletion, not this one. Everything else this PRD builds (`SourceSpan`, `unitize`/`provenance_for_pasted_text`, the unit-granularity table, the OCR downscale ceiling change) is left standing by PRD 09 and needs no rework here.

## Summary of what requires you (not a dev agent)

Per PRD §8, both items are manual/qualitative checks tied to real infrastructure and cannot be automated by a dev agent:

1. **OCR ceiling smoke test.** Run a real end-to-end test via ngrok + pm2 (`SERVICE_MODE=combined`) with a genuine multi-page scanned/photographed document containing small print (a medication list with decimal dosages and drug-name suffixes is the worst case). Confirm (a) the OCR call completes without a Vertex payload-size or timeout error at the new 4096px ceiling, and (b) transcription of small text visibly improves versus the old 2048px ceiling. No automated test can perform this (clinical-fidelity evaluation is out of scope everywhere).
2. **Vertex AI inline-request limits.** The PRD's payload-size reasoning (§4.5) rests on the existing 10 MB upload cap and general knowledge of Gemini's inline-request handling, not a live check against current Vertex AI documentation/quotas — worth a quick confirmation on your end before this reaches production traffic, ideally alongside item 1's smoke test.

No PRD §9 items are `[OPEN]` — the gate was clear; all 17 tasks above derive from `[RESOLVED]` decisions only. One `[RESOLVED]` item (the PRD 09 cross-reference) is recorded above as a hand-off, not a task, since it describes a *future* sub-project's supersession, not something this PRD's own tasks need to preempt.
