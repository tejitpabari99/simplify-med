# Processing Pipeline

This document covers the backend pipeline that turns a submitted document into a
structured, plain-language care plan: input extraction, term detection, the three
Gemini calls, readability scoring, and the error taxonomy.

## 1. Input extraction

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

**Multiple files become one document.** Each usable file's extracted text is
concatenated into one combined text block, separated by a `--- Source: <filename> ---`
marker per file. For file uploads, the accepted files are also merged into one PDF
(PDF/TXT/image bytes merged as-is; DOCX/HTML sources merged as a rendered page of their
*extracted text*, not their original formatting) and uploaded to Cloud Storage as a
stored copy of the original submission — this merged PDF is not what the pipeline
processes; the pipeline works from the extracted text.

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
2. If the image's longest edge exceeds 2048 px, it is downscaled before sending
   (best-effort — on any decode error during downscaling, the original bytes are sent
   unchanged).
3. The image is sent to Gemini with a fixed instruction prompt: transcribe *all* visible
   text verbatim — headers, medication names/dosages, dates, numbers, line breaks —
   without summarizing, interpreting, or commenting on the image. If no legible text is
   present, the model is instructed to return the literal token `NO_TEXT_FOUND`.
4. A `NO_TEXT_FOUND` response is treated as an empty document. Otherwise the returned
   text flows into the pipeline exactly like text extracted from any other format.

This call uses a larger output-token budget than the pipeline's other steps, since a
dense scanned page can produce a lot of transcribed text.

## 3. Length limits

Every path — pasted text, extracted file text — is validated against two independent
caps before a job is created:

- **500,000 characters** (Python codepoints).
- **350,000 UTF-8-encoded bytes**, checked *alongside* (not instead of) the character
  cap. This exists because Firestore's 1 MiB per-document limit is a *byte* limit, not a
  character count: 500,000 characters of CJK or emoji-heavy text can be 1.5–2 MB once
  UTF-8-encoded — well past the character cap without tripping it. Both checks must
  pass.

Text is also checked for content Firestore cannot store as a UTF-8 string field (an
unpaired UTF-16 surrogate codepoint, or an embedded NUL byte) and rejected with a clear
message rather than failing later with an unhandled write error.

## 4. The five pipeline stages

The pure pipeline algorithm lives in `backend/care_plan/pipeline.py`
(`CarePlanPipeline`); `backend/services/care_plan_pipeline.py` is the adapter that wraps
each step with observability and runs readability grading.

| # | Step | LLM call? | On failure |
|---|---|---|---|
| 1 | Reading your note | no | n/a — implicit; this is the state between job pickup and term detection starting |
| 2 | Finding difficult and medical terms | no | non-fatal — falls back to empty term lists |
| 3 | Simplifying language | yes | **fatal** — aborts the job |
| 4 | Clarifying actions and numbers | yes | non-fatal — falls back to step 3's output |
| 5 | Organizing your care plan | yes | **fatal** — aborts the job |

### Step 2 — term detection (deterministic, no LLM)

Runs three independent, dictionary-based lookups against a normalized copy of the text
(see §5 below) and returns three lists — plain-language substitution candidates,
medical terms to preserve and define, and abbreviation expansions — that feed the next
two prompts. Each of the three lookups is individually wrapped so a failure in one logs
and continues with an empty list rather than aborting.

### Step 3 — simplify language (LLM)

**Input:** the original text plus the three term-detection lists, formatted into compact
prompt sections. **Prompt** (`care_plan/prompts/simplify_language.txt`): rewrite the
note to roughly a 6th-grade reading level, use the detected plain-language substitutions
where they fit, preserve detected medical terms verbatim (they are defined separately in
the glossary, not rewritten inline), expand detected abbreviations, use short sentences
and active voice and "you"/"your", never add a diagnosis, piece of advice, or urgency not
present in the source, and never include patient-identifying details. **Output:** plain
text. Any failure here is fatal — there is no partial/fallback simplified text.

