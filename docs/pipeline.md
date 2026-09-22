# Processing Pipeline

This document covers the backend pipeline that turns a submitted document into a
structured, plain-language care plan: input extraction and unitization, term
detection, the four LLM calls, readability scoring, and the error taxonomy (moved to
[`error-taxonomy.md`](error-taxonomy.md)).

## 1. Input extraction and unitization

Implemented in `backend/services/care_plan_input.py`. Accepted file extensions
(`pdf`, `txt`, `docx`, `html`/`htm`, and images `png`/`jpg`/`jpeg`/`webp`/`heic`) are
dispatched by extension:

- **TXT** — decoded as UTF-8 (`errors="replace"`).
- **PDF** — `PyPDF2`, page text concatenated. A password-protected PDF is distinguished
  from a merely corrupt one and gets its own actionable error message.
- **DOCX** — `python-docx`, paragraph text joined with newlines.
- **HTML/HTM** — `BeautifulSoup` (stdlib parser): `<script>`/`<style>` removed, inline
  formatting tags unwrapped, text taken from `<body>`.
- **Images** — routed to Gemini vision OCR (§2 below).

Every extractor's library-specific exceptions (PyPDF2 read errors, python-docx zip/XML
errors, etc.) are reclassified into a structured error with an actionable message rather
than surfacing as a raw 500.

**Multiple files become one document, tracked by provenance, not by a text marker.**
`resolve_uploaded_files` (called from `routes/jobs.py::_resolve_job_input`) extracts each
usable file's text and concatenates it into one combined text block — but unlike the
pre-inversion pipeline, no `--- Source: <filename> ---` marker is spliced into that text
(that separator was deleted outright, PRD 02 §4.6). Instead, `resolve_uploaded_files`
builds `provenance: list[SourceSpan]` alongside the text, at (file, page) granularity: one
`SourceSpan` per contiguous run of lines belonging to the same (file, page), each carrying
`file`, `page`, an inclusive `start_line`/`end_line` range into the combined text's
`split("\n")` result, and `extraction_method` (below). This is why grounding can cite
`[unit_id]` and have the frontend/glossary recover a real file/page location — the model
is never asked to invent one.

The API process writes the (text, provenance) pair to Cloud Storage as one JSON object —
`JobInputPayload{text, provenance}` — via `upload_job_input`, rather than passing it
through Firestore; see [`architecture.md`](architecture.md) §2 for the object's exact
lifecycle and shape. `services/unitizer.py::unitize` (for uploads/pasted-file text) and
`provenance_for_pasted_text` (for the pasted-text path, a single synthetic span) then
materialize `list[Unit]` — the numbered, per-line evidence list the grounding call
actually cites — once, in the worker, immediately before grounding runs. Blank/whitespace
lines are dropped when building `Unit`s but still occupy a slot in the line-index
accounting, so `Unit.line` matches what a human counting lines in the original file would
call that line; `Unit.id` is a flat, contiguous, 1-indexed integer assigned only to
non-blank lines, in document order.

`Unit.file`/`Unit.page`/`Unit.line` semantics per source type (verbatim from PRD 02 §4.2):

