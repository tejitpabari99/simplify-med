# Error Taxonomy

Split out of [`pipeline.md`](pipeline.md)'s former §8 — this file is the address for
"what happens when X fails," referenced from `architecture.md`'s API-surface section for
the error-envelope shape and from `testing.md` for anyone adding a new failure mode.

## The "codes.py"/"exceptions.py" split

All backend errors funnel through `backend/errors/`: `"codes.py"` is pure data — every
error code plus its metadata (an HTTP status, a developer-facing message, a
plain-English user hint, and whether retrying is likely to help); `"exceptions.py"` holds
the logic that raises, classifies, and formats them into responses.

## Categories

LLM generation failures (mapped from Vertex AI finish reasons — hitting the output token
limit, a safety block, blocked recitation, prohibited content, no candidates returned,
invalid JSON, etc.), Vertex AI API-level errors (quota exceeded, deadline exceeded,
permission denied, service unavailable, etc.), pipeline/processing errors (unparseable
file, empty document, schema validation failure, job timeout), auth errors
(missing/malformed token, anonymous access forbidden), resource errors (not found,
forbidden), input-validation errors, and rate limiting.

## `message` vs. `user_hint`

Every error carries both a `message` (technical, for logs/developers) and a `user_hint`
(plain-English, safe to show a non-technical user). A structured exception's own detail
string is shown to the client because it was written by this codebase specifically to be
shown; an unclassified exception's raw message is **not** — it is logged server-side but
stripped from the response, since some exception types can embed the actual invalid
input value in their message text.

## Step → possible `ErrorCode`s → fatal to the job?

| Step | Possible `ErrorCode`s | Fatal to the job? |
|---|---|---|
| `READ_NOTE` | `FILE_PARSE_FAILED`, `UNSUPPORTED_FILE_TYPE`, `EMPTY_DOCUMENT`, `INPUT_VALIDATION_ERROR`, `FILE_TOO_LARGE` | Fatal — the request never becomes a job (raised in `POST /jobs`, before any job doc is created), or fails the job immediately if raised in the worker's own defensive re-check |
| `DETECT_TERMS` | none observed — this step catches its own exceptions and falls back to empty term lists | Non-fatal by construction |
| `GROUND` | `LLM_INVALID_JSON`, `PIPELINE_VALIDATION_FAILED`, plus any unclassified `LLM_*`/`VERTEX_*` code the underlying Vertex AI call itself raises | **Fatal** — aborts the job |
| `ASSEMBLE_AND_RENDER` | `LLM_INVALID_JSON`, `PIPELINE_VALIDATION_FAILED`, plus any unclassified `LLM_*`/`VERTEX_*` code | **Fatal** — aborts the job |
| `REVIEW` | `LLM_INVALID_JSON`, `PIPELINE_VALIDATION_FAILED`, plus any unclassified `LLM_*`/`VERTEX_*` code | Non-fatal — the pipeline ships `assemble_and_render`'s output unmodified |
| `CORRECT` | `LLM_INVALID_JSON`, `PIPELINE_VALIDATION_FAILED` (including a corrector-diff-check rejection), plus any unclassified `LLM_*`/`VERTEX_*` code | Non-fatal — the pipeline reverts to the pre-correction care plan |

`ground`, `assemble_and_render`, `review`, and `correct` each independently reuse
`LLM_INVALID_JSON`/`PIPELINE_VALIDATION_FAILED` for every one of their new failure modes
(a malformed grounding draft, an empty verified ledger, an invalid assembled/reviewed/
corrected shape, a diff-check rejection) rather than adding a per-step `ErrorCode` — a
consistent, cross-step decision, not one made once and left unexamined by the others.

## No frontend change is ever required for a new failure mode on an existing step

The frontend's error rendering is already fully generic over `code`/`message`/
`user_hint`: `ResultScreen.tsx` renders `jobDoc.error_data?.user_hint ??
jobDoc.error_data?.message ?? <generic fallback>` with no `switch`/`case` branching on
any specific `ErrorCode`, and every `ErrorCode`'s `user_hint` in `codes.py` is already
written generically enough to read correctly regardless of which pipeline step raised
it. So **no frontend change is ever required** when a new failure mode is added to an
existing step, as long as it reuses an existing `ErrorCode` — only adding a genuinely new
`ErrorCode` (not done by any of PRDs 01–18) would call for a frontend look, and even then
only because a new code's `user_hint` needs writing, not because the rendering path
itself needs to branch on it.
