# PRD 02 — Unitization and Provenance

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2.5 and §3.2).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (schema-and-config) — specifically `backend/models/ledger.py`'s `Unit` model:

```python
class Unit(JsonModel):
    id: int
    file: str
    page: int
    line: int
    text: str
```

Depended on by: 03 (grounding, cites `Unit.id`), 06 (pipeline-orchestration, wires this sub-project's output into the pipeline run).

## 1. Problem

The deterministic input path — turning an uploaded/pasted document into text the pipeline can run on — already computes file and page identity for every extracted character, and throws it away before that identity can ever reach a `Unit`:

- **`backend/services/care_plan_input.py::resolve_uploaded_files`** concatenates every uploaded file's extracted text into one blob, prefixing each file's content with a plain-text marker, `source_separator(filename)` (`backend/utils/misc.py:106`, `"\n\n--- Source: {filename} ---\n"`), then joins everything with `"\n"` and hands the whole flattened string to the job as `input_text`. File identity survives only as prose a downstream LLM would have to notice and correctly parse back out — never as structured data.
- **`backend/utils/pdf.py::extract_text_from_pdf`** iterates `reader.pages`, computes `page_num` inside the loop, logs it once at `debug` level, and then joins every page's text with `"\n\n"` — the page number is never returned to the caller. It is computed and discarded in the same function.
- **The API/worker split makes this loss permanent, not just wasteful.** `routes/jobs.py::create_job` resolves input (calling `resolve_uploaded_files`, which has the original file bytes) and writes a `JobDoc` to Firestore containing only `input_text: str` — a flat string, `input_source_filename: str` — a comma-joined list of names with no per-character mapping back to which name, and `input_pdf_gcs_uri` — a URI to a *merged, re-rendered* PDF (TXT/DOCX/HTML files are re-flowed through `reportlab` into synthetic PDF pages at merge time; this is not the original file). `routes/worker.py::execute_job` later reads that same job doc back via `resolve_input_from_job_doc(job) -> job.input_text or ""` and runs the pipeline on the flat string alone. By the time the worker runs, the only bytes it has ever seen are `input_text`; the original per-file, per-page bytes were read once by the API process and never persisted anywhere the worker can reach them in their original form.

The brief's inverted pipeline (brainstorm.v1.md §2.5, §3.2) requires a `Unit` for every clause the grounding LLM might cite, addressable by a bare integer `id`, with `file`/`page`/`line` recoverable "by lookup" rather than asked of the model. Building that lookup table requires the exact file/page boundaries this code already computes and discards — and requires them to survive from the process that computes them (the API) to the process that needs them (the worker), which today share no state but a flattened string.

This PRD is the deterministic input path that produces `Unit` records (01's exact contract) from every input path — upload (PDF/TXT/DOCX/HTML/image) and pasted text — and resolves how that provenance survives the API→worker boundary without either reconstructing it from data the worker doesn't have, or blowing through Firestore's document-size budget.

## 2. Goals

- Produce a `Unit` (per 01's `models/ledger.py` contract) for every meaningful line of every input source — upload or pasted text — with stable, reproducible `id` assignment.
- Preserve real page numbers for PDFs (including gaps for blank pages) and real file identity for every upload, including a multi-image upload where each image is its own file.
- Resolve **the central design problem**: how unit provenance survives the API (which resolves input) → Firestore job doc → worker (which runs the pipeline) hop, given the worker never has access to original file bytes and job docs are size-constrained.
- Retire the `--- Source: {filename} ---` inline marker from model-facing text, since file identity is now carried structurally.
- Raise the OCR downscale ceiling from 2048px to 4096px long edge, and account for the knock-on effects (payload size, latency, output-token budget).
- Specify every test this breaks and every new deterministic test the unitizer needs, with unit-ID stability as the load-bearing property (evidence citation, owned by 03, depends on it).

## 3. Non-Goals

- No grounding LLM call, no prompt text for it (03's job — this PRD hands 03 a `list[Unit]` and stops).
- No pipeline wiring. `care_plan/pipeline.py` and `services/care_plan_pipeline.py` are untouched; they keep calling the old three-LLM-step pipeline until 06 rewires them. `routes/worker.py` is touched only where this PRD's own new field (`input_provenance`) must be cleaned up at job completion/failure (§4.12) — not to invoke the unitizer from the pipeline run itself, which is 06's wiring job.
- No `Fact`/ledger logic (03's `Fact` model already exists per 01; this PRD produces `Unit`s only).
- No changes to `models/ledger.py` itself — 01's `Unit` contract is taken as given (see §9 on where I considered, and rejected, diverging from it).
- No frontend changes. The unit list and its provenance are never rendered to the patient (brief §3.10) and never appear in any API response (§5).
- No versioning, no migration code, no dual-shape support — mutate in place, per the global constraint. `JobDoc.input_provenance` is a new field added directly; there is no prior shape to migrate from.
- No clinical-fidelity evaluation of the raised OCR ceiling (out of scope everywhere per the brief's Non-Goals) — only the mechanical/architectural consequences of the constant change are this PRD's concern.
- No per-PR backend preview environment concerns (out of scope everywhere).

## 4. Architecture Decisions

### 4.1 THE CENTRAL DESIGN PROBLEM — provenance across the API→worker boundary

**Constraint recap, verified against the actual code:**

- `routes/jobs.py::create_job` → `_resolve_job_input` runs in the **API** process. For uploads, it calls `resolve_uploaded_files`, which has the original file bytes in memory and calls `extract_text_from_bytes` per file (which is where PDF page boundaries are visible, momentarily, inside `extract_text_from_pdf`'s loop). For pasted text, there are no file bytes at all.
- The API writes a `JobDoc` (`models/job.py`) to Firestore via `create_job_doc`, containing `input_text: str` (the flattened blob, capped at `Constants.Uploads.MAX_TEXT_BYTES = 350,000` bytes) and `input_pdf_gcs_uri: str | None` — a URI to a **merged, re-rendered** PDF built by `utils/pdf.py::merge_pdfs`, used only for GCS retention/audit, never read back by the pipeline. Confirmed by grep: `input_pdf_gcs_uri` has exactly one production consumer after job creation — `routes/worker.py`'s `finally` block, which deletes the GCS object. Nothing ever downloads or re-parses it.
- The **worker** process later reads the job doc back (`get_job_doc` → `JobDoc.from_firestore`) and calls `resolve_input_from_job_doc(job) -> job.input_text or ""`. This is the *only* text the worker ever sees. It has no access to the original uploaded bytes, and even if it fetched `input_pdf_gcs_uri`, that PDF's pages do not correspond 1:1 to the original files' pages — TXT/DOCX/HTML inputs were re-flowed through `reportlab` at 95-char line wrap and letter-page dimensions having nothing to do with how `extract_text_from_bytes` originally segmented that file's text, and a multi-file upload's original files are concatenated into one merged PDF with no page-range index recorded anywhere mapping "merged PDF page N" back to "original file X, page M".

**This rules out "unitize in the worker by re-extracting from original bytes" outright**, not as a matter of preference but of missing data: the bytes the worker would need either don't exist in the worker's reach (pasted text was never stored as bytes at all) or exist only in a re-rendered form (`input_pdf_gcs_uri`) whose page structure is a synthetic artifact of the merge process, not the original extraction's page structure. Re-extracting from it would produce *different, wrong* page numbers, not merely redundant work.

That leaves two live options, both raised in the task brief:

**Option 1 — persist the full `list[Unit]` on the job doc.** Compute units in the API (where the bytes are), write them directly as `JobDoc.units: list[Unit]`, read them back verbatim in the worker.

Rejected. This duplicates the entire input text a second time inside the same document: each `Unit` carries its own `text: str` field, so a job doc would contain both `input_text` (up to 350,000 bytes) *and* an array of per-line objects whose `text` fields sum back to approximately the same 350,000 bytes, plus per-unit JSON overhead (`"id"`, `"file"`, `"page"`, `"line"` keys, the repeated filename string, list/object punctuation) for every single line. For a dense, many-short-line document (a lab-values table, a densely bulleted discharge checklist), this overhead is not a rounding error — a document with a few thousand short lines could plausibly double the size of what's already, by design, the single largest field on the job doc. `Constants.Uploads.MAX_TEXT_BYTES` (350,000 B) was explicitly sized "to keep the full `care_plan_outputs` Firestore doc under the 1,048,576-byte (1 MiB) hard document limit," with its own comment recording "350,000 B leaves a large safety margin below the ~896,576 B actually available for `input_text`." Spending that entire remaining headroom (and risking exceeding it) to store a second, structurally bulkier copy of data already present in the same document is the wrong trade for a field that exists purely so the worker can look up `file`/`page` by integer — it does not need `text` duplicated to do that lookup at all, since the text is already sitting right next to it in `input_text`.

**Option 2 (recommended) — persist a compact provenance map alongside the already-persisted flattened text; materialize `list[Unit]` in the worker as a pure, in-memory reconstruction.**

The API computes, at the same time it builds `input_text`, a small list of `(file, page, start_line, end_line)` ranges — one entry per (file, page) pair, not per line — describing which contiguous slice of `input_text`'s lines belongs to which file/page. This is the `SourceSpan` model (§4.3). It is persisted as a new `JobDoc.input_provenance: list[SourceSpan]` field, written in the same `create_job_doc` call that already writes `input_text`.

The worker, immediately before it needs units (i.e. right before invoking 03's grounding step — the actual call site is 06's, not this PRD's, since 06 owns pipeline wiring), calls a pure function `unitize(text, provenance) -> list[Unit]` (§4.8) that splits `job.input_text` on `"\n"` and, walking the span list, assigns each non-blank line a `Unit` with the right `file`/`page`/`line`/`text` and a stable, sequential `id`. This is the "unitizer" in the sense the brief means it — deterministic, our own code, never the model — but its *output* is never itself persisted. It is computed once per job, in memory, at the point it is consumed.

Why this wins over Option 1, concretely:

1. **No duplicated text.** `SourceSpan` carries four small integers and one filename string per (file, page) — not per line. A realistic upload (bounded by `Constants.Limits.MAX_FILE_COUNT = 5` files, `MAX_AGGREGATE_FILE_BYTES = 10 MB` combined, itself an upper bound on how many *pages* can plausibly exist) produces tens of spans, not thousands of units. Even a pathological 5-file upload averaging 100 pages each (500 spans) costs roughly 500 × ~70 bytes (`{"file":"discharge.pdf","page":123,"start_line":4567,"end_line":4598}`) ≈ 35 KB — under a tenth of the ~546 KB of headroom `MAX_TEXT_BYTES` was deliberately sized to leave. A per-line `Unit` list for the same document would be one to two orders of magnitude larger, because it duplicates `input_text` itself.
2. **The worker already reads `input_text`.** `unitize` needs nothing the worker doesn't already fetch in one Firestore read. No second collection, no second read, no new I/O.
3. **Matches the existing lifecycle.** `input_text` is deleted from the job doc at both `complete_job` and `fail_job` (`utils/firebase.py`, via `firestore.DELETE_FIELD`) the instant the job reaches a terminal state — "write-once... read-once," per `complete_job`'s own docstring. `input_provenance` gets exactly the same treatment (§4.12): it is only ever needed for the one `unitize()` call at pipeline-run time, same as `input_text` is only ever needed for the one pipeline run. Persisting units instead would create a second piece of state with the same short lifetime but a much larger footprint for the same window.
4. **Deterministic and cheap to verify.** Because `unitize` is a pure function of `(text, provenance)`, its correctness is fully covered by unit tests (§7) with no Firestore, no HTTP, no mocking of file bytes — a stronger determinism guarantee than "trust that whatever got written to the job doc round-trips," which is what Option 1 would still need to prove separately.

**Option 3 — "unitize in the worker" is not actually a third option once Option 2 exists.** The brief's phrasing invites reading it as "worker re-extracts from bytes," which §4.1 above rules out. But there's a version worth naming explicitly since it's easy to conflate with the recommendation: the worker *does* do the actual unit-materialization step (calling `unitize`) — it just does it against the API-computed provenance map, not against re-extracted bytes. This is exactly Option 2; it is not a separate option.

**Decision: Option 2.** `SourceSpan` is computed in the API (§4.3, §4.7) and persisted (§4.10); `Unit` is materialized in the worker via `unitize()` (§4.8) and never persisted. Recorded as `[RESOLVED]` in §9.

### 4.2 Unit granularity — what "line" means per source type

The brief's own diagram (`brainstorm.v1.md` §3.2) shows `{id: 47, file: "cardiology-note.pdf", page: 2, line: 14, text: "..."}` — `line` is a page-relative, 1-indexed position, distinct from `id` (the flat, document-wide integer the model actually cites; per 01 §4.3's rationale, `line` is documentation/debug-only, never itself cited).

A "line" is one `"\n"`-delimited line of whatever text that source type's own extractor already produces — no new tokenization is introduced. Concretely, per source type:

| Source type | `Unit.file` | `Unit.page` | `Unit.line` (1-indexed within its page/file) |
|---|---|---|---|
| PDF | the uploaded filename | the real PDF page number (1-indexed; a blank page with no extractable text is omitted, **not renumbered** — if page 2 is blank, pages jump 1 → 3) | position within that page's `PyPDF2`-extracted text, split on `"\n"` |
| TXT | the uploaded filename | `1` (constant — no page concept) | position within the whole decoded file, split on `"\n"` |
| DOCX | the uploaded filename | `1` (constant — `python-docx`'s `.paragraphs` API exposes no page boundaries) | index among non-empty paragraphs (each paragraph is already one line by construction — see `extract_pages_from_bytes`'s DOCX branch, §4.7, unchanged from today's `"\n".join(p.text for p in doc.paragraphs if p.text.strip())`) |
| HTML | the uploaded filename | `1` (constant) | position within BeautifulSoup's `get_text(separator="\n")` output |
| Image | the uploaded filename (per brief §3.2: "a multi-image upload gives each image its own file identity") | `1` (constant, per image — brief §3.2: "one image is one unit source at page: 1") | position within that image's Gemini OCR transcription, split on `"\n"` |
| Pasted text | the literal string `"text_input"` (§9 — reuses the existing sentinel already used for `input_source_filename` and special-cased in `utils/misc.py::derive_output_name`, rather than inventing a new convention) | `1` (constant) | position within the pasted text, split on `"\n"` |

**Blank/whitespace-only lines get no `Unit`** — they carry no citable clinical content and would only add substring-match noise to 03's quote-verification check — but they still occupy a slot in the line-index accounting, so `Unit.line` numbers match what a human counting lines in the original page/file would call that line (no silent renumbering across a blank line). `Unit.id` (the flat, global, model-cited integer) is assigned only to lines that actually produce a `Unit`, sequentially, in document order (span order, then line order within a span) — so `id` values are always contiguous starting at 1, with no gaps, even though the underlying line indices they're drawn from may skip blank lines. This is what makes `id` "stable and reproducible": the same `(input_text, input_provenance)` pair always produces the same `list[Unit]`, in the same order, with the same ids (§7).

### 4.3 New module: `backend/models/provenance.py`

Placement mirrors 01's own reasoning for `models/ledger.py` (§4.3 there): a small, flat module directly under `backend/models/`, not a subpackage, and not inside `models/care_plan/` (this is not part of the `CarePlan` family) — and, unlike `Unit`/`Fact`, *not* inside `ledger.py` either, because `SourceSpan` has a materially different lifecycle from `Unit`/`Fact`: it **is** persisted to Firestore (as a `JobDoc` field), where `Unit`/`Fact` explicitly never are (01 §4.1.4, brief §3.10). Co-locating a persisted model with two pipeline-internal-only models would blur that distinction for anyone reading `ledger.py` expecting "nothing in this file reaches Firestore."

```python
"""Pydantic model for the deterministic per-(file, page) line-range map
persisted alongside a job's flattened input text.

SourceSpan is the compact, Firestore-persisted half of the provenance
design (PRD 02 §4.1): the API computes it once, at job-creation time, from
data only it has (each uploaded file's own extracted, page-segmented
text); the worker later reconstructs the full, larger list[Unit] (models.
ledger.Unit) from (input_text, list[SourceSpan]) via services.unitizer.
unitize, without ever re-touching original file bytes.

A SourceSpan never appears in any API response -- like Unit and Fact, it
is pipeline-/job-internal only. Unlike Unit and Fact, it IS persisted to
Firestore (as JobDoc.input_provenance), which is exactly why it stays
small: it carries a line RANGE, never a copy of the text in that range.
"""
from __future__ import annotations

from .base import JsonModel


class SourceSpan(JsonModel):
    """One contiguous, 0-indexed, inclusive range of global line indices --
    into `input_text.split("\\n")` -- attributed to one (file, page).

    Spans are produced in document order and, taken together, partition
    every line of the job's combined input_text with no gaps or overlaps.
    The two producers (services.care_plan_input.resolve_uploaded_files and
    services.unitizer.provenance_for_pasted_text) are responsible for this
    invariant; services.unitizer.unitize (the consumer) trusts it rather
    than re-validating it on the hot path -- see that function's docstring.
    """

    file: str
    page: int
    start_line: int
    end_line: int
```

Both new integer fields are 0-indexed (matching Python's own `str.split("\n")` indexing directly, so `unitize` needs no off-by-one translation) — deliberately *not* the same indexing convention as `Unit.line` (1-indexed, page-relative), because the two fields answer different questions: `SourceSpan.start_line`/`end_line` index into the flat `input_text`; `Unit.line` is a page-relative display/debug number for a human. Conflating them would make one of the two conventions wrong for its own purpose.

### 4.4 `backend/utils/pdf.py` — stop discarding the page boundary

Old:
```python
def extract_text_from_pdf(pdf_content: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
    text_parts: list[str] = []
    for page_num, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())
            logger.debug("pdf_extract: page %d: %d chars", page_num + 1, len(page_text))
    full_text = "\n\n".join(text_parts)
    logger.info("pdf_extract: %d total chars from %d pages", len(full_text), len(reader.pages))
    return full_text
```

New — **rename and change the return shape**; the page number becomes the whole point of the return value instead of a debug-log-only side effect:

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
    (see extract_pages_from_bytes, §4.7).
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

`extract_text_from_pdf` (the old flat-string function) is **deleted**, not kept as a wrapper — see §9 for the rationale (zero production callers survive this PRD; keeping a dead flat-text-only function around to avoid touching two tests is exactly the vestigial-surface pattern the parent brief argues against elsewhere). `backend/tests/utils/test_pdf.py`'s two callers of the old function are rewritten against the new one (§7).

`merge_pdfs` and everything else in this file is untouched.

### 4.5 `backend/utils/image_ocr.py` — OCR downscale ceiling 2048 → 4096

```python
_MAX_LONG_EDGE_PX = 2048   # OLD
_MAX_LONG_EDGE_PX = 4096   # NEW
```

That is the entire code change (`backend/utils/image_ocr.py:12`). `IMAGE_OCR_PROMPT` is unchanged, per the brief's explicit instruction ("Leave `IMAGE_OCR_PROMPT` unchanged... adding illegibility markers invites mid-transcription editorialising").

Rationale (from the brief, decision-log table): a letter page at 2048px long edge is ~186 DPI — below where decimals and drug-name suffixes reliably survive OCR, and this is the one failure mode in the whole design invisible to every other safeguard, since 05's fidelity reviewer compares the assembled plan against the *transcription*, not the original photo — a corrupted transcription passes review cleanly. At 4096px long edge, a standard 8.5×11" page is ~372 DPI.

Knock-on effects considered:

- **Upload payload size is already bounded independently.** `Constants.Limits.MAX_AGGREGATE_FILE_BYTES = 10 MB` caps the *original* uploaded file bytes before any resize logic runs (`app.py`'s `MAX_CONTENT_LENGTH = 15 * 1024 * 1024` is the outer Flask-level backstop above that). Raising the downscale ceiling doesn't change what a client can upload — it changes what `_maybe_downscale` does with it: images whose long edge already fell in `(2048, 4096]` now bypass resizing entirely (`if max(image.size) <= _MAX_LONG_EDGE_PX: return image_bytes` is unchanged) and are sent to Vertex as their original upload bytes — already bounded by the 10 MB cap. Images over 4096px are thumbnailed down to 4096 instead of 2048, which can produce a larger re-encoded payload than before, but the source is still a photo of a document (large white/light background areas compress well) within the same 10 MB input ceiling.
- **`Part.from_data(data=image_bytes, ...)` (`utils/llm.py`) sends the image inline in the `generateContent` request**, not via GCS/File API. Vertex's Gemini inline-request-size ceiling is well above what a 4096px-long-edge document photo produces in practice, but this is an external, Google-side limit this PRD cannot verify from inside the repo — flagged as a manual smoke-test item, §8, not a blocking `[OPEN]` (the constant change itself is unambiguous and low-risk given the existing 10 MB upload bound).
- **`Constants.Llm.MAX_TOKENS_LONG_FORM = 65536`** governs the OCR call's *output* token budget (how much transcribed text the model may return) — this is a function of how much text is on the page, not the input image's pixel resolution, and Gemini's image-tokenization cost is resolution-tiered (bucketed), not linear in raw pixels, so no output-budget change is needed alongside this constant change.
- **Latency**: modestly higher per-image encode/transmit time at the new ceiling; not expected to meaningfully threaten `Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S = 270` given the existing multi-hundred-second budget and that this affects only the OCR step, not the LLM pipeline steps that follow it.

No other file changes for this item.

### 4.6 `backend/utils/misc.py` — retire `source_separator`

Verified by grep: `source_separator` (`utils/misc.py:106-107`) has exactly one caller anywhere in the codebase — `services/care_plan_input.py:308`, inside `resolve_uploaded_files` — and zero test references (`backend/tests/utils/test_misc.py` does not test it). Once file identity is carried structurally by `SourceSpan`/`Unit` (§4.1–§4.3, §4.7), the inline marker is exactly the "plain-text markers become redundant in model-facing text" case the brief calls out (§2.5, §3.2). **Delete the function outright:**

```python
def source_separator(filename: str) -> str:
    return f"\n\n--- Source: {filename} ---\n"
```

No replacement, no deprecation shim — zero other consumers, and the global constraint is "no back-compat cruft."

### 4.7 `backend/services/care_plan_input.py` — the extraction/resolution rewrite

**Imports.** Old:
```python
from utils.misc import extract_text_from_html, source_separator, text_artifact_filename
from utils.pdf import merge_pdfs, extract_text_from_pdf
from models.input import ResolvedInput
```
New:
```python
from utils.misc import extract_text_from_html, text_artifact_filename
from utils.pdf import merge_pdfs, extract_pages_from_pdf
from models.input import ResolvedInput
from models.ledger import Unit
from models.provenance import SourceSpan
from services.unitizer import unitize
```

**`extract_text_from_bytes` is replaced by `extract_pages_from_bytes`** — the single extraction entry point, page-segmented for every format (not just PDF). Every branch's error handling is preserved **verbatim**; only the return shape changes, from `str` to `list[tuple[int, str]]`:

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

**`resolve_uploaded_files`** — same overall control flow (extension check → read bytes → aggregate-size check → extract+validate → `tolerate_unusable_files` handling → merge-candidate bookkeeping), rewritten to build `SourceSpan`s instead of prefixing `source_separator` text:

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

Notable, deliberate details worth a junior developer's attention:

- **`combined_text = "\n".join(text_parts)` has no trailing `.strip()`** (the old code did `.strip()` here). Each `page_text` is already individually stripped of leading/trailing whitespace before being appended, and parts are joined by exactly one `"\n"` with nothing prepended/appended around the whole list — so `combined_text` is already clean, *and*, critically, stripping the joined string here would shift line indices relative to the `SourceSpan`s just computed, breaking the exact invariant `unitize` depends on. **Do not add `.strip()` back** — see the property test in §7 that guards this.
- **`validate_text_storable` moved from once-per-file to once-per-page** — strictly more precise (pinpoints which page of a multi-page file has the unstorable content), not a behavior change in what gets rejected.
- The `elif ext in {"docx", "html", "htm"} and real_content:` merge-candidate branch is **unchanged** — it still encodes the flat, non-page-segmented `extracted_text` for the synthetic merged-PDF artifact, which has nothing to do with unit provenance.

**`resolve_input_from_job_doc` is unchanged** — it still returns `job.input_text or ""`, because 03's grounding prompt needs the flat line-numbered text itself (brief §3.3: "Input: the line-numbered original"), not the unit list, to build its prompt. A new sibling function is added alongside it:

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

### 4.8 New module: `backend/services/unitizer.py`

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

### 4.9 `backend/models/input.py` — `ResolvedInput.provenance`

```python
class ResolvedInput(JsonModel):
    text: str
    source_description: str
    source_filename: str
    combined_pdf_size: float | None = None
    source_kind: str = "upload"
    file_count: int = 0
    file_types: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    provenance: list[SourceSpan] = Field(default_factory=list)   # NEW
```

Add `from .provenance import SourceSpan` to the file's imports. `provenance` defaults to `[]` so any other (hypothetical, currently nonexistent) construction site of `ResolvedInput` that doesn't pass it explicitly still validates — though in practice `resolve_uploaded_files` is `ResolvedInput`'s only production constructor (grep-confirmed).

### 4.10 `backend/models/job.py` — `JobDoc.input_provenance`

```python
class JobDoc(JsonModel):
    ...
    # ── Input provenance ──────────────────────────────────────────────────
    input_source_kind: SourceKind
    input_text: Optional[str] = None
    input_source_filename: str
    input_pdf_gcs_uri: Optional[str] = None
    input_provenance: list[SourceSpan] = Field(default_factory=list)   # NEW
    input_version: str = "v1-2"
    grading_enabled: bool = False
    ...
```

Add `from .provenance import SourceSpan` to the file's imports.

Update `for_single`'s docstring:
```python
"""input_fields dict must contain:
  input_source_kind, input_text, input_source_filename,
  input_pdf_gcs_uri, input_provenance, input_version, grading_enabled
"""
```
No other change to `for_single` itself — it already forwards `**input_fields` directly into the constructor, so adding the `input_provenance` key to the caller's dict (§4.11) is sufficient.

`JobDoc`'s `extra="ignore"` posture (inherited, unchanged) means the nested `SourceSpan` list round-trips through `to_firestore()`/`from_firestore()` the same way `output_data: Optional[CarePlanInternal]` already does today — proven pattern, no new risk.

### 4.11 `backend/routes/jobs.py::_resolve_job_input`

Add the import:
```python
from services.unitizer import provenance_for_pasted_text
```

Pasted-text branch — old:
```python
if text_input:
    validate_extracted_text_length(text_input)
    return {
        "input_source_kind": "text",
        "input_text": text_input,
        "input_source_filename": "text_input",
        "input_pdf_gcs_uri": None,
        "input_version": Constants.Pipeline.PIPELINE_VERSION,
        "grading_enabled": True,
    }
```
New:
```python
if text_input:
    validate_extracted_text_length(text_input)
    return {
        "input_source_kind": "text",
        "input_text": text_input,
        "input_source_filename": "text_input",
        "input_pdf_gcs_uri": None,
        "input_provenance": provenance_for_pasted_text(text_input),   # NEW
        "input_version": Constants.Pipeline.PIPELINE_VERSION,
        "grading_enabled": True,
    }
```

Upload branch — old:
```python
return {
    "input_source_kind": "upload",
    "input_text": resolved.text,
    "input_source_filename": resolved.source_filename,
    "input_pdf_gcs_uri": pdf_gcs_uri,
    "input_version": Constants.Pipeline.PIPELINE_VERSION,
    "grading_enabled": True,
    "skipped_files": resolved.skipped_files,
}
```
New:
```python
return {
    "input_source_kind": "upload",
    "input_text": resolved.text,
    "input_source_filename": resolved.source_filename,
    "input_pdf_gcs_uri": pdf_gcs_uri,
    "input_provenance": resolved.provenance,   # NEW
    "input_version": Constants.Pipeline.PIPELINE_VERSION,
    "grading_enabled": True,
    "skipped_files": resolved.skipped_files,
}
```

### 4.12 `backend/utils/firebase.py` — clean up `input_provenance` at job termination

`input_provenance` has exactly the same short lifetime as `input_text` — needed only for one `unitize()` call at pipeline-run time, never again after the job reaches a terminal state. Give it the identical `firestore.DELETE_FIELD` treatment in both `complete_job` and `fail_job`:

`complete_job`, old:
```python
update_fields: dict = {
    "status": "completed",
    "stage": 5,
    "output_data": output_data,
    "name": name,
    "completed_at": now,
    "updated_at": now,
    "input_text": firestore.DELETE_FIELD,
}
```
New:
```python
update_fields: dict = {
    "status": "completed",
    "stage": 5,
    "output_data": output_data,
    "name": name,
    "completed_at": now,
    "updated_at": now,
    "input_text": firestore.DELETE_FIELD,
    "input_provenance": firestore.DELETE_FIELD,   # NEW
}
```

`fail_job`, old:
```python
update_fields: dict = {
    "status": "error",
    "error_data": error_data,
    "completed_at": now,
    "updated_at": now,
    "input_text": firestore.DELETE_FIELD,
}
```
New:
```python
update_fields: dict = {
    "status": "error",
    "error_data": error_data,
    "completed_at": now,
    "updated_at": now,
    "input_text": firestore.DELETE_FIELD,
    "input_provenance": firestore.DELETE_FIELD,   # NEW
}
```

Update both docstrings' "Always clears input_text" language to "Always clears input_text and input_provenance."

### 4.13 Firestore size-budget accounting (substantiating §4.1's recommendation)

Concrete numbers, using this repo's own documented budget (`Constants.Uploads.MAX_TEXT_BYTES`'s comment: "350,000 B leaves a large safety margin below the ~896,576 B actually available for `input_text`"):

- Headroom available beyond `input_text` itself: ~896,576 − 350,000 ≈ **546,576 bytes**.
- A `SourceSpan` entry serializes to roughly 55–75 bytes of JSON (`{"file":"discharge_summary.pdf","page":12,"start_line":4567,"end_line":4598}`), and the number of spans is bounded by the number of (file, page) pairs, not lines — at most `Constants.Limits.MAX_FILE_COUNT = 5` files, each realistically well under a few hundred pages given `MAX_AGGREGATE_FILE_BYTES = 10 MB` total upload size. Even a deliberately pathological 500-span job costs ≈35 KB — about 6% of the available headroom.
- The equivalent `Unit` list (Option 1, rejected) would need to additionally carry every non-blank line's own text a second time — for the same document already contributing up to 350,000 bytes via `input_text`, this is not a small percentage of headroom, it's comparable to `input_text` itself, before per-unit JSON key overhead is even counted.

This is the quantitative case for §4.1's recommendation, not just the qualitative one.

## 5. API Change Summary

`JobDoc`'s Firestore wire shape gains one field during the **processing** window only (never present on a completed or errored doc, §4.12):

| Key | Before | After |
|---|---|---|
| `input_provenance` | did not exist | present while `status in {"not_started", "processing"}`: `list[{file: str, page: int, start_line: int, end_line: int}]`; **deleted** (via `firestore.DELETE_FIELD`) in the same update that sets `status` to `"completed"` or `"error"` — mirrors `input_text`'s existing lifecycle exactly |
| `input_text` | flattened blob, per-file blocks joined with `"\n"`, each prefixed by `"\n\n--- Source: {filename} ---\n"` | flattened blob, per-(file,page) blocks joined with `"\n"`, **no inline marker** — file/page identity now lives structurally in `input_provenance`, not in the text itself |

No other `JobDoc` field changes. `CarePlanInternal`/`output_data` (the only shape that ever reaches an HTTP response, via `GET`-style reads of a completed job doc from the frontend) is **completely unaffected** — `Unit`, `SourceSpan`, and (01's) `Fact` never appear there, by design (brief §3.10: the evidence ledger is not displayed). No route signatures, HTTP status codes, or error shapes change.

## 6. Frontend Change Summary

**N/A.** No frontend file is touched by this PRD, and none needs to be. `input_provenance` never leaves the backend (deleted before a job reaches a state the frontend ever reads — a completed or errored doc never has it), and `Unit`/`SourceSpan` never appear in `output_data`. The frontend's existing behavior (poll a job by ID, read `output_data` once completed) is unaffected in every respect.

## 7. Testing

### 7.1 Files with breaking changes

| File | What breaks | What it should assert instead |
|---|---|---|
| `backend/tests/utils/test_pdf.py::test_extract_text_from_two_page_pdf` | Calls the now-deleted `extract_text_from_pdf` | Rewrite against `extract_pages_from_pdf`: build the same two-page PDF, assert `len(pages) == 2`, `pages[0][0] == 1`, `pages[1][0] == 2`, and that each page's text contains its expected content |
| `backend/tests/utils/test_pdf.py::test_extract_text_from_empty_pdf_returns_empty_string` | Same — deleted function | Rewrite: `extract_pages_from_pdf(pdf_bytes) == []` for a PDF whose only page is blank |
| `backend/tests/services/test_care_plan_input.py::test_extract_text_from_bytes_dotless_filename_raises_simplify_error` | Calls the now-deleted `extract_text_from_bytes` | Rewrite against `extract_pages_from_bytes`, same assertion (`SimplifyError`, `error_code == ErrorCode.UNSUPPORTED_FILE_TYPE`) |
| `...::test_extract_text_from_bytes_still_works_for_txt` | Same | Rewrite: `extract_pages_from_bytes(b"hello world", "notes.txt") == [(1, "hello world")]` |
| `...::test_extract_text_from_bytes_dispatches_image_extensions_to_ocr` | Same | Rewrite: mock `extract_text_from_image` to return `"ocr text"`, assert `extract_pages_from_bytes(b"bytes", "photo.png") == [(1, "ocr text")]` |
| `...::test_extract_text_from_bytes_corrupt_pdf_raises_file_parse_failed` | Same | Rewrite against `extract_pages_from_bytes`, same assertion |
| `...::test_extract_text_from_bytes_empty_pdf_raises_file_parse_failed` | Same | Rewrite against `extract_pages_from_bytes`, same assertion |
| `...::test_extract_text_from_bytes_corrupt_docx_raises_file_parse_failed` | Same | Rewrite against `extract_pages_from_bytes`, same assertion |
| `...::test_resolve_uploaded_files_rejects_extracted_text_containing_lone_surrogate` | Patches `services.care_plan_input.extract_text_from_bytes`, which no longer exists as the call site inside `resolve_uploaded_files` | Patch `services.care_plan_input.extract_pages_from_bytes` instead, returning `[(1, "hello \ud800 world -- padding so this clears MIN_MEANINGFUL_CONTENT_CHARS")]` |
| Every other test in `test_care_plan_input.py` that calls `_resolve(...)`/`resolve_uploaded_files` (blank-file, tolerant-mode, aggregate-limit, image-merge-candidate tests) | Nothing breaks functionally (these assert on `resolved.text`/`resolved.skipped_files` content, unaffected by the marker removal or the return-shape change, since they go through the public `resolve_uploaded_files` API, not the deleted functions directly) | No change required, but add `assert "--- Source:" not in resolved.text` to at least one of them (regression guard for §4.6) |

### 7.2 Files checked and confirmed unaffected

- `backend/tests/utils/test_image_ocr.py` — none of its existing tests assert a specific value for `_MAX_LONG_EDGE_PX`; `test_maybe_downscale_returns_unchanged_for_small_image` uses a 100×100 image, well under either ceiling, so it passes unchanged. New tests are additive (§7.3).
- `backend/tests/utils/test_misc.py` — grepped for `source_separator`: zero references. No change needed.
- `backend/tests/routes/test_jobs.py` — none of its assertions do full-dict equality on the `payload` passed to `create_job_doc` (all are `payload["specific_key"]` lookups); adding `input_provenance` to that dict does not break any of them. Spot-check during implementation, but no rewrite expected.
- `backend/models/ledger.py` (01's `Unit`/`Fact`) — not modified by this PRD; consumed as-is (§4.1's central recommendation was evaluated specifically to avoid needing to diverge from it).

### 7.3 New tests this PRD should add

- **`backend/tests/models/test_provenance.py`** (new) — round-trip a `SourceSpan` through `to_dict()`/`from_dict()`; assert `extra="forbid"` rejects an unknown key. Mirrors 01's own recommendation for a minimal `test_ledger.py`.
- **`backend/tests/services/test_unitizer.py`** (new) — this is where unit-ID stability (the property 03's citation depends on) is actually proven:
  - `test_unitize_assigns_sequential_ids_skipping_blank_lines` — a span whose text has blank lines interspersed produces contiguous `id`s (1, 2, 3, ...) with no gaps, while `line` numbers do skip across the blank lines.
  - `test_unitize_is_deterministic_across_repeated_calls` — call `unitize(text, provenance)` twice with the same arguments; assert the two `list[Unit]` results are element-wise equal (same ids, same order).
  - `test_unitize_line_numbers_reset_per_page` — two spans (two pages of the same file); assert the second span's first unit has `line == 1`, not a continuation of the first span's line count.
  - `test_unitize_multi_file_preserves_distinct_file_identity` — two spans with different `file` values; assert each emitted `Unit.file` matches its own span, not the other's.
  - `test_unitize_empty_provenance_returns_empty_list`.
  - `test_unitize_preserves_verbatim_line_text_including_internal_whitespace` — a line with leading/trailing spaces mid-document is preserved exactly in `Unit.text` (only whole-line-blank lines are dropped, not whitespace trimmed from real lines).
  - `test_unitize_tolerates_span_past_end_of_text` — a deliberately malformed span whose `end_line` exceeds `len(text.split("\n"))`; assert `unitize` returns the units it *can* build rather than raising or crashing (the defensive `break`, per the docstring).
  - `test_provenance_for_pasted_text_single_span_covers_whole_text`.
  - `test_provenance_for_pasted_text_empty_string_returns_empty_list`.
- **`backend/tests/services/test_care_plan_input.py`** additions:
  - `test_resolve_uploaded_files_single_file_produces_one_span_per_page`.
  - `test_resolve_uploaded_files_multi_file_produces_contiguous_non_overlapping_spans_in_order` — the critical partition-invariant test: for a multi-file upload, walk `resolved.provenance` in order and assert `spans[0].start_line == 0`, each subsequent `spans[i].start_line == spans[i-1].end_line + 1`, and the final `spans[-1].end_line == len(resolved.text.split("\n")) - 1`. This is the property `unitize` trusts without re-checking at runtime (§4.8) — it must be enforced here, at the producer.
  - `test_resolve_uploaded_files_pdf_blank_page_omitted_not_renumbered` — a synthetic 3-page PDF (reportlab) with a genuinely blank middle page; assert the resulting spans' `page` values are `[1, 3]`, not `[1, 2]`.
  - `test_resolve_uploaded_files_omits_source_separator_marker_from_combined_text` (§7.1, regression).
  - `test_resolve_units_from_job_doc_round_trips_through_a_job_doc_shaped_object` — build a minimal object (or real `JobDoc`) with `input_text`/`input_provenance` set from a `resolve_uploaded_files` call, pass it through `resolve_units_from_job_doc`, and assert the resulting `list[Unit]` matches calling `unitize` directly on the same `(text, provenance)` pair — proves the round trip through the `JobDoc` model doesn't lose or reorder anything.
- **`backend/tests/utils/test_image_ocr.py`** additions:
  - `test_max_long_edge_is_4096`: `from utils.image_ocr import _MAX_LONG_EDGE_PX; assert _MAX_LONG_EDGE_PX == 4096`.
  - `test_maybe_downscale_leaves_image_between_old_and_new_ceiling_unchanged` — an image sized ~3000px long edge: under the new ceiling, `_maybe_downscale` must return it unchanged (regression-proof that the ceiling actually moved — under the *old* 2048 ceiling this image would have been downscaled).
  - `test_maybe_downscale_still_downscales_image_over_new_ceiling` — an image over 4096px long edge is thumbnailed to `<= 4096`.
- **`backend/tests/utils/test_pdf.py`** additions (beyond the two rewrites in §7.1):
  - `test_extract_pages_from_pdf_page_numbers_are_one_indexed_in_document_order`.
- **`backend/tests/routes/test_jobs_e2e_scenarios.py`** additions:
  - Extend `TestScenario1TypicalDischargeSummary::test_full_chain_completes_and_final_doc_is_safe_and_small` and/or `TestScenario4MultibyteNearLimits::test_mixed_multibyte_just_under_both_caps_completes_and_stays_under_1mib` with `assert "input_provenance" not in doc` alongside the existing `assert "input_text" not in doc` — proves §4.12's cleanup actually lands on the completed-doc path. The existing `_doc_size_bytes(doc) < 1_048_576` assertions need no threshold change (§4.13 shows the added field's processing-time footprint is small, and it's gone entirely by the time these size assertions run against the *completed* doc).
  - One new small test asserting the **processing-state** doc (read via `fake_db.raw_doc(...)` immediately after `POST /jobs`, before the worker runs) contains a non-empty `input_provenance` for a multi-file upload — proving §4.11's wiring actually persists it, not just that it gets cleaned up later.

## 8. Manual Intervention Required From You

- **OCR ceiling smoke test.** Run a real end-to-end test via ngrok + pm2 (`SERVICE_MODE=combined`, per this repo's local-testing convention) with a genuine multi-page scanned/photographed document containing small print (a medication list with decimal dosages and drug-name suffixes is the worst case the brief specifically cites). Confirm (a) the OCR call completes without a Vertex payload-size or timeout error at the new 4096px ceiling, and (b) transcription of small text visibly improves versus the same page at the old 2048px ceiling. This is a qualitative check no automated test in this sub-project can perform (clinical-fidelity evaluation is explicitly out of scope everywhere per the brief).
- **Vertex AI inline-request limits.** This PRD's payload-size reasoning (§4.5) is based on the existing 10 MB upload cap and general knowledge of Gemini's inline-request handling, not a live check against current Vertex AI documentation/quotas — worth a quick confirmation on your end if you want certainty beyond the smoke test above before this reaches production traffic.

Nothing else in this sub-project requires action only you can take — no new environment variables, no console configuration, no credentials.

## 9. Open Questions & Decisions

- `[RESOLVED: provenance survives the API→worker boundary as a compact SourceSpan map (JobDoc.input_provenance), persisted alongside the already-persisted input_text; the full list[Unit] is materialized in the worker by the pure function services.unitizer.unitize, and is never itself persisted to Firestore.]` — see §4.1 for the full option analysis and §4.13 for the quantitative size justification. This was the task's own "central design problem"; resolved in favor of the option that adds the least Firestore-document risk while reusing data the worker already reads.
- `[RESOLVED: a Unit's "line" is one "\n"-delimited line of whatever text that source type's own extractor already produces, page-scoped for PDF, whole-file-as-page-1 for TXT/DOCX/HTML/images, whole-paste-as-page-1 for pasted text.]` — see §4.2's table, directly answering the task's "confirm what a line means for each source type."
- `[RESOLVED: blank/whitespace-only lines get no Unit (and no id), but still consume a slot in the line-index accounting, so Unit.line stays a faithful page-relative count.]` — keeps `Unit.id` contiguous (no gaps a citation-consumer would need to explain) while keeping `Unit.line` meaningful to a human matching it against the source page.
- `[RESOLVED: pasted text's Unit.file is the literal string "text_input", reusing the existing sentinel already used for input_source_filename and already special-cased in utils.misc.derive_output_name, rather than inventing a new convention.]`
- `[RESOLVED: extract_text_from_pdf and extract_text_from_bytes (the old flat-string functions) are deleted outright, not kept as thin backward-compatible wrappers around the new page-aware functions.]` — this is the one place this PRD goes slightly beyond the task brief's literal file list. Once `resolve_uploaded_files` needs page boundaries, the flat-string functions have zero remaining production callers (grep-confirmed) and would survive only to avoid rewriting ~9 existing tests. The parent brief repeatedly argues against exactly this pattern elsewhere (deleting `RawArtifacts`, the `Enums` container class, `JobDoc.shared` — each justified by "no remaining consumer," not "how many tests reference it"). Rewriting the ~9 affected tests (§7.1) against the new functions was judged the more consistent choice; if this is unwanted churn, the alternative (keep both old functions as one-line wrappers, e.g. `extract_text_from_pdf(b) = "\n\n".join(t for _, t in extract_pages_from_pdf(b))`) is a strictly smaller, mechanical change that a future task could make instead without touching anything else in this PRD.
- `[RESOLVED: SourceSpan lives in a new backend/models/provenance.py, not inside 01's models/ledger.py alongside Unit/Fact.]` — different persistence lifecycle (SourceSpan is written to Firestore; Unit/Fact never are) is reason enough to keep them visually and structurally separate, mirroring 01's own reasoning for keeping `ledger.py` out of `models/care_plan/`.
- `[RESOLVED: SourceSpan.start_line/end_line are 0-indexed (direct Python list-index convention); Unit.line is 1-indexed and page-relative (a distinct, human-facing convention).]` — the two fields answer different questions; forcing one indexing convention across both would make one of them wrong for its purpose. Documented explicitly in both models' docstrings so a future reader doesn't assume they match.
- `[RESOLVED: no per-page minimum-content-length check is added alongside the new per-page validate_text_storable call (§4.7) — Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS stays a file-level check only, as today.]` — a legitimately short page (a one-line divider or cover page) should not be rejected; the brief doesn't ask for this, and adding it would change accept/reject behavior for real documents, not just refactor internals.
- `[DEFERRED: DOCX "line" granularity is one Unit per non-empty paragraph, which means content inside DOCX tables (python-docx's `.paragraphs` API does not walk table cells) is invisible to the unitizer exactly as it is invisible to today's flat-text extraction.]` — a pre-existing limitation of the DOCX extraction path, not something this PRD changes or worsens. Worth a future PRD if DOCX tables turn out to carry clinically load-bearing content in practice, but out of this sub-project's scope.
- `[DEFERRED: what 03 (grounding) does when a single page's text produces an unusually large number of Units — e.g. a densely tabular or garbled-OCR page — such as prompt-size management or a per-unit count cap.]` — this PRD's contract is "produce accurate Units for every non-blank line," not "bound how many Units a pathological page produces." Flagged for 03's author, since it concerns how the line-numbered original gets rendered into a grounding prompt, not how it's unitized.
- `[DEFERRED: persisting SourceSpan/Unit anywhere longer-term (e.g. for the future clinical-fidelity evaluation harness) is out of scope]` — same reasoning as 01's identical deferral for the ledger: that harness is itself explicitly deferred, and building storage for a consumer that doesn't exist yet is exactly the speculative surface the brief argues against.
- `[OPEN]` — none remaining that block `dev-tasks` from generating tasks for this sub-project deterministically. The two items in §8 are manual verification/smoke-test steps, not decisions this PRD left unmade.
