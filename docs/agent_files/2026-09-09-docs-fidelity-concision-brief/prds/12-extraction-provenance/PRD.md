# PRD 12 — Extraction Provenance

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially §2 and the OCR-ceiling decision row in §2's table). Source research: `comparison-drive-research-bundle.v1.md` §5 R4, §4.1.
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (schema-and-config — `models/ledger.py`'s `Unit`), 02 (unitization-and-provenance — `SourceSpan`, `unitize()`, `provenance_for_pasted_text()`, the OCR downscale-ceiling change), 09 (input-transport — `JobInputPayload`, `upload_job_input`/`load_job_input`, the GCS transport this PRD's payload-shape note applies to).

Depended on by: 16/17 (technical/scientific documentation — will document whatever this PRD lands on). No other sub-project in this batch reads `extraction_method`; PRD 10 (numeric-integrity) and 11 (omission-signal) are independent log-only signals living in the same files (`care_plan/pipeline.py`, `utils/constants.py`'s `LOG_EXTRA_KEYS`) and are called out at the relevant merge seams below, but neither depends on this PRD's field.

## 1. Problem

Grounding's evidence check (`_is_verbatim_quote` in `backend/care_plan/pipeline.py`) verifies that a fact's quote is a substring of its cited unit's text. That check answers "did the model quote the text in front of it correctly" — it says nothing about whether the text in front of it was *itself* correct. A `Unit` built from a garbled OCR scan and a `Unit` built from crisp native PDF text are structurally identical: same four fields (`id`, `file`, `page`, `line`, `text`), no method tag, no confidence signal, nothing distinguishing "the model transcribed this from a photograph" from "this came straight out of a PDF's text layer."

This is the specific gap the parent brief calls out as uniquely dangerous: a plausible OCR misread — "5 mg" scanned as "6 mg," "hydralazine" scanned as "hydroxyzine" — produces a unit whose text is simply wrong, but internally consistent. Grounding quotes it verbatim (passes `_is_verbatim_quote` with complete certainty, because the check only asks "is this a substring," never "was this substring reliably produced"). Review compares the assembled plan against that same wrong transcription, not against the original photo, so it agrees. Every deterministic guard in the pipeline (`_is_verbatim_quote`, `_is_informative_quote`, review's coverage check, correct's path validation) is validating internal consistency between stages, and a bad OCR read is consistent with itself at every stage. The brief names this "the only failure mode in the whole design invisible to every other safeguard."

**Verified: nothing in the current codebase carries extraction method past the point where it's known.**

```
$ grep -rn "extraction_method\|extraction method\|via_ocr\|source_method" backend --include=*.py
(no matches)
```

`resolve_uploaded_files` (`backend/services/care_plan_input.py`) knows, per file, whether it called `extract_text_from_image` (OCR) or one of the native extractors (`extract_pages_from_pdf`, the TXT/DOCX/HTML branches) — that branch decision is made and then thrown away the moment the function returns `ResolvedInput`. `SourceSpan` (`backend/models/provenance.py`) — `{file, page, start_line, end_line}` — has no field for it. `Unit` (`backend/models/ledger.py`) — `{id, file, page, line, text}` — has no field for it either. By the time grounding runs, there is no way to ask "was this text OCR'd," at any granularity, for any unit.

**This PRD closes that visibility gap and nothing else.** It threads a three-way `extraction_method` tag from the two points that already know it, through the one existing carrier (`SourceSpan` → `Unit`), to a small set of log statements. It is explicitly **not** a confidence score, a quality signal, or a fidelity check. `extraction_method: "ocr"` tells a human reading logs that a fact's evidence came from a transcription step, not from the document's own text layer — it says nothing about whether that transcription was accurate. A perfect OCR read and a badly garbled one both get tagged `"ocr"`, indistinguishably. This is a **triage signal for a human**, pointing an investigator (reviewing a specific complaint, auditing a sample of runs, deciding whether to raise the OCR ceiling again) at which facts are worth double-checking against the original document — it is not, and must never be read as, evidence that any specific fact is right or wrong. Per the initiative's locked decisions, this is log-only and non-gating: nothing about what ships to a patient changes based on this tag.

## 2. Goals

- Add `extraction_method: Literal["native", "ocr", "pasted"]` to `SourceSpan` and to `Unit`, populated at both producers (`resolve_uploaded_files`, `provenance_for_pasted_text`) and threaded through `unitize()` as a pure copy — no inference, no heuristics, no "guess from the text's shape."
- Establish, precisely, the actual granularity available: per-file for uploads (§4.2 shows why per-page is not a real distinction today), per-job for pasted text.
- Make the resulting signal observable in two places: a per-run aggregate (unit-level, always-on) and a fact-level aggregate at grounding time — both `logger.info`, both log-only, neither gating anything.
- Decide, and justify, whether the grounding prompt should see the tag. (It should not — §4.6.)
- Document the GCS `JobInputPayload` shape change this field causes, and say plainly that no migration is needed (§4.7) — payloads are per-job, short-lived, and there is no cross-version compatibility requirement anywhere in this initiative.

## 3. Non-Goals

- **No confidence score, no quality score, no OCR-accuracy estimate.** `extraction_method` records *how* a unit's text was produced, never *whether* it was produced correctly. Nothing in this PRD attempts to detect a misread — that would require comparing the transcription against ground truth, which no part of this pipeline has access to. Restated because it is the single most likely way this feature gets misread later: `"ocr"` is not `"low confidence"`.
- **No gate, disposition, hold, or abstain.** Per the initiative's locked decisions, this signal is log-only. A document composed entirely of OCR'd units ships exactly as it would today — this PRD changes nothing about the pipeline's output, only what gets logged alongside it.
- **No patient-facing surface.** `extraction_method` never appears in `CarePlan`, `output_data`, or any API response, for the same reason `Unit`/`Fact`/`SourceSpan` themselves never do (brief §3.10; `_strip_internal_provenance` in `routes/worker.py` already exists to keep pipeline-internal identifiers out of what a patient's browser reads).
- **No change to the grounding, assembly, review, or correct prompts' instructions or the pipeline's four-call shape.** The pipeline is exactly `ground → assemble_and_render → review → correct`; this PRD adds a fifth field to two existing models and some `logger.info` calls, not a fifth call. §4.6 argues explicitly against exposing the tag to the grounding prompt.
- **No per-page OCR fallback for PDFs.** §4.2 confirms, by reading `extract_pages_from_pdf`, that no such fallback exists today (a page with no text layer is silently omitted, never OCR'd) — this PRD does not add one. If a future PRD adds page-level OCR fallback for PDFs, `SourceSpan`'s existing per-(file, page) granularity already has room for a per-page `extraction_method` without further schema change; this PRD just doesn't need it yet, because the fallback doesn't exist yet.
- **No retroactive tagging of anything.** No migration, no backfill, no dual-shape reading of an old `JobInputPayload` — see §4.7 for why this is a non-issue given the payload's lifecycle.
- **No versioning.** `SourceSpan.extraction_method` and `Unit.extraction_method` are added as plain required fields, mutating both schemas in place, per the global constraint.

## 4. Architecture Decisions

### 4.1 The three-way `Literal` — why `"pasted"` is its own member, not folded into `"native"`

`Literal["native", "ocr", "pasted"]`, not the binary `Literal["native", "ocr"]` the task brief's own phrasing ("`native`/`ocr`") might suggest at first read.

Reasoning: `"native"` and `"ocr"` both describe an *extraction step that ran* — one deterministic (PyPDF2/python-docx/BeautifulSoup pulling text out of a structured file), one model-mediated (Gemini vision transcribing a photo). Pasted text has no extraction step of any kind — the user's own literal keystrokes are the text, with zero transformation between what they typed and what `Unit.text` holds. Folding pasted text into `"native"` would be a category error: it isn't that pasted text's extraction is reliable, it's that there is no extraction to be unreliable. Collapsing the distinction would also quietly overstate `"native"`'s aggregate count in the per-run log (§4.5) with units that never went through any of the code paths `"native"` is meant to describe, muddying exactly the signal this PRD exists to produce.

This also lines up with `provenance_for_pasted_text` already being "its own producer" (per this task's framing) and already using its own sentinel filename convention (`"text_input"`, PRD 02 §4.2) rather than reusing an upload convention — `extraction_method="pasted"` is the same move one level down, at the method tag instead of the filename.

`SourceSpan`/`Unit`'s `extraction_method` field:

```python
from typing import Literal

ExtractionMethod = Literal["native", "ocr", "pasted"]
```

Placed in `backend/models/provenance.py` (where `SourceSpan` already lives) and imported into `backend/models/ledger.py` for `Unit` — a type alias, not a duplicate `Literal` spelled out twice, so the two models cannot drift apart on which three strings are valid. `FactCategory` (`models/ledger.py`) is the closest existing precedent for a small `Literal` alias living at module scope for reuse; `ExtractionMethod` follows the same pattern but crosses module boundaries (defined in `provenance.py`, imported by `ledger.py`) because `SourceSpan` is `ExtractionMethod`'s "owning" model in the same sense `provenance.py`'s docstring already claims ownership of the whole provenance design.

### 4.2 Granularity — confirmed per-file for uploads, no per-page PDF fallback exists

The task asks explicitly whether a PDF's per-page OCR fallback exists, since if it did, `extraction_method` would need to vary *within* a single PDF's spans. Checked directly against the code:

```python
# backend/utils/pdf.py — extract_pages_from_pdf, in full (reproduced from the actual file)
def extract_pages_from_pdf(pdf_content: bytes) -> list[tuple[int, str]]:
    reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
    pages: list[tuple[int, str]] = []
    for page_num, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text and page_text.strip():
            pages.append((page_num + 1, page_text.strip()))
    ...
    return pages
```

There is no call to `extract_text_from_image`, no image rendering of the page, no branch of any kind here for a page whose `extract_text()` comes back empty — that page is simply **omitted from the returned list**, per its own docstring: *"a page with none [no extractable text] is omitted, NOT renumbered."* `extract_pages_from_bytes` (`backend/services/care_plan_input.py`), the single dispatcher that calls this, confirms the same: its `ext == "pdf"` branch calls `extract_pages_from_pdf` and nothing else; OCR is reachable only from the separate `ext in Constants.Uploads.IMAGE_EXTENSIONS` branch, which calls `extract_text_from_image` on the *whole uploaded file's bytes*, never on a rendered PDF page. **Confirmed: no per-page OCR fallback exists.** A PDF is either usable in its native, per-page-extracted form (some pages may be silently dropped for having no text layer, but the pages that remain are all natively extracted — never a mix of native and OCR'd pages within one PDF), or, if *every* page comes back empty, the whole file fails `MIN_MEANINGFUL_CONTENT_CHARS` and is rejected/skipped as `EMPTY_DOCUMENT` before any `SourceSpan` for it is ever created (§4.3).

This means the real granularity of `extraction_method`, given today's code, is **per-file**, not truly per-`(file, page)` — every page of one PDF/TXT/DOCX/HTML file is `"native"`; every page of one image file is `"ocr"` (always page 1, per PRD 02 §4.2's table — an image has no page concept). The field is still placed on `SourceSpan` (the per-`(file, page)` model) rather than hoisted to some new per-file structure, for three reasons: (1) `SourceSpan` is already the exact granularity a future per-page fallback would need, so this PRD doesn't have to be revisited if one is ever added (§3's non-goal note); (2) it keeps `extraction_method` next to the `file`/`page` fields it's a property of, rather than inventing a second, parallel per-file lookup a consumer would have to join back against spans/units anyway; (3) it costs nothing extra today — every span of a given file gets the same value, computed once per file (§4.3), not once per span.

**What genuinely does vary within one job: files.** A single upload can mix a natively-extracted PDF with a photographed page (`resolve_uploaded_files` accepts up to `Constants.Limits.MAX_FILE_COUNT = 5` files of any allowed mix of types) — this is the real "mixed-method upload" case, and it is handled correctly by computing `extraction_method` per file inside the existing per-file loop (§4.3), not per job.

### 4.3 Producer 1: `backend/services/care_plan_input.py::resolve_uploaded_files`

`resolve_uploaded_files` already branches per file by extension inside `extract_pages_from_bytes` (dispatches to `extract_pages_from_pdf`, the TXT/DOCX/HTML inline branches, or `extract_text_from_image`) — it just never records which branch a given file took. Add one small helper, and one call to it per file, in the same loop that already builds each file's `SourceSpan`s:

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

Call site — inside the existing per-file loop, computed once per file (not once per page, since it's the same value for every page of one file — §4.2):

Old (the per-page `SourceSpan`-building block, reproduced from the actual file):
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
```

New:
```python
filenames.append(filename)
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
```

Note `ext = _get_extension(filename)` already exists a few lines below this block in the current source (used for the merge-candidate branch); it must be computed **before** this new line instead, since `_extraction_method_for_ext` needs it here. Moving that one `ext = _get_extension(filename)` line up costs nothing — it's a pure function of `filename`, already computed with no side effects, just currently positioned slightly later in the function than this new call needs it.

A file that is skipped entirely (`tolerate_unusable_files`, corrupt/unsupported/empty) never reaches this block — correctly, since a skipped file contributes no `SourceSpan` at all today, and this PRD doesn't change that.

### 4.4 Producer 2: `backend/services/unitizer.py::provenance_for_pasted_text`

The simpler of the two producers — always exactly one method, no branching:

Old:
```python
def provenance_for_pasted_text(text: str, *, file: str = "text_input") -> list[SourceSpan]:
    if not text:
        return []
    line_count = len(text.split("\n"))
    return [SourceSpan(file=file, page=1, start_line=0, end_line=line_count - 1)]
```

New:
```python
def provenance_for_pasted_text(text: str, *, file: str = "text_input") -> list[SourceSpan]:
    if not text:
        return []
    line_count = len(text.split("\n"))
    return [SourceSpan(
        file=file, page=1, start_line=0, end_line=line_count - 1,
        extraction_method="pasted",
    )]
```

### 4.5 `backend/models/provenance.py` — `SourceSpan.extraction_method`

```python
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import JsonModel

ExtractionMethod = Literal["native", "ocr", "pasted"]


class SourceSpan(JsonModel):
    """One contiguous, 0-indexed, inclusive range of global line indices --
    into the combined document's ``split("\\n")`` result -- attributed to
    one (file, page).

    ...(unchanged docstring body)...
    """

    file: str
    page: int
    start_line: int
    end_line: int
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

No default value — required, like every other field on `SourceSpan`. Both producers (§4.3, §4.4) always know the correct value at construction time; there is no legitimate `SourceSpan` construction site in production code where it would be unknown. (§7 covers the resulting test-fixture churn — every existing `SourceSpan(...)` call site must now pass this field.)

`JobInputPayload` in this same file needs **no** field change — it already carries `provenance: list[SourceSpan]`, so `extraction_method` rides along automatically as part of each `SourceSpan`'s own serialization. (Its *wire shape* still changes, because `SourceSpan`'s shape changed — see §4.7.)

### 4.6 `backend/models/ledger.py` — `Unit.extraction_method`, and threading it through `unitize()`

```python
from .provenance import ExtractionMethod


class Unit(JsonModel):
    """... (unchanged docstring body, plus:) `extraction_method` is copied
    verbatim from the SourceSpan that produced this Unit (services.
    unitizer.unitize) -- never inferred, re-derived, or defaulted here.
    See models.provenance.SourceSpan.extraction_method and PRD 12 for the
    full design; this is a pure carrier field on Unit, exactly like
    `file`/`page` already are."""

    id: int
    file: str
    page: int
    line: int
    text: str
    extraction_method: ExtractionMethod
```

`backend/models/ledger.py` gains one new import: `from .provenance import ExtractionMethod`. This is a new dependency direction — `ledger.py` did not previously import from `provenance.py` — but it is not a cycle: `provenance.py` imports only from `.base`, never from `.ledger`, so `ledger.py -> provenance.py -> base.py` is a clean one-way chain. Worth naming explicitly in the PRD because `provenance.py`'s own docstring currently frames the two modules as siblings with deliberately separate lifecycles (§4.3 of PRD 02: "unlike Unit/Fact, [SourceSpan] IS persisted... Co-locating a persisted model with two pipeline-internal-only models would blur that distinction") — this import doesn't blur that distinction (`SourceSpan` still isn't moving into `ledger.py`, and `Unit` still never touches Firestore/GCS directly), it just means `ledger.py` now depends on one small type alias from `provenance.py` rather than the two files being mutually unaware of each other.

`unitize()` (`backend/services/unitizer.py`) — the pure copy, exactly where the task specifies (no inference):

Old:
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

That is the entire change to the copy loop itself. (The aggregate-logging addition to this same function is §4.8, below — kept as a separate diff here so the "pure copy, no inference" change reads on its own.)

### 4.7 The GCS payload shape change — no migration, and why none is needed

`JobInputPayload` (`backend/models/provenance.py`, added by PRD 09) is the JSON object `upload_job_input` writes to `gs://.../care_plan_inputs/{user_id}/inputs/{object_id}.json` and `load_job_input` reads back — `{text: str, provenance: list[SourceSpan]}`. Because `SourceSpan` gains a required field, every serialized `SourceSpan` inside that JSON array gains a key:

Before:
```json
{"file": "discharge.pdf", "page": 2, "start_line": 40, "end_line": 55}
```
After:
```json
{"file": "discharge.pdf", "page": 2, "start_line": 40, "end_line": 55, "extraction_method": "native"}
```

Both `JobInputPayload` and `SourceSpan` are `JsonModel` subclasses (`extra="forbid"`, per `backend/models/base.py`) with no default on the new field. This has one concrete operational consequence, and this PRD's position on it is: **not a problem, no migration needed, explicitly.**

- **Why it could theoretically matter:** if a payload object written by an *old* build of the API (pre-this-PRD, no `extraction_method` key) were read back by a *new* build of the worker (post-this-PRD, field required), `JobInputPayload.from_dict` would raise `ValidationError`, and `load_job_input` wraps that in `SimplifyError(ErrorCode.PIPELINE_ERROR)` — the job fails cleanly (not a crash, an actual `fail_job` call), but it does fail.
- **Why this doesn't matter here:** the object is written and read by the *same job's* API and worker processes, typically seconds to low minutes apart (`Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S` bounds the whole pipeline run), and the object itself is deleted at job completion/failure and additionally backstopped by the `care_plan_inputs/` prefix's 1-day GCS lifecycle rule (PRD 09 §4.4) regardless. There is no durable, cross-deploy population of these objects sitting around for a version-skew window to matter — this is exactly the "no versioning, no backward compatibility, no migration code" global constraint applied to a case where the object's own lifetime already makes a migration path pointless, not a case where the constraint is being invoked to skip work that's actually needed. The only realistic exposure window is a rolling deploy landing mid-flight for a job that was already in progress when the deploy started — the same pre-existing exposure every prior in-place schema mutation in this initiative already carries (e.g. PRD 09's own removal of `input_text`/`input_provenance` from `JobDoc` had the identical shape-changes-under-a-live-job risk, and this repo's explicit no-backward-compat, no-preview-environment posture already accepts that class of risk as normal for how this app deploys).
- **No `extra="ignore"` relaxation, no default value added "just to be safe."** Adding a default (e.g. defaulting `extraction_method` to `"native"` for an old payload missing the key) would silently mislabel a genuinely-unknown-provenance record as `"native"` — actively worse than a clean, loud failure, since it would corrupt exactly the signal this PRD exists to produce with zero visible indication that it happened. A hard failure on a genuinely malformed/stale payload is the correct behavior, and `load_job_input` already has that failure mode wired up for every other kind of payload corruption (missing URI, 404, malformed JSON, schema mismatch — see `backend/tests/services/test_care_plan_input.py`'s existing `test_load_job_input_raises_pipeline_error_on_schema_mismatch`); this is one more instance of a pattern the code already handles, not a new failure class.

### 4.8 Consumption — what this PRD logs, and where

Per the initiative's locked decisions, this is **log-only, no gate** — the two aggregates below are the entire "consumption" story. Following PRD 11 (omission-signal)'s already-established structured-logging pattern in this same file/whitelist, for consistency across this batch's log-only signals.

**4.8.1 Unit-level aggregate — `services/unitizer.py::unitize()`, always-on, before every fact is even extracted.**

This is the earliest point the signal is fully known — before grounding runs at all, so it's available even for a job that fails partway through the pipeline (a job that times out or errors during `assemble_and_render` still gets its input's OCR-reliance logged, since `unitize()` runs first). Precedent for a "pure" extraction function also logging a side-channel aggregate about its own output already exists in this exact area of the codebase — `utils/pdf.py::extract_pages_from_pdf` ends with `logger.info("pdf_extract: %d total chars from %d of %d pages", ...)` despite otherwise being a straightforwardly pure function; this follows the same house pattern rather than inventing a new one.

```python
import logging
from collections import Counter
...
logger = logging.getLogger(__name__)


def unitize(text: str, provenance: list[SourceSpan]) -> list[Unit]:
    """... (unchanged docstring, plus:) Logs one INFO-level aggregate of
    `extraction_method` counts across the emitted units before returning
    (PRD 12 SS4.8) -- log-only, never affects the returned list.
    """
    lines = text.split("\n")
    units: list[Unit] = []
    next_id = 1
    for span in provenance:
        for offset, global_idx in enumerate(range(span.start_line, span.end_line + 1)):
            if global_idx >= len(lines):
                break
            line_text = lines[global_idx]
            if not line_text.strip():
                continue
            units.append(Unit(
                id=next_id,
                file=span.file,
                page=span.page,
                line=offset + 1,
                text=line_text,
                extraction_method=span.extraction_method,
            ))
            next_id += 1
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

**4.8.2 Fact-level aggregate — `care_plan/pipeline.py::ground()`, after verification, before the empty-ledger check.**

The unit-level aggregate (§4.8.1) answers "how much of the *source document* is OCR'd." This one answers the sharper question: "how much of what actually became a *cited, patient-facing fact* rests on OCR'd text" — the two numbers can diverge (an OCR'd unit that's never cited by any fact contributes to the first count and not the second; a document that's mostly native but whose one OCR'd page happens to be exactly where the medication list lived would show a small §4.8.1 `ocr_rate` next to a much larger §4.8.2 one). Both are worth having; neither substitutes for the other.

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

Call site inside `ground()` (`backend/care_plan/pipeline.py`), immediately after the existing `_verify_ledger` call and before the existing empty-ledger check:

Old:
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

`{u.id: u for u in units}` is recomputed here rather than plumbed out of `_verify_ledger` (which already builds an identical `units_by_id` internally) — cheap (units per job are bounded by document size, not a hot loop), and keeps `_verify_ledger`'s signature/return type (`list[Fact]`) untouched, per this PRD's non-goal of not touching grounding's existing contract with its caller.

**4.8.3 `_verify_ledger`'s existing per-fact drop warnings gain `extraction_method` — the one place this PRD extends existing logging rather than adding new logging.**

The task explicitly asks whether grounding's *existing* per-fact logging should include the tag. It should, for exactly two of its three warnings — the two where a specific unit's text is already in scope and directly relevant to *why* the drop happened:

Old:
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

The third warning (`unit is None` — cites a nonexistent `unit_id`) is **not** changed: there is no unit to read a method from in that branch (the whole point of that branch is that the cited id doesn't resolve), so there is nothing to add.

Why this specific pair is worth extending (and why it's the "log-only, non-gating" boundary staying intact): a verbatim-quote drop against an OCR'd unit is a materially different event from the same drop against a natively-extracted unit — the former is plausibly *the exact failure mode this whole PRD exists to make visible* (the model quoted what it read; what it read may have been a misread; the quote-verification check then correctly rejects a quote that doesn't match the — possibly wrong — unit text, for a reason that has nothing to do with the model's behavior). The latter is more likely a genuine model deviation from its own cited text. Today both log identically; a human triaging a spike in dropped facts has to go dig up the source document to tell them apart. This is a **strictly additive, no-behavior-change** edit: nothing about which facts get dropped changes, nothing about the drop-and-continue policy changes, only the log line's diagnostic content changes.

### 4.9 New `Constants.Observability.LOG_EXTRA_KEYS` entries

`observability/logging_config.py`'s `StructuredJsonFormatter.format()` only copies an `extra` key into the emitted Cloud Logging JSON payload if it's listed in `Constants.Observability.LOG_EXTRA_KEYS` (`utils/constants.py:164-171`) — confirmed by reading that file directly (same mechanism PRD 11 §4.3 documents for its own `coverage_signal` key). Without an entry, `extra={"extraction_signal": {...}}` is silently dropped from structured (production) log output while still appearing to work in local/plain-text logging — the same footgun PRD 11 calls out. This PRD adds two entries (both dict-valued; `StructuredJsonFormatter` passes them straight to `json.dumps(log_entry, default=str)`, no flattening needed):

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

**Merge-seam note for whoever implements this alongside PRD 10/11:** PRD 11 independently adds `"coverage_signal"` to this same list; PRD 10 does not add a `LOG_EXTRA_KEYS` entry (confirmed by reading PRD 10 §4.4 — it logs via a differently-scoped mechanism). If 10/11/12 are implemented as separate, sequential tasks against this one list (as this initiative's own dev-tasks/dev-code workflow does), each addition is a small, independent, non-conflicting append — flagged here only so whoever lands second or third doesn't assume their diff against this list is the *only* pending change to it (§9).

### 4.10 The grounding prompt does **not** see `extraction_method` — `_format_units_for_prompt` is unchanged

The source research bundle (§5 R4) suggests the tag could be shown to the grounding model as context, e.g. rendering `[47, OCR] Pt to cont. metoprolol...` instead of the current `[47] Pt to cont. metoprolol...`. **Decision: do not do this.**

`_format_units_for_prompt` (`backend/care_plan/pipeline.py`) stays exactly as it is:

```python
def _format_units_for_prompt(units: list[Unit]) -> str:
    lines: list[str] = []
    current_key = None
    for unit in units:
        key = (unit.file, unit.page)
        if key != current_key:
            lines.append(f"=== {unit.file}, page {unit.page} ===")
            current_key = key
        lines.append(f"[{unit.id}] {unit.text}")
    return "\n".join(lines)
```

The argument for showing it: the model, seeing `[47, OCR]`, could in principle hedge its transcription or flag likely-garbled content itself. The argument against, which this PRD adopts:

1. **This is the exact risk PRD 02 already rejected for `IMAGE_OCR_PROMPT` itself**, on record: *"`IMAGE_OCR_PROMPT` is unchanged, per the brief's explicit instruction ('Leave `IMAGE_OCR_PROMPT` unchanged... adding illegibility markers invites mid-transcription editorialising')"* (PRD 02 §4.5). Grounding's units block is the *next* prompt downstream of the OCR transcription — showing an `[OCR]` marker there is functionally the same temptation one hop later: it invites the grounding model to editorialize about legibility/reliability in a step whose entire job is "extract atomic facts and cite them," not "assess transcription quality."
2. **It threatens the soundness contract's own verification mechanism.** The evidence contract (this initiative's locked decision) is soundness: every emitted item cites a real fact, verified by `_is_verbatim_quote` doing an exact (normalized) substring match against the unit's raw text. A model that sees `[47, OCR]` and starts hedging — paraphrasing instead of quoting verbatim, adding a qualifier like "per the (possibly OCR'd) note," second-guessing a dose it would otherwise have quoted cleanly — produces exactly the kind of non-literal quote `_is_verbatim_quote` is designed to reject. The tag would then actively work against the very check meant to catch a bad OCR read, by giving the model a reason to paraphrase around text it's been told to be suspicious of, right before the one deterministic gate that depends on it not doing that.
3. **It would not make the LOG-ONLY signal more useful, and might make it less trustworthy.** `extraction_method` is consumed exclusively by deterministic code (§4.8) reading `Unit.extraction_method` directly — it has no dependency on the model having seen the tag. Exposing it to the model changes the model's *behavior* on OCR'd content (in an unpredictable, unmeasured direction — clinical-fidelity evaluation of that behavior change is explicitly out of scope everywhere in this initiative) for zero improvement to a signal that already works correctly without it.
4. **Determinism.** `_format_units_for_prompt`'s current output is a pure function of `(unit.id, unit.file, unit.page, unit.text)`. Adding `unit.extraction_method` to the rendered line is harmless to determinism in isolation, but the *reason* to add it (inviting a model response to the tag) is precisely what this PRD is arguing against — there's no "expose it but tell the model to ignore it" middle ground worth the added prompt-surface risk for a log-only feature.

`[RESOLVED]`, recorded in §9: `extraction_method` is a code-only signal. `_format_units_for_prompt`, `_GROUND_PROMPT`, and every other prompt template in `backend/care_plan/prompts/` are untouched.

## 5. API Change Summary

No HTTP route, request/response shape, status code, or error code changes. The only wire-format change is the internal GCS `JobInputPayload` object (§4.7):

| Object | Before | After |
|---|---|---|
| `gs://.../care_plan_inputs/{user_id}/inputs/{object_id}.json` (`JobInputPayload`, written by `upload_job_input`, read by `load_job_input`) | `{"text": ..., "provenance": [{"file", "page", "start_line", "end_line"}, ...]}` | `{"text": ..., "provenance": [{"file", "page", "start_line", "end_line", "extraction_method"}, ...]}` |

`JobDoc`'s Firestore shape is completely unaffected — `input_payload_gcs_uri` (the only surviving pointer to this object on the job doc, per PRD 09) is an opaque URI string; the object it points at changing shape doesn't change the job doc at all. `CarePlanInternal`/`output_data` (the only shape that ever reaches an HTTP response) is unaffected for the same reason it was unaffected by PRD 02/09: `Unit`, `SourceSpan`, and `Fact` never appear there.

## 6. Frontend Change Summary

**N/A.** No frontend file is touched. `extraction_method` never leaves the backend process boundary it's created and consumed within (GCS payload → `unitize()` → grounding's in-memory `Unit`/`Fact` objects → log lines) — it is never written to `output_data`, never sent to the frontend, and (per §4.10) never even reaches an LLM prompt. The frontend's existing behavior is unaffected in every respect.

## 7. Testing

### 7.1 Breaking changes — every existing `SourceSpan(...)`/`Unit(...)` construction needs the new required field

Because both fields are added with **no default** (§4.5, §4.6 — matching every other field on both models, and matching this codebase's stated no-back-compat posture), every existing test that constructs a `SourceSpan` or `Unit` directly breaks with a `pydantic.ValidationError` for a missing required field, until it's updated to pass `extraction_method`. Grep-confirmed inventory (§1's grep evidence extended to production + test call sites):

| File | Construction sites | Fix |
|---|---|---|
| `backend/services/care_plan_input.py` (`resolve_uploaded_files`) | 1 (production) | Covered by §4.3's diff itself. |
| `backend/services/unitizer.py` (`provenance_for_pasted_text`, and `unitize`'s `Unit(...)`) | 2 (production) | Covered by §4.4/§4.6's diffs. |
| `backend/tests/models/test_provenance.py` | `_span()` helper (used by most tests in the file) + 1 direct call in `test_source_span_rejects_unknown_field` | Add `extraction_method="native"` to the `_span()` helper's default `fields` dict — fixes every test that calls `_span(...)` in one place. The direct call in `test_source_span_rejects_unknown_field` doesn't strictly need the new field to still raise `ValidationError` (it's already missing a required field in addition to carrying the forbidden `extra="x"` key, and either alone raises), but add it anyway so the test asserts what it claims to assert (rejecting an unknown key on an otherwise-valid span, not incidentally also rejecting a missing field). Add one new test: `test_source_span_requires_extraction_method` (omit it from an otherwise-valid `_span()` call, assert `ValidationError`). Add one new test asserting the `Literal`'s exact members: `test_source_span_rejects_invalid_extraction_method` (`_span(extraction_method="scanned")` → `ValidationError`). Extend `test_job_input_payload_round_trips_through_to_dict_from_dict` — no code change needed since it already goes through `_span()`, but worth a comment noting it now exercises the field's round-trip through `JobInputPayload` too. |
| `backend/tests/services/test_unitizer.py` | 9 direct `SourceSpan(...)` calls (no shared helper in this file today) | Add `extraction_method="native"` to each. Consider introducing a small `_span(**overrides)` helper here too (mirroring `test_provenance.py`'s pattern) to reduce this to one edit point for any future field addition — not required, but this PRD's own churn is a natural moment to add it. Extend assertions: every `unitize(...)` call's resulting units should additionally assert `u.extraction_method == "native"` (or whatever the test's own spans specify) at least once per test that isn't specifically about extraction_method, to prove the copy-through actually happened — plus new dedicated tests: `test_unitize_copies_extraction_method_from_span_verbatim`, `test_unitize_preserves_distinct_extraction_methods_across_mixed_spans` (one native span, one ocr span, one pasted span in the same `provenance` list — assert each emitted unit's `extraction_method` matches its own span's, not some other span's — the mixed-upload case, §4.2). `test_provenance_for_pasted_text_single_span_covers_whole_text`'s expected `SourceSpan(...)` literal needs `extraction_method="pasted"` added to match. |
| `backend/tests/services/test_care_plan_input.py` | 2 direct `SourceSpan(...)` calls (`test_upload_job_input_writes_json_with_text_and_provenance`, `test_load_job_input_happy_path`) + the new-span-producing tests added by PRD 02/09 that go through `resolve_uploaded_files`/`_resolve(...)` (no direct construction, unaffected by the missing-field issue, but see below) | Add `extraction_method="native"` to both direct calls (both use `.txt` files in their fixtures). Add a new test proving §4.3's per-file computation: `test_resolve_uploaded_files_multi_file_mixed_native_and_ocr_tags_spans_correctly` — one `.txt` upload plus one image upload (reusing this file's existing `_FakeUpload`/`extract_text_from_image`-mocking pattern from `test_resolve_uploaded_files_image_becomes_raw_merge_candidate`) in the same `_resolve([...])` call; assert the `.txt` file's span(s) have `extraction_method == "native"` and the image's span has `extraction_method == "ocr"`. |
| `backend/tests/models/test_ledger.py` | `_unit()` helper (covers most call sites) + 2 direct `Unit(...)` calls (`test_quote_for_returns_unit_text_slice`, and the module-level constant if any) | Add `extraction_method="native"` to the `_unit()` helper's default `fields` dict, and to the 2 direct calls. Add `test_unit_requires_extraction_method` and `test_unit_rejects_invalid_extraction_method`, mirroring the two new `SourceSpan` tests above. |
| `backend/tests/care_plan/test_pipeline_grounding.py` | 25 direct `Unit(...)` calls, no shared helper today | Add `extraction_method="native"` to all 25 (every fixture in this file represents a PDF-note scenario — none currently test OCR/pasted behavior at all, so `"native"` is the correct, not merely convenient, value for every existing case). This is the largest mechanical edit in this PRD's footprint; introducing a `_unit(**overrides)` helper at the top of this file (same pattern as `test_ledger.py`/`test_provenance.py`) is worth doing here specifically, both to make this edit a one-line change per call site and because this file is exactly where the new OCR-aware tests below live. New tests: `test_ground_logs_extraction_signal_aggregate_for_verified_facts` (mixed native/ocr units, assert the `logger.info` call's `extra["extraction_signal_facts"]` dict has the right `total`/`ocr`/`ocr_rate`, via `caplog` — matching PRD 11 §7.1's established `caplog` pattern for this exact kind of aggregate assertion in this same test module family); `test_ground_extraction_signal_omits_log_when_zero_facts_verified` (all drafts fail verification → `PIPELINE_VALIDATION_FAILED` raised, and no `extraction_signal_facts` log emitted — the `if not facts: return` guard); `test_verify_ledger_drop_warning_includes_extraction_method_for_ocr_unit` (a unit with `extraction_method="ocr"` whose draft fails `_is_verbatim_quote` — assert the resulting `logger.warning` message contains `extraction_method=ocr`, via `caplog`). |
| `backend/tests/care_plan/test_pipeline_schema.py` | 6 direct `Unit(...)` calls | Add `extraction_method="native"` to all 6 (same reasoning as `test_pipeline_grounding.py` — these are all native-PDF fixtures unrelated to this PRD's own subject matter). |

### 7.2 New file: `backend/tests/services/test_unitizer.py` additions for `_log_extraction_signal`

(Folded into the table above rather than a separate file — `_log_extraction_signal` lives in `unitizer.py`, so its tests belong in `test_unitizer.py` alongside `unitize`'s existing tests.) One additional test worth calling out on its own: `test_unitize_logs_extraction_signal_aggregate` — build a `provenance` list with 2 native spans and 1 ocr span producing, say, 5 native units and 2 ocr units; call `unitize(...)`; assert (via `caplog`, `logger.info` level) the emitted record's `extra["extraction_signal"]` equals `{"total": 7, "native": 5, "ocr": 2, "pasted": 0, "ocr_rate": 2/7}`. And `test_unitize_empty_units_list_logs_nothing` (empty `provenance` → `caplog` has zero records from `services.unitizer`).

### 7.3 Files checked and confirmed unaffected

- `backend/tests/routes/test_jobs.py`, `test_jobs_e2e_scenarios.py` — neither constructs `SourceSpan`/`Unit` directly; they exercise `resolve_uploaded_files`/`_resolve_job_input` end-to-end, which this PRD keeps fully populated (§4.3). Spot-check during implementation that none of these assert a full-dict equality on a serialized `SourceSpan` that would need updating for the new key (grep for `.to_dict()`/literal dict comparisons against provenance shapes before assuming zero changes needed).
- `backend/tests/utils/test_pdf.py`, `test_image_ocr.py` — neither constructs `SourceSpan`/`Unit`; both test extraction functions that this PRD's producers call but does not itself modify (`extract_pages_from_pdf`, `extract_text_from_image` are unchanged).
- `backend/tests/utils/test_constants.py` — extend to assert the two new `LOG_EXTRA_KEYS` entries exist (mirrors this file's existing `assert "user_id" in Constants.Observability.LOG_EXTRA_KEYS` pattern, per PRD 11 §7.3's identical addition for `coverage_signal`): `assert "extraction_signal" in Constants.Observability.LOG_EXTRA_KEYS` and `assert "extraction_signal_facts" in Constants.Observability.LOG_EXTRA_KEYS`.

## 8. Manual Intervention Required From You

Nothing blocking. Two things worth your awareness, not your action:

- **Log volume.** This adds two `logger.info` calls per successful job run (one in `unitize()`, one in `ground()`) plus, occasionally, an extra field on two pre-existing `logger.warning` calls. Negligible relative to this pipeline's existing per-run log volume (four LLM calls, each already logged), but noted since it's a permanent, always-on addition to every run's Cloud Logging footprint, not a sampled or opt-in one (§4.8.1 explains why always-on is the right call here, same reasoning PRD 11 gives for its own signal).
- **If you want to eyeball the signal on a real OCR'd upload** (not required for this PRD to be considered complete, since no automated clinical-fidelity check is in scope anywhere in this initiative): run a real end-to-end job via ngrok + pm2 (`SERVICE_MODE=combined`) with a photographed document, and confirm in the local logs that `extraction_signal`/`extraction_signal_facts` show a nonzero `ocr`/`ocr_rate` and that a native-only upload in the same session shows all-zero `ocr` counts. This is a smoke test of the wiring, not of OCR accuracy.

## 9. Open Questions & Decisions

- `[RESOLVED: extraction_method is a three-way Literal["native", "ocr", "pasted"], not a binary native/ocr.]` — §4.1. Pasted text has no extraction step at all; folding it into `"native"` would be a category error and would corrupt the per-run aggregate's `"native"` count with units that never went through any extractor.
- `[RESOLVED: no per-page OCR fallback exists for PDFs today (grep/read-confirmed against extract_pages_from_pdf, §4.2) — a page with no text layer is silently omitted, never OCR'd, so extraction_method's real granularity is per-file, not per-page, given current code.]` — the field still lives on the per-(file, page) SourceSpan rather than a new per-file structure, so a future per-page fallback wouldn't require another schema change, but this PRD does not build that fallback.
- `[RESOLVED: extraction_method is required with no default on both SourceSpan and Unit, matching every other field on both models.]` — §4.5, §4.6. A default (e.g. defaulting to `"native"`) would let a genuinely-unknown-provenance record silently mislabel itself, which is worse than a loud `ValidationError` for a signal whose entire purpose is triage trustworthiness. Accepted cost: real, enumerated test-fixture churn (§7.1 — roughly 45 existing `SourceSpan`/`Unit` construction sites across 6 test files, plus 2 production call sites already covered by this PRD's own diffs).
- `[RESOLVED: the GCS JobInputPayload shape change needs no migration, no dual-shape reading, no version field.]` — §4.7. The object's lifetime (per-job, deleted at completion/failure, 1-day GCS lifecycle backstop regardless) makes a version-skew window real but inconsequential — a mid-flight rolling-deploy job fails cleanly via the existing `PIPELINE_ERROR` path `load_job_input` already has wired up for every other kind of payload corruption, rather than silently mislabeling data.
- `[RESOLVED: the grounding prompt does not see extraction_method — _format_units_for_prompt, _GROUND_PROMPT, and every other prompt template are unchanged.]` — §4.10. Directly mirrors PRD 02's own on-record rejection of adding illegibility markers to `IMAGE_OCR_PROMPT`, one prompt hop earlier in the same pipeline, for the same reason: it invites the model to editorialize about transcription reliability instead of extracting and citing facts, and specifically threatens `_is_verbatim_quote`'s exact-substring soundness check by giving the model a reason to paraphrase instead of quote verbatim on exactly the content this feature is meant to help a human scrutinize.
- `[RESOLVED: two log-only aggregates, not one — a unit-level one in unitize() (earliest possible point, survives a mid-pipeline failure) and a fact-level one in ground() (answers the sharper "how much of what got cited" question) — plus extraction_method added to two of _verify_ledger's three existing per-fact drop warnings (the two where a specific unit is already in scope).]` — §4.8. The two aggregates measure genuinely different things (source-document OCR share vs. cited-fact OCR share) and can diverge in either direction; neither substitutes for the other.
- `[DEFERRED: whether a future PRD should add a per-page OCR fallback for PDFs with an empty text layer (rather than the current silent-omission behavior), and if so, whether that changes SourceSpan's granularity from "effectively per-file" to "genuinely per-page" in practice.]` — out of this PRD's scope (§3), a real gap the schema already accommodates without further change (per-(file, page) `SourceSpan`). §4.2's "per-file today" framing would need revisiting if that fallback is ever added; this stays a known gap, not a new work item here.
- `[RESOLVED: the fact-level aggregate (§4.8.2) stays run-level; it is not broken down by FactCategory.]` — "how much of this run rests on OCR" is a single run-level question, unlike omission (where category genuinely changes the stakes — a missed warning sign matters differently than a missed follow-up date). No category breakdown is added; simpler is correct here.
- `[RESOLVED: LOG_EXTRA_KEYS additions from PRDs 10, 11, and 12 land as sequential diffs against utils/constants.py, each appending its own key — not concurrent parallel diffs.]` — §4.9. Mechanically trivial to coordinate this way; sequencing avoids one PRD's entry being silently dropped by an unrebased concurrent edit.
