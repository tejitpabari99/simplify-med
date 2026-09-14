# Testing

This document explains what each test layer is *for* — not how to run them. Commands
stay in [`local-development.md`](local-development.md) and `CONTRIBUTING.md`, both
already accurate and unchanged by this rewrite.

## Directory layout

Backend tests live under `backend/tests/`, one subdirectory per concern, mirroring the
source tree it tests:

- `backend/tests/care_plan/` — the pipeline itself: `CarePlanPipeline`'s four LLM calls
  and their deterministic checks, plus prompt-content regression tests (below).
- `backend/tests/models/` — Pydantic model validation and shape tests.
- `backend/tests/routes/` — Flask route handlers (`jobs.py`, `worker.py`).
- `backend/tests/services/` — `care_plan_input.py`, `unitizer.py`, and friends.
- `backend/tests/utils/` — jargon dictionaries, scoring, term detection, image OCR, rate
  limiting, and other standalone utilities.
- `backend/tests/integration/` — cross-module behavior that doesn't fit one unit, plus
  the dead-code and docs-reference-real-symbols guard tests (below).
- `backend/tests/scripts/` — the standalone maintenance scripts (anonymous-user cleanup,
  jargon-stoplist pruning) that ship alongside the app but aren't part of a request path.

Frontend tests live under `frontend/src/tests/`.

## What a prompt-content regression test checks

`backend/tests/care_plan/test_pipeline_prompts.py` is the pattern (PRD 04 §7.2): each
test asserts that a named rule's literal text is present in a loaded prompt string (e.g.
`test_assemble_prompt_contains_three_way_merge_example`, or the `NUMERACY`-block tests —
`test_style_rules_contains_numeracy_block`, `test_style_rules_numeracy_forbids_rounding`,
and their siblings, added by PRD 10 §4.1/§7.1 reusing exactly this pattern rather than
inventing a new one). This is deliberately shallow: it does not evaluate what the model
does with a rule, only that the rule's text is actually in the prompt the model receives
— the cheapest possible guard against a prompt edit that silently drops or rewords an
instruction the rest of the codebase (and this documentation) assumes is still there.
`backend/tests/care_plan/test_pipeline_numeric_parity.py` covers the numeric-parity
*checker*'s own logic (tokenization, unit matching, log redaction) — a different kind of
test from the prompt-content-regression pattern above, even though both landed as part
of the same PRD.

## What `test_dead_code_removed.py` checks

`backend/tests/integration/test_dead_code_removed.py` asserts, mechanically, that
specific deleted modules stay deleted — each test imports a module name expected to no
longer exist and asserts it raises `ModuleNotFoundError`. This is a module-non-existence
guard: cheap, zero false positives (a module either imports or it doesn't), and it is the
direct precedent this codebase's own doc-accuracy mechanism
(`backend/tests/integration/test_docs_reference_real_symbols.py`) extends — the same
"assert a specific stale claim can't silently come back" shape, aimed at documentation
claims instead of import statements.

## Adding a new failure mode

If you're adding a new way an existing pipeline step can fail, start at
[`error-taxonomy.md`](error-taxonomy.md)'s step → `ErrorCode` → fatal table — it names
which error codes each step already reuses, and states when (and when not) a frontend
change is required.

## Frontend

Frontend tests (`frontend/src/tests/`) are component tests only — no separate
integration, prompt-regression, or dead-code-guard layers, since none of those concepts
apply to a client-rendered UI. Component behavior (rendering, the `resolveWhy()`
fallback, the "couldn't confirm" fallback, PDF-export HTML generation) is covered where
it lives, one test file per component/util under that same directory tree.
