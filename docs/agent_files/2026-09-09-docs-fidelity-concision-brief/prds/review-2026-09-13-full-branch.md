# Review — 2026-09-13 — full branch (PRDs 01–09), adversarial deep dive
Diff: main...docs/fidelity-concision-brief   Personas: Bug Hunter, Security, Architect
Extra pass (owner request): end-to-end "never blank / never blocked / generic internal errors" audit of backend error paths + frontend.

## Verdict (pre-fix): BLOCK → all findings fixed

## Must-fix (all fixed)
- [Security — BLOCK] backend/care_plan/pipeline.py (ground/assemble_and_render/review/correct) + backend/errors/exceptions.py — `detail=str(ValidationError)` embedded patient-derived LLM output, and build_error_data/build_error_data_from_exc passed detail through to Firestore `error_data.details` (read by the browser listener) for every non-UNKNOWN code. → Fixed f5e6f4e: PHI-free loc/type-only detail helper at all 4 sites; Firestore error_data now honors ERROR_CATALOG details_template exactly like the HTTP path (empty template → details None).
- [Bug Hunter] backend/care_plan/pipeline.py `_targets_removed_item` — anchored regex missed nested array paths (`diagnosis.details[N]`), so a remove + contradictory correct on the same diagnosis detail both reached the corrector, risking an edit applied to the wrong diagnosis. → Fixed 0921e7c (prefix match + regression tests).
- [Error-surfacing audit] frontend — ErrorBoundary rendered raw error.message; nextSteps `.map` on null arrays crashed PDF build; POST /jobs had no timeout (button stuck disabled forever); raw "Failed to fetch"/JSON parse errors shown to user; double-submit race; download-report failures silent/unhandled. → Fixed 9ef590b, fd15983, cb59ffd.
- [Error-surfacing audit] frontend — unrecognized job status left user on spinner until the 6-minute watchdog. → Fixed 047ff10.

## Notes (non-blocking)
- [Architect] Implementation matches PRD 01–09 §4 decisions (fatal/non-fatal policy, glossary thread, provenance stripping, stage constant, PRD 09 GCS payload lifecycle incl. owns_execution guard, MAX_TEXT_BYTES removal, dead-code removal). Worker has top-level catch-all → fail_job; frontend has watchdog, root + result ErrorBoundaries, auth timeout/retry, listener error handling.
- Process: during parallel fix agents, uncommitted backend edits were wiped once by a git operation from another process in the shared working tree; edits were redone and committed.

## Verification
- Backend: 761 passed, 5 warnings, 23 subtests passed in 110.83s (0:01:50), ruff clean
- Frontend: Test Files 20 passed (20), Tests 135 passed (135), lint clean, build OK

## Next step
PASS after fixes → ready to land (open PR / merge at owner's discretion).
