# Tasks: Frontend and PDF

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — `CarePlan`/item-model shape this PRD's TypeScript types mirror exactly (§4.1); 04 (assemble-and-render) — the "not stated in your note" sentinel and nullable `WarningSign.urgency` this PRD renders null-safely; 07 (glossary) — confirms `renderTextWithTerms`/`MedicalTerm.tsx` need no code change (§4.2), independently re-verified below. None of 01's, 04's, or 07's backend code exists in this repo yet; their tasks are tracked in `prds/01-schema-and-config/TASKS.md`, `prds/04-assemble-and-render/TASKS.md`, `prds/07-glossary/TASKS.md` and are **not** duplicated here — this PRD only needs their *settled contracts* (schema shape, sentinel, nullable field, glossary-key semantics), not their code landing first, so its own tasks can be implemented and tested against hand-built fixtures independently. Depended on by: nothing (leaf of the decomposition).

**Conventions**

- Frontend tests: from `frontend/`, run `npx vitest run` (matches `package.json`'s `"test": "vitest run"`). To run a single file: `npx vitest run src/tests/utils/nextSteps.test.ts`. Typecheck: `npx tsc -b` (matches `package.json`'s `"build": "tsc -b && vite build"` — the `tsc -b` half is what actually catches the type-contract violations most of these tasks depend on; you do not need to run `vite build` itself). Lint: `npx eslint .` from `frontend/`.
- No backend changes in this PRD (§3 Non-Goals, §5) — no backend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- Every source edit below is a compile-time forcing function against the new `carePlan.ts` types from Task 1 onward — expect `npx tsc -b` to fail between tasks until the corresponding component/util is also updated. Land Tasks 1-6 in order without running the full frontend test suite in between if you prefer (they touch a connected chain of files), or run `npx tsc -b` after each to see exactly what the next task must fix — either is fine, but do not leave the tree mid-way at the end of a work session.

---

### Task 1 — Rewrite `frontend/src/types/carePlan.ts` to match 01's backend contract

   - Files: `frontend/src/types/carePlan.ts` (full rewrite)
   - Changes (PRD §4.1): Replace the file's content with exactly the new shape given in PRD §4.1's code block — keep `StepStatus`, `AppState`, `PipelineStep`, `GlossaryTerm`, `TermsMap` verbatim (unchanged from today), and replace everything below them with:
     - `export type ItemStatus = 'to_do' | 'done';`
     - `DiagnosisDetail` — unchanged from today's inline shape, now still a named interface (already was).
     - `Medication` — add required `status: ItemStatus`; change `change?: boolean` / `change_description?: string` to a single required `change: string` (empty string means nothing to report).
     - `Test`, `Procedure`, `OtherInstruction` — promote from today's inline anonymous types (inside `CarePlanContent`) to named interfaces (`Test`, `Procedure`, `OtherInstruction`), each gaining required `status: ItemStatus`. Field lists are otherwise unchanged from today's inline shapes.
     - `FollowUp` — new named interface: `time_frame: string`, `description: string`, `status: ItemStatus` (promoted from today's inline `{ time_frame: string; description: string }`, plus the new `status`).
     - `WarningSign` — `urgency` changes from `'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect'` (required, non-null) to `'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect' | null` (still required — no `?`, no `= `, just a wider union that includes `null`).
     - `CarePlanContent` — delete `additional_info`; delete `diagnosis.main_conclusion`; add `summary_fact_ids: number[]` as a sibling of `summary`; change `medications`/`tests`/`procedures`/`other`/`follow_up` to reference the new named interfaces (`Medication[]`, `Test[]`, `Procedure[]`, `OtherInstruction[]`, `FollowUp[]`).
     - Reproduce every field's exact type from PRD §4.1's code block — do not add or drop anything beyond what's listed there (in particular, do **not** add `source_fact_ids` to any item type or `summary_fact_ids`'s sibling fields beyond what's shown — the PRD's block is the literal target).
   - Acceptance criteria:
     - `frontend/src/types/carePlan.ts` contains no occurrence of `additional_info` or `main_conclusion`.
     - `grep -n "change_description" frontend/src/types/carePlan.ts` returns zero hits; `Medication.change` is typed `string`, not `boolean`.
     - `Test`, `Procedure`, `OtherInstruction`, `FollowUp` are each `export interface`s (not inline anonymous object types) with a `status: ItemStatus` field (all but nothing else new).
     - `WarningSign.urgency`'s type is `'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect' | null` and the field has no `?`.
     - `CarePlanContent.summary_fact_ids: number[]` exists; `npx tsc -b` (from `frontend/`) now fails with type errors in `CarePlanView.tsx`, `buildPdfHtml.ts`, `ResultScreen.test.tsx`, `downloadReport.test.ts`, and `HomePage.test.tsx`/fixture consumers — this is expected and is what Tasks 2-9 fix; it is not a regression in this task.
     - `frontend/src/types/envelope.ts` needs **no edit** — `SimplifiedCarePlan = CarePlanContent` (verified: `envelope.ts:29`) already reflects the new shape once this file changes. Do not touch `envelope.ts` in this task.