### Step 4 — clarify and action (LLM)

**Input:** step 3's simplified text, plus up to 30 detected abbreviations. **Prompt**
(`care_plan/prompts/clarify_and_action.txt`): rewrite in active voice addressed to "you",
start every patient action with a clear verb (Take / Call / Schedule / Ask / Bring /
Watch / Avoid / Continue / Stop), never fabricate numbers or turn vague wording into an
exact number the source doesn't contain, never add urgency not implied by the source,
and break multi-step instructions into separate steps. **Output:** plain text. A failure
here is non-fatal — the pipeline falls back to step 3's output for every subsequent
stage, including the "after" readability score.

### Step 5 — structure the document (LLM)

**Input:** step 4's output (or step 3's, if step 4 failed), plus a JSON schema derived
from the care-plan data model. **Prompt** (`care_plan/prompts/structure_note.txt`):
return JSON only, matching the given schema; use only information present in the source
text; every medication needs a reason explaining *why* it applies to this patient; every
warning sign needs what to do about it and an urgency classification (`emergency` /
`call_doctor` / `monitor` / `normal_side_effect`); the summary must be exactly three
sentences (why the patient came in / the main conclusion / the most important next
step); exactly three patient-facing questions are generated; low-priority details go in
a separate list; active voice, "you", no abbreviations, a 20-word-per-sentence ceiling.
**Output:** JSON, validated against the care-plan schema — a schema mismatch or
non-JSON response is a fatal error, aborting the job.

### Post-processing (no LLM call)

After step 5 succeeds, the medical-term detector is re-run against the **clarified**
text (step 4's output, not the original) to build the final glossary — so the glossary
only contains terms that actually survived into the rewritten text, not every term
detected in the original source.

## 5. Term detection and the jargon dictionaries

`backend/utils/jargon_db.py` loads three static, checked-in dictionary JSON files from
`backend/data/jargon/` and builds normalized lookup tables from them (plus a fourth,
`sources.json`, holding only friendly source names for attribution — not term data):

- **`ahrq_plain_language.json`** — jargon-to-plain-language replacement pairs (AHRQ
  Health Literacy Universal Precautions Toolkit), used as substitution candidates in the
  simplify prompt.
- **`michigan_medical_dictionary.json`** — medical terms with full definitions (and
  optional image/alt-text), used both to tell the simplify step *not* to rewrite them
  inline and to build the final glossary.
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
(started on a background thread at the top of the pipeline so it overlaps with the three
sequential Gemini calls rather than adding to the total time). The **after** score is
computed from step 4's output (the clarified prose), not the final structured JSON from
step 5.

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

The raw text artifacts (original / simplified / clarified) used internally during the
pipeline are dropped from the stored result — the UI never reads them, and keeping them
would needlessly increase the size of every stored job document.

## 8. Error taxonomy

All backend errors funnel through `backend/errors/`: `codes.py` is pure data — every
error code plus its metadata (an HTTP status, a developer-facing message, a
plain-English user hint, and whether retrying is likely to help); `exceptions.py` holds
the logic that raises, classifies, and formats them into responses.

**Categories:** LLM generation failures (mapped from Vertex AI finish reasons — hitting
the output token limit, a safety block, blocked recitation, prohibited content, no
candidates returned, invalid JSON, etc.), Vertex AI API-level errors (quota exceeded,
deadline exceeded, permission denied, service unavailable, etc.), pipeline/processing
errors (unparseable file, empty document, schema validation failure, job timeout), auth
errors (missing/malformed token, anonymous access forbidden), resource errors (not
found, forbidden), input-validation errors, and rate limiting.

Every error carries both a `message` (technical, for logs/developers) and a `user_hint`
(plain-English, safe to show a non-technical user). A structured exception's own detail
string is shown to the client because it was written by this codebase specifically to be
shown; an unclassified exception's raw message is **not** — it is logged server-side but
stripped from the response, since some exception types can embed the actual invalid
input value in their message text.