| Source type | `Unit.file` | `Unit.page` | `Unit.line` (1-indexed within its page/file) |
|---|---|---|---|
| PDF | the uploaded filename | the real PDF page number (1-indexed; a blank page with no extractable text is omitted, **not renumbered** — if page 2 is blank, pages jump 1 → 3) | position within that page's `PyPDF2`-extracted text, split on `"\n"` |
| TXT | the uploaded filename | `1` (constant — no page concept) | position within the whole decoded file, split on `"\n"` |
| DOCX | the uploaded filename | `1` (constant — `python-docx`'s `.paragraphs` API exposes no page boundaries) | index among non-empty paragraphs |
| HTML | the uploaded filename | `1` (constant) | position within BeautifulSoup's `get_text(separator="\n")` output |
| Image | the uploaded filename | `1` (constant, per image) | position within that image's Gemini OCR transcription, split on `"\n"` |
| Pasted text | the literal string `"text_input"` (the existing sentinel already used for `input_source_filename`) | `1` (constant) | position within the pasted text, split on `"\n"` |

**`extraction_method` column.** Both `SourceSpan` (`backend/models/provenance.py`) and
`Unit` (`backend/models/ledger.py`) carry a required `extraction_method:
Literal["native", "ocr", "pasted"]` field, copied from the span onto every `Unit` built
from it. `"native"` covers PyPDF2/python-docx/BeautifulSoup/plain-text decoding, `"ocr"`
is set when the text came from the Gemini-vision transcription path (§2 below), and
`"pasted"` marks the single synthetic span `provenance_for_pasted_text` builds for text
typed or pasted directly into the app (no extraction step at all).

**Unusable files are tolerated, not fatal.** A single file that fails to parse, is
empty/blank, or is an unsupported type is skipped rather than aborting a multi-file
request; its filename is recorded so the caller can see what was skipped. The request
only fails if *no* file yields usable content.

**Empty-document detection** runs at three layers so no input source can silently reach
the pipeline on nothing: after per-file extraction (any file under 20 characters of
stripped text is rejected), on the image-OCR sentinel (below), and again as a defensive
floor on the fully-resolved text immediately before the pipeline runs.

## 2. Image OCR (Gemini vision)

Image input (`backend/utils/image_ocr.py`) is handled by a single multimodal Gemini
call, not a separate OCR service:

1. The image bytes are decode-verified before any model call is spent on them; a
   corrupt or mislabeled file is rejected immediately.
2. If the image's longest edge exceeds **4096 px** (`_MAX_LONG_EDGE_PX`), it is
   downscaled before sending (best-effort — on any decode error during downscaling, the
   original bytes are sent unchanged).
3. The image is sent to Gemini with a fixed instruction prompt: transcribe *all* visible
   text verbatim — headers, medication names/dosages, dates, numbers, line breaks —
   without summarizing, interpreting, or commenting on the image. If no legible text is
   present, the model is instructed to return the literal token `NO_TEXT_FOUND`.
4. A `NO_TEXT_FOUND` response is treated as an empty document. Otherwise the returned
   text flows into the pipeline exactly like text extracted from any other format, tagged
   `extraction_method="ocr"` on its `SourceSpan`.

This call uses a larger output-token budget than the pipeline's other steps, since a
dense scanned page can produce a lot of transcribed text. The 4096px ceiling is a
reasoned-not-measured constant — see the footer callout below.

## 3. Length limits

Pasted text and extracted file text are validated against one cap before a job is
created: **`MAX_TEXT_LENGTH`, 500,000 characters** (Python codepoints). The former
second, independent UTF-8-encoded-byte cap (checked alongside the character cap) is
gone: it existed only because Firestore's 1 MiB
per-document byte limit applied to the raw input text, and input text no longer touches
Firestore at all — it lives only in the transient GCS `JobInputPayload` object. See
[`architecture.md`](architecture.md) §2 for the transport that made the byte cap
unnecessary.

Text is also checked for content Firestore cannot store as a UTF-8 string field (an
unpaired UTF-16 surrogate codepoint, or an embedded NUL byte) and rejected with a clear
message rather than failing later with an unhandled write error.

## 4. The pipeline: four LLM calls plus their deterministic checks

The pure pipeline algorithm lives in `backend/care_plan/pipeline.py`
(`CarePlanPipeline`); `backend/services/care_plan_pipeline.py` is the adapter that wraps
each step with observability and runs readability grading. Four sequential LLM calls —
`ground` → `assemble_and_render` → `review` → `correct` — replace the pre-inversion
three-call, five-stage design; every deterministic check below runs with no model call
involved.

### Term detection (deterministic, unchanged)

Runs three independent, dictionary-based lookups against a normalized copy of the text
(see §5 below) and returns three lists — plain-language substitution candidates,
medical terms to preserve and define, and abbreviation expansions — that feed the
`ground` and `assemble_and_render` prompts. Each of the three lookups is individually
wrapped so a failure in one logs and continues with an empty list rather than aborting.

### Grounding (`ground`)

**Inputs:** the deterministic `units: list[Unit]` and the detected `abbreviations`.
`ground` prompts the model to emit `_GroundedFactRaw` drafts (a category, a `unit_id`
citation, and a verbatim quote from that unit), which `_verify_ledger` turns into
verified `Fact`s via three deterministic post-checks, drop-and-log on failure of any one
(never fails the whole step for one bad draft):

1. **Unit existence** — the cited `unit_id` must be a real unit.
2. **Verbatim-quote check** — the quote must appear in the cited unit's text, tolerant of
   OCR noise (`_is_verbatim_quote`).
3. **Informativeness floor** — the quote must clear `_QUOTE_MIN_LENGTH`/
   `_QUOTE_LONG_WORD_MIN_LENGTH` (`_is_informative_quote`), so a quote that is technically
   verbatim but carries no real clinical content is still dropped.

A draft that survives all three has its quote *located* (not copied) inside the unit's
raw text, and is stored as a `Fact` carrying `char_start`/`char_end` — the quote string
itself never reaches the `Fact` model. `ground` is **fatal on failure**: no whole-document
prose survives anywhere in this pipeline to fall back to once assembly runs from a
ledger, not from the raw text. `_log_grounding_extraction_signal` then logs one
`extraction_signal_facts` aggregate (verified facts citing an OCR-extracted unit, out of
all verified facts) — log-only, cross-referenced in the footer's log-key list below.

### Assembly and render (`assemble_and_render`)

The single LLM call that maps the verified fact ledger into a typed `CarePlan`,
splitting and plain-language-rendering each field. `_verify_assembly` runs several
deterministic, LLM-free guards afterward, none of them fatal — each corrects, filters, or
drops in place and logs:

- **Citation-existence check.** Every item in the seven `_ITEM_LIST_FIELDS`
  (`reason_for_visit`, `medications`, `tests`, `procedures`, `other`, `follow_up`,
  `warning_signs`) and every `diagnosis.details` entry must carry at least one
  `source_fact_ids` value that is a real fact id; an item with none is dropped, and a
  hallucinated id mixed in with real ones is stripped rather than dropping the whole
  item. `diagnosis.changed_since_last_visit` gets the same treatment via
  `changed_since_last_visit_fact_ids`: cleared to empty if none of its cited ids are
  real. This check widened from six item-list fields to the current seven plus the
  `reason_for_visit`/`diagnosis` blocks (PRD 18) — previously only the six list-typed
  fields other than `reason_for_visit` were covered.
- **Questions-cap-to-3 truncation** — `model.questions` is truncated to 3 if the model
  returned more.
- **Content-richness logging pass** (`_log_thin_fields`) — logs (never mutates) a
  `why`/`description` field that fails the same informativeness floor grounding uses;
  `why` may be `None` and a `None` value never triggers this check.
- **`NUMERACY`** (PRD 10) — a block in the shared `_STYLE_RULES` constant (reaching both
  `assemble_and_render.txt` and `correct.txt` — the shared prompt include, not two
  separate copies) instructing the model: no added label ("high blood pressure" for a
  bare value), no added reference range, no rounding/truncation of an already-exact
  number, no unit conversion, no percent-frequency reframe, and no unattributed
  severity/urgency word — a number may carry only the interpretation the source fact
  itself already states. Alongside it, `_check_numeric_parity` is a log-only,
  deterministic check (never mutates the `CarePlan`) that re-extracts every number+unit
  token from each rendered field and its cited facts' text, logging a `WARNING` per
  number found in a rendered field with no matching token among its cited facts (with a
  `<non-unit word>` redaction guard so an unrecognized following word — a name, not a
  unit — never gets logged verbatim), plus one summary-count `WARNING` per run.
- **`merge_candidate_signal`** (PRD 14) — the `assemble_and_render.txt` prompt's `MERGE`
  paragraph instructs the model to merge two or more facts describing the identical
  underlying clinical fact into one item, preserving every differing detail; it was
  hardened by extending its existing two-site worked example (plaque in the left and
  right coronary arteries) to a three-site one (see the prompt file for the full text —
  not re-derived here). `_verify_assembly` logs a log-only, always-on
  `merge_candidate_signal` aggregate (`{total, by_section}`) counting how many items
  across the seven `_ITEM_LIST_FIELDS` cite more than one fact — a superset of actual
  merges (an item legitimately built from several complementary facts also counts) that
  flags candidate near-duplicate merges for review. It counts only the item-list fields,
  not `diagnosis`.
- **`source_fact_ids`/`changed_since_last_visit_fact_ids`** (PRD 18) — new fields on
  `DiagnosisDetail`/`ReasonForVisit` and `Diagnosis` respectively, cited above as part of
  the widened citation-existence check.

`assemble_and_render` is **fatal on failure**, same as `ground`.

### Review (`review`)

One LLM call producing field-level corrections and a per-fact coverage walk.
`_sanitize_review_result` is the deterministic drop-and-log policy afterward: drops a
correction whose path doesn't resolve against the care plan, a `not_stated` outside the
four scoped `why` fields (`medications`/`tests`/`procedures`/`other`), or a `correct` with
no value; and applies a contradiction guard where a `remove` on an item wins over any
`correct`/`not_stated` targeting the same item. `review` is **non-fatal**: on failure the
pipeline ships `assemble_and_render`'s output unmodified, since a fidelity nit must never
cost the user their whole result.

**`coverage_signal`** (PRD 11) — `_log_coverage_summary` reads `review()`'s already-
computed, already-discarded `coverage` field once and logs one `INFO`-level
`"review: coverage signal -- ..."` line per run: `coverage_signal: {total, omitted, rate,
omitted_by_category}`. The log message states explicitly that `present=False` here is a
WEAK signal (near-chance per-fact LLM judgment, ~24.6% published detection rate) — trend/
observability only, never a per-fact verdict.

### Correct (`correct`)

Applies exactly the named corrections from `review` plus a bounded PII sweep (never a
free-form rewrite). `_verify_correction_diff` is the deterministic post-check — it
rejects any unnamed, non-PII-shaped change to the care plan. `correct` is **non-fatal**:
on failure (including a diff-check rejection) the pipeline reverts to the pre-correction
`care_plan`.

### The glossary-curation background thread

Starts right after term detection, on its own `ThreadPoolExecutor(max_workers=1)`,
running concurrently with all four LLM calls above. The `LLMClient()` for this thread is
constructed eagerly, on the calling thread, before the executor submits its job — this
avoids a `vertexai.init()` race between this thread's client construction and the main
thread's own client. A 20-second timeout backstop
(`Constants.Deadlines.GLOSSARY_CURATION_TIMEOUT_S`) on `glossary_future.result(...)`
falls back to uncurated terms if curation hasn't finished in time; if it's still running
past that timeout, `glossary_executor.shutdown(wait=False)` lets it finish in the
background rather than blocking job completion a second time.

### The deterministic close

Glossary re-detection against the final `care_plan` (`build_glossary_from_care_plan`) is
the only step left after `correct()` — the citation-existence check that used to need
ordering against it is already enforced inside `assemble_and_render`, before `review`/
`correct` even run.

| # | Step | LLM call? | Fatal/non-fatal | Fallback |
|---|---|---|---|---|
| 1 | Reading your note | no | n/a — implicit; the state between job pickup and term detection starting | — |
| 2 | Finding difficult and medical terms | no | non-fatal | falls back to empty term lists |
| 3 | Finding the facts in your note (`ground`) | yes | **fatal** | none — aborts the job |
| 4 | Putting your care plan together (`assemble_and_render`) | yes | **fatal** | none — aborts the job |
| 5 | Double-checking your care plan (`review`) | yes | non-fatal | ships assembly's output unmodified |
| 6 | Finishing touches (`correct` + deterministic close) | yes | non-fatal | reverts to the pre-correction care plan |

(Sourced from `Constants.Pipeline.PIPELINE_STEPS`, `backend/utils/constants.py`, and PRD
06 §4.9's composite policy table.)

## 5. Term detection and the jargon dictionaries

`backend/utils/jargon_db.py` loads three static, checked-in dictionary JSON files from
`backend/data/jargon/` and builds normalized lookup tables from them (plus a fourth,
`sources.json`, holding only friendly source names for attribution — not term data):

- **`ahrq_plain_language.json`** — jargon-to-plain-language replacement pairs (AHRQ
  Health Literacy Universal Precautions Toolkit), used as substitution candidates.
- **`michigan_medical_dictionary.json`** — medical terms with full definitions (and
  optional image/alt-text), used both to tell assembly *not* to rewrite them inline and
  to build the final glossary.
- **`abbreviations.json`** — a flat map of abbreviation to expansion.

Each source is expanded into alias rows at load time (splitting comma-separated
entries, expanding parentheticals like `"stroke (CVA)"` into `stroke`, `stroke CVA`, and
`CVA`, splitting slash alternatives, and — for the medical dictionary — adding
conservative pluralization/verb-form inflections). Rows are sorted longest-alias-first
so a multi-word match (e.g. "shortness of breath") is preferred over a shorter substring
match ("breath") in the same text. Matching itself is a normalized (accent- and
case-insensitive, whitespace-tolerant) substring search with word-boundary anchoring —
entirely deterministic, no LLM call. Abbreviation matching additionally tolerates dotted
and undotted spellings of the same acronym (`b.i.d.` / `bid`).

## 6. Readability scoring

Computed by `backend/utils/scoring.py`, using only automatable, non-LLM signals — no
model call is involved in scoring.

### Composite 0–100 score

Seven weighted dimensions, each normalized to 0–100 and combined:

| Dimension | Weight | Signal |
|---|---|---|
| Grade level | 0.25 | Consensus of Flesch-Kincaid, an approximate Dale-Chall grade, and SMOG (once ≥30 sentences) |
| Jargon density | 0.20 | Difficult-word ratio |
| Sentence complexity | 0.15 | Average words per sentence |
| Passive voice | 0.10 | Passive-construction ratio |
| Actionability | 0.10 | "you"/"your" rate, imperative-sentence rate, bullet presence |
| Numeracy clarity | 0.10 | Count of vague quantifiers ("some", "several", ...) and unlabeled raw fractions |
| Structural clarity | 0.10 | Average words per paragraph, with a bonus for bulleted/numbered structure |

The composite is labeled `"Patient-friendly"` (≥70), `"Moderate"` (≥40), or
`"Hard to read"` (below). A sample under 30 words or 3 sentences is flagged
`low_confidence` — the score is still returned, just noted as less reliable.

### Before / after

The **before** score is computed from the raw input text, before any pipeline step runs
(started on a background thread at the top of the pipeline so it overlaps with the four
sequential LLM calls rather than adding to the total time). The **after** score is
computed via `render_care_plan_text(care_plan)` (`backend/utils/term_detection.py`) — the
final structured `CarePlan`'s plain-text rendering — not an intermediate stage's output,
since no such intermediate whole-document text exists in the four-call pipeline.

### Named method approximations

In addition to the composite score, six separate named scores are computed per target
(before/after), each an *approximation* of a published health-literacy instrument built
from the same underlying dimension scores — not a re-implementation of the original,
which typically requires a trained human rater:

- **SMOG** — direct calculation; flagged `insufficient_sample` under 30 sentences.
- **Flesch-Kincaid** — reading ease and grade level, computed directly.
- **Dale-Chall** — the raw score mapped to an approximate grade-range label.
- **PEMAT** (AHRQ 2013) — a weighted blend approximating its understandability and
  actionability item groups.
- **SAM** (Doak et al. 1996) — an approximation of its automatable content, literacy
  demand, and layout/typography domains.
- **CDC Clear Communication Index** — four pass/fail checks (main message, behavioral
  recommendations, numbers, call to action) derived from threshold rules.

## 7. Output shape

The pipeline produces a typed care-plan document with the following top-level fields:
`summary`, `reason_for_visit`, `diagnosis`, `medications`, `tests`, `procedures`,
`other` (instructions), `follow_up`, `warning_signs`, `questions`, `low_priority`,
`terms` (the glossary, keyed by term), and `additional_info`. The frontend renders these
as: Why You Came In, What the Doctor Found, Your Medications, Tests, Procedures, Other
Instructions, What to Watch For, Questions to Ask at Your Next Visit, Follow-Up, Other
Items From Your Visit, Medical Terms Glossary, and Data Sources.

No intermediate whole-document rewrite artifacts ever exist in this pipeline to drop —
that was a property of the deleted three-call design. Only two classes of field are
pipeline-internal and never reach the frontend: `raw` (deleted per PRD 01, applies to
nothing in the current schema) and the internal fact-ID provenance fields
(`summary_fact_ids` on `CarePlan` and every item's own `source_fact_ids`/
`changed_since_last_visit_fact_ids`), stripped by `routes/worker.py::_strip_internal_provenance`
before a completed job's `output_data` is written.

**`why` is nullable** (PRD 13): `Medication.why`, `Test.why`, `Procedure.why`, and
`OtherInstruction.why` are `why: str | None = None` (`backend/models/care_plan/care_plan.py`),
not the former `why: str = ""` with a placeholder sentinel. `assemble_and_render.txt`/
`correct.txt` instruct the model to emit `null` for a genuinely unstated reason rather
than an empty string or an app-written placeholder; the placeholder sentinel string is
deleted from both prompt files. The frontend's own null-handling fallback is documented
in [`architecture.md`](architecture.md) §6.

## 8. Error taxonomy

Moved to its own document — see [`error-taxonomy.md`](error-taxonomy.md) for the
`codes.py`/`exceptions.py` split, the category list, and the step → `ErrorCode` → fatal
table.

---

## Uncalibrated constants and logged signals

Every constant below is a reasoned-not-measured value — see
[`uncalibrated-constants.md`](uncalibrated-constants.md) for the full seven-column
register (why this value, how it would be calibrated):

- The glossary-curation timeout, `GLOSSARY_CURATION_TIMEOUT_S` (§4 above) — see
  [`uncalibrated-constants.md`](uncalibrated-constants.md).
- The grounding quote-informativeness floor, `_QUOTE_MIN_LENGTH`/
  `_QUOTE_LONG_WORD_MIN_LENGTH` (§4 above) — see
  [`uncalibrated-constants.md`](uncalibrated-constants.md).
- The OCR downscale ceiling, `_MAX_LONG_EDGE_PX` (§2 above) — see
  [`uncalibrated-constants.md`](uncalibrated-constants.md).

**Logged-field keys** (`Constants.Observability.LOG_EXTRA_KEYS`, `backend/utils/constants.py`)
this batch of PRDs adds — these are logged-signal keys, not calibration constants, so
they're listed separately from the register above:

- `extraction_signal` — logged once per run by `unitize()` (§1 above), an aggregate of
  units by `extraction_method`.
- `extraction_signal_facts` — logged once per run by `ground()` (§4 above), the subset of
  *verified* facts citing an OCR-extracted unit.
- `coverage_signal` — logged once per run by `review()`'s `_log_coverage_summary` (§4
  above).
- `merge_candidate_signal` — logged once per run by `assemble_and_render()`'s
  `_verify_assembly` (§4 above).