### Task 2 — New module `frontend/src/utils/nextSteps.ts`

   - Files: `frontend/src/utils/nextSteps.ts` (new file)
   - Dependency: land after Task 1 (imports `CarePlanContent`, `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, `ItemStatus` from `../types/carePlan`).
   - Changes (PRD §4.3): Create the file with exactly the contract given in PRD §4.3's code block: `NextStepType`, `NEXT_STEPS_TYPE_ORDER`, `NEXT_STEPS_TYPE_LABELS`, `NextStepRow`, `joinDetail`, `buildNextStepsRows`. Copy the fixed type precedence exactly (`medication: 0, test: 1, procedure: 2, follow_up: 3, other: 4` — `follow_up` ahead of `other`, per PRD §4.3's `[RESOLVED]` decision in §9) and the exact per-type field mapping (medication → `joinDetail(dosage, frequency, timing, duration)`; test → `joinDetail(description, preparation)`; procedure → `joinDetail(what_to_expect, timeframe)`; follow_up → `title: f.description`, `detail: joinDetail(f.time_frame)`; other → `title: o.title`, `why: o.why`, `steps: o.steps`, `detail: joinDetail(o.description, o.frequency, o.duration)`). Sort is status-then-type, using JS's spec-guaranteed-stable `Array.prototype.sort` for same-`(status, type)` tiebreaking — no explicit tiebreaker code needed.
   - Acceptance criteria:
     - `npx tsc -b` (from `frontend/`) compiles this file with no errors once Task 1 has landed.
     - Covered permanently by Task 10's `nextSteps.test.ts`.

### Task 3 — `frontend/src/components/CarePlanView.tsx` — eight-card collapse, Next Steps, null-safe urgency, strikethrough, `change` fold, `hideLowPriority` deletion

   - Files: `frontend/src/components/CarePlanView.tsx`
   - Dependency: land after Task 2 (imports `buildNextStepsRows`, `NEXT_STEPS_TYPE_LABELS` from `../utils/nextSteps`).
   - Changes (PRD §4.4, §4.8): all in one file, land together as this task's single commit —
     1. **Diagnosis card** (currently `:161-191`): delete the `result.diagnosis.main_conclusion` guard clause and its `<p className="narrative-headline">` block (currently lines 161, 163-166). Change the card's guard condition from `result.diagnosis && (result.diagnosis.main_conclusion || result.diagnosis.details?.length > 0)` to `result.diagnosis && result.diagnosis.details?.length > 0` (drop the `main_conclusion` disjunct entirely — the field no longer exists on the type).
     2. **Delete the Medications, Tests, Procedures, Other Instructions, and Follow-Up cards** (currently `:193-262` and `:316-325`) and **replace them with one Next Steps card** in the same position (fourth card, immediately after "What the Doctor Found" and before "What to Watch For"), using exactly the JSX given in PRD §4.4's code block: call `buildNextStepsRows(result)`, render nothing if `rows.length === 0`, otherwise a `ResultCard color="violet" icon="✅" title="Next Steps"` containing one row per item with a `☑`/`☐` glyph (green `#059669` for `done`, grey `#9CA3AF` for `to_do`), an `sr-only` "Done: "/"To do: " prefix, the title (with `line-through` + `var(--text-secondary)` when done), a `next-step-type-label` chip showing `NEXT_STEPS_TYPE_LABELS[row.type]`, and conditionally a `Why:` line, a detail line, and a `steps` sub-list (`result-list`).
     3. **Delete the Data Sources card** (currently `:348-358`) in its entirety — no replacement.
     4. **Warning-sign urgency, null-safe** (currently `:264-282`): keep `URGENCY_COLORS`/`URGENCY_LABELS`/`URGENCY_ORDER` unchanged; add two new constants `NULL_URGENCY_COLOR = '#9CA3AF'` and `NULL_URGENCY_ORDER = 4`; change the sort from `(URGENCY_ORDER[a.urgency] ?? 4) - (URGENCY_ORDER[b.urgency] ?? 4)` to `(a.urgency ? URGENCY_ORDER[a.urgency] : NULL_URGENCY_ORDER) - (b.urgency ? URGENCY_ORDER[b.urgency] : NULL_URGENCY_ORDER)`; change the color lookup from `URGENCY_COLORS[sign.urgency] ?? '#6B7280'` to `sign.urgency ? URGENCY_COLORS[sign.urgency] : NULL_URGENCY_COLOR`; change the badge from an unconditional `<span ...>[{URGENCY_LABELS[sign.urgency] ?? sign.urgency}]</span>` to `{sign.urgency && <span style={{ color, fontWeight: 700 }}>[{URGENCY_LABELS[sign.urgency]}]</span>}` — a null-urgency sign renders no bracketed badge at all (PRD §4.4/§9's `[RESOLVED]` decision: no invented "NOT STATED"/"UNKNOWN" label).
     5. **Medication `change` rendering** (currently `:198`): change `{med.change && <span ...>[{med.change_description || 'CHANGED'}]</span>}` to `{med.change && <span ...>[{med.change}]</span>}` — `change` is now the string itself (both the gate and the content); delete the `|| 'CHANGED'` fallback (the folded field can't represent "changed=true but no description").
     6. **Delete `hideLowPriority`** (PRD §4.8): remove the `hideLowPriority = false` prop and its `hideLowPriority?: boolean` type from the component's destructured-props signature (currently `:92-98`), leaving only `{ result }: { result: SimplifiedCarePlan }`. Change the "Other Items From Your Visit" guard (currently `:327`, `{!hideLowPriority && result.low_priority?.length > 0 && (`) to `{result.low_priority?.length > 0 && (` — the same guard shape every other optional card in the file already uses.
     7. New render order top-to-bottom: What You Need to Know → Why You Came In → What the Doctor Found → **Next Steps** → What to Watch For → Questions to Ask at Your Next Visit → Other Items From Your Visit → Medical Terms Glossary (eight cards total; this is a straight re-slotting of existing conditional blocks around the new Next Steps block — no new component-level state).
   - Do **not** touch `renderTextWithTerms`, `ResultCard`, the clipboard-copy logic, or any card not named above (PRD §4.2 confirms `renderTextWithTerms` needs no change; §3 Non-Goals confirms no new CSS framework/rewrite of card chrome).
   - Acceptance criteria:
     - `grep -n "main_conclusion\|additional_info\|hideLowPriority\|change_description" frontend/src/components/CarePlanView.tsx` returns zero hits.
     - `npx tsc -b` (from `frontend/`) compiles `CarePlanView.tsx` with no errors (proves `status` being required on the five item types and `urgency` being nullable are both satisfied by the new code).
     - Rendering a care plan with one `to_do` and one `done` item across two different Next Steps types produces exactly one card titled "Next Steps" containing both rows, status-grouped (`to_do` first) then type-ordered within each group.
     - Rendering a `WarningSign` with `urgency: null` produces a grey (`#9CA3AF`) left border, no bracketed badge text, and is still present in the DOM (not dropped).
     - Permanent tests land in Task 10's `CarePlanView.test.tsx`.

### Task 4 — `frontend/src/components/ResultScreen.tsx` — delete `hideLowPriority` call-site prop

   - Files: `frontend/src/components/ResultScreen.tsx`
   - Dependency: land after Task 3 (the prop it passes no longer exists on `CarePlanView`'s interface — this task and Task 3 could land as one commit if preferred, since they're two ends of the same deletion, but are listed separately here to keep each commit's diff to one file).
   - Changes (PRD §4.8): change `<CarePlanView result={care_plan} hideLowPriority />` (currently `:122`) to `<CarePlanView result={care_plan} />`. No other line in this file changes — `downloadReport(care_plan, grading)` (currently `:124`) already matches the unchanged two-argument `downloadReport` signature Task 6 preserves, and the before/after score widget (`:112-114`) is untouched.
   - Acceptance criteria:
     - `grep -n "hideLowPriority" frontend/src/components/ResultScreen.tsx` returns zero hits.
     - `npx tsc -b` (from `frontend/`) compiles with no errors attributable to this file.

### Task 5 — `frontend/src/utils/buildPdfHtml.ts` — mirror `CarePlanView.tsx`'s changes via the shared `nextSteps.ts` module

   - Files: `frontend/src/utils/buildPdfHtml.ts`
   - Dependency: land after Task 2 (imports `buildNextStepsRows`, `NEXT_STEPS_TYPE_LABELS` from `./nextSteps`). Independent of Tasks 3-4 (different file), but listed after them here since it mirrors the same decisions.
   - Changes (PRD §4.5):
     1. Delete the `diagnosis.main_conclusion` branch (currently `:37-53`'s `if (result.diagnosis.main_conclusion) { diagnosis += ... }` block and the `main_conclusion` disjunct in the outer `if (result.diagnosis && (result.diagnosis.main_conclusion || result.diagnosis.details?.length))` guard, which becomes `if (result.diagnosis && result.diagnosis.details?.length)`).
     2. Replace the five separate sections (`Your Medications` `:55-66`, `Tests` `:68-78`, `Procedures` `:80-89`, `Other Instructions` `:91-102`, `Follow-Up` `:125-128`) with one `Next Steps` section built from `buildNextStepsRows(result)`, using exactly the template-string logic given in PRD §4.5's code block: a `☑`/`☐` HTML entity (`&#9745;`/`&#9744;`) colored `#059669`/`#9CA3AF`, `text-decoration:line-through;` on the title `<strong>` when done, the type label, and conditional `Why:`/detail/`steps` lines — same field mapping as `CarePlanView.tsx`'s Next Steps card, driven by the same `buildNextStepsRows` call.
     3. Null-safe warning-sign urgency (currently `:104-118`): change the sort's `(order[a.urgency] ?? 4) - (order[b.urgency] ?? 4)` to `(a.urgency ? order[a.urgency] : 4) - (b.urgency ? order[b.urgency] : 4)`; change the unconditional `[${escapeHtml(w.urgency)}]` label (currently `:112`) to `${w.urgency ? `[${escapeHtml(w.urgency)}]` : ''}` — a null urgency renders no bracketed label, mirroring `CarePlanView.tsx`'s decision exactly.
     4. **Keep unchanged, do not delete or edit**: the readability breakdown block (currently `:137-150`, the `if (includeReadability && grading?.enabled && grading.entries?.length)` branch and its `methodMap` grouping), the `grading` parameter, and the `BuildPdfHtmlOptions` interface (currently `:12-16`) — none of the three flags or their defaults change in this file.
     5. **Reorder sections** to match `CarePlanView.tsx`'s eight-card order: move the low-priority block (currently `:152-155`, gated on `includeLowPriority && result.low_priority?.length`) to immediately **before** the glossary block (currently `:130-135`, gated on `includeGlossary && result.terms && Object.keys(result.terms).length > 0`); keep the Readability block (currently `:137-150`) appended **last**, after Glossary — it is not one of the eight `CarePlan` sections. Final `sections.push(...)` order: What You Need to Know → Why You Came In → What the Doctor Found → Next Steps → What to Watch For → Questions to Ask → Other Items (low-priority) → Medical Terms Glossary → Readability.
   - Do **not** touch `escapeHtml`, the print CSS block at the bottom of the file, or the header/footer markup.
   - Acceptance criteria:
     - `grep -n "main_conclusion\|change_description" frontend/src/utils/buildPdfHtml.ts` returns zero hits.
     - `npx tsc -b` (from `frontend/`) compiles this file with no errors.
     - A `CarePlan` with `low_priority`, `terms`, and enabled `grading` all populated produces HTML where `html.indexOf('Other Items') < html.indexOf('Medical Terms Glossary')` and `html.indexOf('Medical Terms Glossary') < html.indexOf('Readability')`.
     - A done-status Next Steps row's title renders with `text-decoration:line-through` in the output HTML; a to_do row's does not.
     - `BuildPdfHtmlOptions`, `includeGlossary`/`includeReadability`/`includeLowPriority`'s `?? true` defaults (currently `:19-21`), and the `grading` parameter are byte-for-byte unchanged from today.
     - Permanent tests land in Task 10's `buildPdfHtml.test.ts`.

### Task 6 — `frontend/src/utils/downloadReport.ts` — flip the three flags to `true`

   - Files: `frontend/src/utils/downloadReport.ts`
   - Dependency: land after Task 5 (the sections being activated must already render correctly).
   - Changes (PRD §4.7, §2): change the `buildPdfHtml(carePlan, grading, { includeGlossary: false, includeReadability: false, includeLowPriority: false })` call (currently `:7-10`) to `buildPdfHtml(carePlan, grading, { includeGlossary: true, includeReadability: true, includeLowPriority: true })`. Nothing else in this file changes — the `downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void` signature stays exactly as-is; do not drop the options argument and rely on `buildPdfHtml`'s own `?? true` defaults instead — PRD §4.7 is explicit that the three values must be spelled out literally at this call site so a reader sees the decision here, not inferred from a different file's defaults.
   - Acceptance criteria:
     - `frontend/src/utils/downloadReport.ts` passes `includeGlossary: true, includeReadability: true, includeLowPriority: true` explicitly (not omitted, not relying on defaults).
     - The function signature (`carePlan: SimplifiedCarePlan, grading: Grading`) is unchanged from today.
     - Permanent test updated in Task 8.

### Task 7 — Two new CSS rule blocks in `frontend/src/App.css`

   - Files: `frontend/src/App.css`
   - Dependency: none (independent of the other tasks; needed for Task 3's Next Steps card to render with its intended chrome, but does not block that task's compile/test pass — the JSX references these classes regardless of when the CSS lands, so land this task whenever convenient, before or alongside Task 3).
   - Changes (PRD §4.6): add exactly the two rule blocks given in PRD §4.6, alongside the existing `.result-list`/`.glossary-item` block (`App.css:332-376`):
     ```css
     .next-step-checkbox {
       flex-shrink: 0;
       font-family: inherit; /* Unicode box-drawing glyphs render fine in the app's system font stack */
     }

     .next-step-type-label {
       font-size: 0.7rem;
       font-weight: 600;
       color: var(--text-muted);
       background: var(--surface-hover);
       border-radius: var(--radius-pill);
       padding: 1px 8px;
       text-transform: uppercase;
       letter-spacing: 0.03em;
     }
     ```
     Use only existing custom properties (`--text-muted`, `--surface-hover`, `--radius-pill`) — do not add new `:root` color tokens; `#059669`/`#9CA3AF` stay as one-off inline hex values in `CarePlanView.tsx`/`buildPdfHtml.ts`, matching the file's existing convention for other inline hex colors.
   - Acceptance criteria:
     - `grep -n "\.next-step-checkbox\|\.next-step-type-label" frontend/src/App.css` returns exactly one rule block each.
     - No existing rule in `App.css` is removed, renamed, or reordered.

### Task 8 — `frontend/src/tests/utils/downloadReport.test.ts` — invert the one content-drifted test

   - Files: `frontend/src/tests/utils/downloadReport.test.ts`
   - Dependency: land after Task 6 (asserts the post-flip behavior).
   - Changes (PRD §7.2): the five `downloadReport(fixture, grading)` call sites (`:33,47,57,64,72`) keep compiling untouched — no signature change to react to. Replace the test at `:68-80` (`'omits the Medical Terms Glossary, Readability, and Other Items sections from the downloaded report'`) with its inverse, using the same existing fixture (`:9-14`, which already carries a `terms` entry, a `low_priority` entry, and enabled `grading`):
     ```typescript
     it('includes the Medical Terms Glossary, Readability, and Other Items sections in the downloaded report', () => {
       const fakeWindow = { document: { write: vi.fn(), close: vi.fn() }, print: vi.fn() };
       vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window);

       downloadReport(fixture, grading);

       const html = fakeWindow.document.write.mock.calls[0][0] as string;
       expect(html).toContain('Medical Terms Glossary');
       expect(html).toContain('Readability');
       expect(html).toContain('Other Items');
       // Sanity check: the rest of the report is still present.
       expect(html).toContain('Take it easy for a week.');
     });
     ```
     No other test in this file changes — `fixture`'s `medications`/`tests`/`procedures`/`other`/`follow_up` are all empty arrays already, so none of them needs a `status` field added to keep this file's own fixture valid against Task 1's new required `status`. (If `npx tsc -b` reports otherwise once this file is checked, that means the fixture literal itself needs `status` on any non-empty item array here — none exist today, so no change is expected.)
   - Acceptance criteria: `npx vitest run src/tests/utils/downloadReport.test.ts` (from `frontend/`) passes in full, including the inverted test; `grep -n "omits the Medical Terms Glossary" frontend/src/tests/utils/downloadReport.test.ts` returns zero hits.

### Task 9 — Regenerate `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json`

   - Files: `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json`
   - Dependency: land after Task 1 (defines the shape this fixture must match). Independent of Tasks 2-8 otherwise.
   - Changes (PRD §7.1): hand-edit the `care_plan` object (leave `metrics`, `input`, `grading` untouched) —
     - Delete `care_plan.urgency`, `care_plan.additional_info`, `care_plan.raw` (all three currently present, at `:273`, `:387`, `:382-386`).
     - Delete `care_plan.diagnosis.main_conclusion` (currently `:282`, `"Your blood pressure is still higher than the goal range."`).
     - Delete `importance`/`source` from `medications[0]` (`:305-306`), `tests[0]` (`:318-319`), `procedures[0]` (`:329-330`), `other[0]` (`:344-345`), `warning_signs[0]` (`:361-362`).
     - Fold `medications[0].change` (`true`, `:307`) / `medications[0].change_description` (`"This medicine was started today.", :308`) into a single field: `"change": "This medicine was started today."`.
     - Add `"status": "to_do"` to `medications[0]`, `tests[0]`, `procedures[0]`, `other[0]`, `follow_up[0]` — nothing in the fixture's existing narrative ("in 2 weeks," "daily," home monitoring not yet started) describes a completed action, so `"to_do"` is the only value consistent with the surrounding text (PRD §7.1/§9 `[RESOLVED]`).
     - Add `"summary_fact_ids": [1, 2, 3]` at the top level of `care_plan`, as a sibling of `summary`.
     - Leave `warning_signs[0].urgency` as `"emergency"` (non-null) — the fixture's one warning sign is a real emergency case in its own narrative ("Go to the emergency room"); the null-urgency case is covered by Task 10's dedicated unit tests instead of mutating this shared, narratively-coherent fixture.
     - Leave everything else (`doc_type`, `version`, `summary`, `reason_for_visit`, `diagnosis.changed_since_last_visit`, `diagnosis.details`, `questions`, `low_priority`, `note`, `terms`) unchanged.
   - Acceptance criteria:
     - The rewritten JSON is valid JSON and contains none of: `urgency`, `additional_info`, `raw`, `main_conclusion`, `importance`, `source` (as `care_plan` item-model field names — `terms.Hypertension.source` is `GlossaryTerm.source`, an unrelated, untouched field, and must stay), `change_description`.
     - Every entry in `medications`/`tests`/`procedures`/`other`/`follow_up` has a `"status": "to_do"` key.
     - `npx vitest run src/tests/components/ResultScreen.test.tsx src/tests/pages/HomePage.test.tsx` (from `frontend/`) passes once Task 10's companion fixes to `ResultScreen.test.tsx` land (this task's own change is content-only and needs no code change on its own to be valid JSON, but the tests that render it also need Task 10's `hideLowPriority`-test inversion to pass together).

### Task 10 — Update and add frontend tests: `ResultScreen.test.tsx`, `nextSteps.test.ts`, `CarePlanView.test.tsx`, `buildPdfHtml.test.ts`

   - Files: `frontend/src/tests/components/ResultScreen.test.tsx` (edit); `frontend/src/tests/utils/nextSteps.test.ts` (new); `frontend/src/tests/components/CarePlanView.test.tsx` (new); `frontend/src/tests/utils/buildPdfHtml.test.ts` (new)
   - Dependency: land after Tasks 1-7, 9 (needs the new types, `nextSteps.ts`, the updated `CarePlanView.tsx`/`buildPdfHtml.ts`, and the regenerated fixture all in place).
   - Changes:
     - **`ResultScreen.test.tsx`** (PRD §7.2, row 1):
       - Delete the three stray `urgency: 'normal'` keys at `:26`, `:68`, `:119` (harmless today since these literals target `JobDoc.output_data: Record<string, unknown> | null` and TS excess-property checking never fires on them, but they reference a field that no longer exists anywhere in the real contract).
       - Invert the test at `:61-77` (`'does not render "Other Items From Your Visit" even when low_priority has entries'`). Same fixture (`low_priority: ['Drink more water']`), same render, opposite assertions and a new name:
         ```typescript
         it('renders "Other Items From Your Visit" when low_priority has entries', () => {
           const jobDoc: JobDoc = {
             status: 'completed', stage: 5, name: 'With Low Priority', error_data: null,
             output_data: {
               metrics: { created_at: '2026-01-05T10:00:00Z' },
               grading: { entries: [], enabled: false, graded_at: null },
               care_plan: {
                 doc_type: 'care_plan', version: '1.2', summary: 'Rest up.',
                 reason_for_visit: [], diagnosis: { details: [] }, medications: [], tests: [],
                 procedures: [], other: [], follow_up: [], warning_signs: [], questions: [],
                 low_priority: ['Drink more water'],
               },
             },
           };
           render(<ResultScreen jobDoc={jobDoc} jobId="job-5" deletedRef={deletedRef} onRestart={vi.fn()} />);
           expect(screen.getByText('Other Items From Your Visit')).toBeInTheDocument();
           expect(screen.getByText('Drink more water')).toBeInTheDocument();
         });
         ```
       - No other test in this file changes — the realistic-payload test's own assertions (`/Lisinopril/`, `.medical-term` count) are unaffected by this PRD; they rely only on Task 9's fixture regeneration having landed.
     - **`frontend/src/tests/utils/nextSteps.test.ts`** (new file, PRD §7.3 — the load-bearing suite for this sub-project): implement every case PRD §7.3 lists under "the load-bearing suite for this sub-project":
       - `builds one row per actionable item across all five source arrays` — one item each in `medications`/`tests`/`procedures`/`other`/`follow_up`; assert `buildNextStepsRows(...)` returns exactly 5 rows.
       - `splits to_do before done, regardless of input order` — rows spanning both statuses out of type-precedence order; assert every `to_do` row precedes every `done` row.
       - `orders by the fixed type precedence within a status group` — one `to_do` item per type, fed in reverse-precedence order; assert output order is medication, test, procedure, follow_up, other.
       - `preserves original array order for two items of the same type and status` (stability check) — two medications, same status, distinguishable titles; assert input order is preserved.
       - `medication detail joins dosage/frequency/timing/duration with a single separator, omitting empty fields` — a medication with only `dosage` and `duration` set; assert `detail === "10 mg · for 30 days"` shape (no double separator, no leading/trailing separator).
       - `follow_up row uses description as title and time_frame as detail`.
       - `other row surfaces steps separately from detail` — assert `row.steps` is the original array, not concatenated into `row.detail`.
     - **`frontend/src/tests/components/CarePlanView.test.tsx`** (new file, PRD §7.3 — closes the "no direct test exists" gap):
       - `renders exactly eight top-level result cards for a fully-populated care plan` — count `.result-card` elements (or query by each expected heading) against a fixture exercising every section.
       - `does not render a Data Sources card even if additional_info-shaped data is force-injected` — regression guard against the deleted card's reappearance; construct a `result` object with an extra unexpected key and assert no "Data Sources" text renders.
       - `renders a check mark for status "done" and an empty checkbox for status "to_do"` — one medication of each status; assert both glyphs appear (query by the `aria-hidden` glyph's parent, or by the `sr-only` "Done: "/"To do: " text).
       - `renders a strikethrough on a done row's title but not on a to_do row's title` — same two-status fixture; assert the done title's inline style includes `line-through` and the to_do title's does not.
       - `renders a null-urgency warning sign last, in grey, with no urgency badge` — three warning signs, one `null`, fed in an order where `null` is first; assert it renders last and no bracketed label text appears next to its symptom.
       - `never drops a null-urgency warning sign from the list` — same fixture; assert the count of rendered warning-sign blocks equals the input length.
     - **`frontend/src/tests/utils/buildPdfHtml.test.ts`** (new file, PRD §7.3 — none exists today, a real gap independent of this PRD's changes):
       - `includes a Next Steps section with a checkbox glyph per item, matching the app's type precedence order`.
       - `includes the Medical Terms Glossary, Readability, and Other Items sections when their flags default to true and their data is present` — direct-unit-tests the three branches that were unreachable through `downloadReport` before this PRD.
       - `orders the Other Items section before the Medical Terms Glossary section, with Readability last` — a fixture populating `low_priority`, `terms`, and `grading` together; assert index ordering.
       - `omits a section when its flag is explicitly false`, e.g. `includeGlossary: false` — confirms the flags still function as real knobs.
       - `renders no Medical Terms Glossary heading at all when terms is empty` — guards the existing `Object.keys(result.terms).length > 0` guard now that the flag defaults to reaching this code.
       - `renders a strikethrough style on a done Next Steps row's title in the generated HTML, and none on a to_do row's`.
       - `omits the Next Steps section entirely when all five source arrays are empty`.
   - Acceptance criteria:
     - `npx vitest run` (from `frontend/`) passes in full across all four files, including every case named above.
     - `grep -n "urgency: 'normal'" frontend/src/tests/components/ResultScreen.test.tsx` returns zero hits; `grep -n "does not render \"Other Items" frontend/src/tests/components/ResultScreen.test.tsx` returns zero hits.

### Task 11 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-10.
   - Acceptance criteria:
     - From `frontend/`, `npx tsc -b` succeeds with zero errors.
     - From `frontend/`, `npx vitest run` passes with zero failures.
     - `grep -rn "additional_info\|main_conclusion\|change_description\|hideLowPriority" frontend/src --include=*.ts --include=*.tsx` returns zero hits anywhere in the frontend source tree (tests included).
     - `npx eslint .` (from `frontend/`) is clean for every file this PRD touched.

---

## Handed off to / from other sub-projects (specified here, not implemented here — do not action as part of this task list)

- **From 05 (review-and-correct)**: `summary` may now legitimately come back as `""` (a drifted summary that `correct()` cleared), per 05's own hand-off note (`prds/05-review-and-correct/TASKS.md`, "To 08" section): "08 should render an empty 'What You Need to Know' card the same way it already handles an empty `questions` array (hide the card, don't show an empty shell)." **Verified against the real code and left alone, not a new task**: `CarePlanView.tsx:141`'s guard is already `{result.summary && (...)}` and `buildPdfHtml.ts:26`'s is already `if (result.summary) {`. Both are falsy on `""` in JavaScript, so an empty-string summary already hides the card in both the app and the PDF today, with no code change needed — 05's hand-off is a pre-existing correctness property of this file, not a gap this PRD's own scope (§4.4's table lists this card "unchanged") needs to close. Flagged in this section rather than silently dropped, since the PRD itself does not mention it.
- **From 06 (pipeline-orchestration)**: `ProcessingScreen.tsx` / step labels (backend `Constants.Pipeline.PIPELINE_STEPS` renumbering) is 06's task, not this PRD's, even though `ProcessingScreen.tsx` lives in the same frontend directory this PRD otherwise owns — confirmed via the PRD README's cross-PRD coupling table and 06's own `TASKS.md` Task 8/13 (`frontend/src/components/ProcessingScreen.tsx`, `frontend/src/tests/components/ProcessingScreen.test.tsx`). Not actioned here.
- **To nothing**: this PRD is the leaf of the decomposition (PRD header, "Depended on by: nothing"). No sub-project depends on any output of this task list.

## Summary of what requires you (not a dev agent)

Per PRD §8, all five items are session-local visual/print QA or post-06 real-pipeline checks that cannot be automated by a dev agent:

1. **Visual QA of the Next Steps checkbox glyphs** (ngrok + pm2, `SERVICE_MODE=combined`): confirm `☑`/`☐` render as recognizable glyphs, not tofu boxes, in your actual browsers/OSes. If they render poorly, fall back to an inline SVG.
2. **Print-preview QA of the same glyphs** — print a sample report and confirm both states are visually distinct.
3. **Black-and-white print QA of the done-state strikethrough** — print (or print-preview in grayscale) a sample report with a mix of done/to-do Next Steps rows and confirm the strikethrough is legible without color.
4. **Confirm the `follow_up`-before-`other` type precedence reads correctly** against real care plans once 06's pipeline wiring produces real output — this PRD's order is a reasoned default, not validated against real patient-facing content.
5. **Spot-check the regenerated `realCarePlanOutput.fixture.json`** (Task 9) for narrative coherence, and once 06 produces a real note whose `warning_signs` mix a null urgency with non-null ones, capture that as a fixture and add coverage against it, supplementing (not replacing) Task 10's synthetic unit tests.

No PRD §9 items are `[OPEN]` — the gate was clear; all 11 tasks above derive from `[RESOLVED]` decisions only.
