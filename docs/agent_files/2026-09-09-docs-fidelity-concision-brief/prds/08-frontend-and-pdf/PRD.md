# PRD 08 — Frontend and PDF

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially the "Information architecture and concision" decision table and §3.10).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend` `CarePlan` contract — §6 of that PRD is the shape this PRD's types converge on), 04 (§6 — the "not stated in your note" sentinel and its exact scope), 07 (§6 — confirms no code change needed for glossary highlighting; verified independently below).
Depended on by: nothing (leaf of the decomposition).

## 1. Problem

The frontend renders the pre-inversion, pre-concision `CarePlan` shape: thirteen result cards (`frontend/src/components/CarePlanView.tsx`), a "Data Sources" card fed by a field (`additional_info`) no prompt rule populates and rendered under a fabricated heading with a variable literally named `path` (`CarePlanView.tsx:348-351`), a `diagnosis.main_conclusion` prose field the backend is deleting, `medications`/`tests`/`procedures`/`other`/`follow_up` split into five separate cards when the patient's real question is "what do I have to do," a `WarningSign.urgency` sort/color/label scheme with no null handling for a field the backend is making nullable, and a PDF export (`frontend/src/utils/buildPdfHtml.ts`) that independently duplicates every one of these problems plus a seven-method readability breakdown presented to a patient as an authoritative health-literacy assessment.

Verified against the real code, not assumed from the brief: `frontend/src/types/carePlan.ts` today does **not** declare `importance` or `source` on any item type — the frontend never rendered or typed these, so their backend deletion (01 §4.1) needs no frontend removal, only confirmation. `RawArtifacts` likewise never existed in any frontend type. `CarePlan.urgency` (top-level) appears only as a stray, unused key in three inline test fixtures (`ResultScreen.test.tsx:26,68,119`) — never read by any component. The real, load-bearing work is: the eight-card collapse, the Next Steps merge with status/type ordering, the null-safe warning-sign urgency path, deleting `main_conclusion`/`additional_info` render code, folding `Medication.change`, and the PDF mirroring all of it.

One further finding, from reading `frontend/src/utils/downloadReport.ts` directly: **the seven-method breakdown is already dead code in production.** `downloadReport` calls `buildPdfHtml(carePlan, grading, { includeGlossary: false, includeReadability: false, includeLowPriority: false })` — every option that would surface the breakdown, the glossary, or "Other Items" in the actual downloaded report is already hard-coded `false`. No real user has ever seen the breakdown in the PDF; only a direct unit test of `buildPdfHtml` (which doesn't exist) could exercise that branch. This is a deletion of unreachable code, not a behavior change to what patients download today.

## 2. Goals

- Collapse thirteen result cards to eight, in the brief's specified order, in both `CarePlanView.tsx` and `buildPdfHtml.ts`.
- Build one shared, order-and-precedence-defining module (`frontend/src/utils/nextSteps.ts`) that both the app and the PDF call, so "the same plan always renders in the same order, in the app and in the PDF" is a structural guarantee, not a maintained-by-hand coincidence between two files.
- Update `frontend/src/types/carePlan.ts` to match 01's backend contract exactly: remove `additional_info`, `CarePlan.urgency` (already absent — confirm and guard against reintroduction), `Diagnosis.main_conclusion`; fold `Medication.change`/`change_description`; add required `status` to the five actionable-item types; make `WarningSign.urgency` nullable; add `summary_fact_ids` (unused by any renderer, present for type fidelity only).
- Make every `WarningSign.urgency` consumer (sort, color, badge label) null-safe, with null rendering grey, sorting last, and never being dropped from the list.
- Delete the "Data Sources" card and `diagnosis.main_conclusion` rendering from both `CarePlanView.tsx` and `buildPdfHtml.ts`.
- Delete the readability breakdown from `buildPdfHtml.ts` and simplify `downloadReport.ts`'s signature accordingly (§4.7).
- Regenerate `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json` against the new contract, and specify every other test file's required changes.

## 3. Non-Goals

- No backend file changes. This PRD consumes 01's `CarePlanContent` contract and 04's render-time content contract (the "not stated" sentinel, nullable `urgency`) as given; if either is wrong for the frontend's needs, that is raised in §9, not patched around here.
- No design-system rework. New CSS is additive (a handful of rules for the Next Steps checkbox/checkmark and its type-label chip) inside the existing `App.css` custom-property system (`--accent-*`, `--text-*`, `--radius-*`); no new stylesheet, no CSS framework, no rewrite of the existing card chrome (`result-card`, `result-card-header`, etc., all unchanged).
- No interactivity added to the Next Steps checkboxes. They are a read-only rendering of `status`, not an editable checklist — there is no persistence layer to write a toggle back to (the job document is deleted the instant `ResultScreen` mounts, per the brief's own non-goals), so an editable checkbox would be a UI lie.
- No change to `frontend/src/types/envelope.ts`'s own declarations. `SimplifiedCarePlan = CarePlanContent` is a type alias; once `carePlan.ts` is corrected, `envelope.ts` reflects the new shape with zero edits to its own file. Verified by reading it (§4.1) rather than assumed.
- No change to `MedicalTerm.tsx` or `renderTextWithTerms`'s matching algorithm. 07 §6 states no frontend code change is needed for glossary highlighting; §4.2 below independently re-verifies that claim against the real code rather than taking it on faith.
- No per-PR preview environment, no clinical-fidelity evaluation suite (global out-of-scope).
- No versioning of the fixture or the types. Old shapes are deleted, not deprecated.

## 4. Architecture Decisions

### 4.1 `frontend/src/types/carePlan.ts` — full rewrite

Old (current file, 67 lines) → new, field by field, mirroring 01 §4.1/§6 exactly:

| Type | Field | Old | New |
|---|---|---|---|
| `CarePlanContent` | `additional_info` | `string[]` optional | **deleted** |
| `CarePlanContent` | `summary_fact_ids` | — | **added**: `number[]` (not rendered anywhere; present so the type is a true mirror of the backend contract, per 01 §6's own framing — "08 may ignore it entirely") |
| `Diagnosis` (inline object) | `main_conclusion` | `string` optional | **deleted** |
| `Medication` | `change` | `boolean` optional | **changed**: `string` (empty string = nothing to report, matching 01 §4.1's fold) |
| `Medication` | `change_description` | `string` optional | **deleted** (folded into `change`) |
| `Medication`/`Test`/`Procedure`/`OtherInstruction`/`FollowUp` | `status` | — | **added, required**: `'to_do' \| 'done'` |
| `WarningSign` | `urgency` | `'emergency' \| 'call_doctor' \| 'monitor' \| 'normal_side_effect'` (required, never null) | **changed**: same union `\| null` (still required — the key is always present, the value may be null) |

New file (unchanged: `StepStatus`, `AppState`, `PipelineStep`, `GlossaryTerm`, `TermsMap` — verbatim from today, not reproduced below):

```typescript
export type ItemStatus = 'to_do' | 'done';

export interface DiagnosisDetail {
  title: string;
  plain_name?: string;
  description: string;
  what_it_means_for_you?: string;
  severity?: 'high' | 'medium' | 'low';
}

export interface Medication {
  title: string;
  plain_name?: string;
  why?: string;
  dosage?: string;
  frequency?: string;
  timing?: string;
  duration?: string;
  instructions?: string;
  side_effects_to_watch?: string;
  change: string;          // "" means nothing to report; non-empty is a plain-language change note
  status: ItemStatus;
}

export interface Test {
  title: string;
  plain_name?: string;
  why?: string;
  description: string;
  preparation?: string;
  status: ItemStatus;
}

export interface Procedure {
  title: string;
  plain_name?: string;
  why?: string;
  what_to_expect?: string;
  timeframe?: string;
  status: ItemStatus;
}

export interface OtherInstruction {
  title: string;
  why?: string;
  steps?: string[];
  description?: string;
  frequency?: string;
  duration?: string;
  status: ItemStatus;
}

export interface FollowUp {
  time_frame: string;
  description: string;
  status: ItemStatus;
}

export interface WarningSign {
  symptom: string;
  what_it_might_mean?: string;
  what_to_do: string;
  urgency: 'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect' | null;
  related_to?: string;
}

export interface CarePlanContent {
  summary: string;
  summary_fact_ids: number[];   // internal provenance; never rendered (brief §3.10 — the ledger is not shown to the patient)
  reason_for_visit: Array<{ reason: string; description: string }>;
  diagnosis: {
    changed_since_last_visit?: string;
    details: DiagnosisDetail[];
  };
  medications: Medication[];
  tests: Test[];
  procedures: Procedure[];
  other: OtherInstruction[];
  follow_up: FollowUp[];
  warning_signs: WarningSign[];
  questions: string[];
  low_priority: string[];
  terms?: TermsMap;
}
```

`Test`/`Procedure`/`OtherInstruction`/`FollowUp` are promoted from inline anonymous object types (as they were before) to named interfaces, because `nextSteps.ts` (§4.3) needs to reference each item type by name in its discriminated-union row type — an anonymous inline type has no name to reference. This is a mechanical consequence of the merge, not a stylistic change made for its own sake.

### 4.2 Independent verification: glossary highlighting needs no change

07 §6 claims `renderTextWithTerms` (`CarePlanView.tsx:6-51`) derives 100% of its highlighting from `Object.keys(terms)` with no separate "is this interesting" logic, so nothing in 08 changes code-side. Confirmed by direct read: the function's only inputs are `text: string` and `terms: TermsMap`; it does a case-insensitive longest-match scan over `Object.keys(terms)` with no filtering, capping, or scoring of its own (`CarePlanView.tsx:11,22-29`). Whatever keys 07 puts in `CarePlan.terms` are exactly what gets boxed. **No change needed to `renderTextWithTerms` or `MedicalTerm.tsx`.** One cosmetic-only, optional item: 07 §6 notes glossary keys are now lowercase literal aliases (`"plaque"`, not `"Plaque (in an artery)"`), and `CarePlanView.tsx:340`'s glossary-card heading renders the raw key uncapitalized. Left as `[DEFERRED]` in §9 — the higher-traffic surface (inline highlighted spans) already renders the term in whatever case it appears in body text, unaffected either way.

### 4.3 New module: `frontend/src/utils/nextSteps.ts`

**Why a new shared module, not duplicated logic in two files.** The brief requires "a FIXED type precedence so the same plan always renders in the same order, in the app and in the PDF" (decision-log row 61). Two independent implementations of the same sort are exactly the drift risk the brief argues against elsewhere (07 §4.4's "one projection, both consumers" reasoning for `render_care_plan_text`). One function, two callers.

The five source arrays (`medications`, `tests`, `procedures`, `other`, `follow_up`) collapse into five Next Steps row kinds — `warning_signs`, `reason_for_visit`, and `diagnosis` are not actionable items and stay in their own cards.

**Fixed type precedence** (within each status group):

| Order | Type | Row label | Rationale |
|---|---|---|---|
| 1 | `medication` | "Medication" | Most frequent, most concretely actionable item type; patients scan for these first. |
| 2 | `test` | "Test" | Scheduled or already-run diagnostic action, second most common. |
| 3 | `procedure` | "Procedure" | Interventions performed on the patient — rarer than tests, still clinical. |
| 4 | `follow_up` | "Follow-up" | A future appointment/contact — distinct from a self-administered action. |
| 5 | `other` | "Other" | Catch-all (diet, activity, self-monitoring) — least specific, ordered last. |

This mirrors today's pre-merge card order (Medications → Tests → Procedures → Other → Follow-Up) with `follow_up` moved ahead of `other`, since a scheduled appointment is a harder commitment than a loosely-defined instruction like "drink more water daily." This is the one substantive judgment call this PRD makes that the brief leaves open; recorded `[RESOLVED]` in §9.

```typescript
import type {
  CarePlanContent, Medication, Test, Procedure, OtherInstruction, FollowUp, ItemStatus,
} from '../types/carePlan';

export type NextStepType = 'medication' | 'test' | 'procedure' | 'follow_up' | 'other';

export const NEXT_STEPS_TYPE_ORDER: Record<NextStepType, number> = {
  medication: 0,
  test: 1,
  procedure: 2,
  follow_up: 3,
  other: 4,
};

export const NEXT_STEPS_TYPE_LABELS: Record<NextStepType, string> = {
  medication: 'Medication',
  test: 'Test',
  procedure: 'Procedure',
  follow_up: 'Follow-up',
  other: 'Other',
};

// One row shape for every type. `title`/`why`/`detail` are pre-extracted plain
// strings (still containing raw text for the caller to run through
// renderTextWithTerms / escapeHtml) so CarePlanView and buildPdfHtml never
// switch on `type` themselves -- the branching happens once, here.
export interface NextStepRow {
  type: NextStepType;
  status: ItemStatus;
  title: string;
  why?: string;
  detail?: string;   // one-line, type-specific detail (see field mapping below)
  steps?: string[];  // OtherInstruction only; a short sub-list, not folded into `detail`
}

// One join helper for every type's "one-line detail" -- filters empties,
// joins with the same separator used throughout CarePlanView.tsx today
// (e.g. the existing medication dosage/frequency/timing/duration join).
function joinDetail(...parts: Array<string | undefined>): string | undefined {
  const present = parts.filter(Boolean);
  return present.length ? present.join(' · ') : undefined;
}

/** Builds the merged, status-then-type-ordered Next Steps row list. The single
 * source of truth for ordering -- CarePlanView.tsx and buildPdfHtml.ts both
 * call this and neither re-implements the sort (brief decision-log row 61). */
export function buildNextStepsRows(carePlan: CarePlanContent): NextStepRow[] {
  const withTitle = (t: { plain_name?: string; title: string }) =>
    t.plain_name ? `${t.plain_name} (${t.title})` : t.title;

  const rows: NextStepRow[] = [
    ...carePlan.medications.map((m): NextStepRow => ({
      type: 'medication', status: m.status, title: withTitle(m), why: m.why,
      detail: joinDetail(m.dosage, m.frequency, m.timing, m.duration),
    })),
    ...carePlan.tests.map((t): NextStepRow => ({
      type: 'test', status: t.status, title: withTitle(t), why: t.why,
      detail: joinDetail(t.description, t.preparation),
    })),
    ...carePlan.procedures.map((p): NextStepRow => ({
      type: 'procedure', status: p.status, title: withTitle(p), why: p.why,
      detail: joinDetail(p.what_to_expect, p.timeframe),
    })),
    ...carePlan.follow_up.map((f): NextStepRow => ({
      type: 'follow_up', status: f.status, title: f.description,
      detail: joinDetail(f.time_frame),
    })),
    ...carePlan.other.map((o): NextStepRow => ({
      type: 'other', status: o.status, title: o.title, why: o.why, steps: o.steps,
      detail: joinDetail(o.description, o.frequency, o.duration),
    })),
  ];

  const statusOrder: Record<ItemStatus, number> = { to_do: 0, done: 1 };
  // Stable sort: JS Array.prototype.sort is spec-guaranteed stable since
  // ES2019, so items sharing a (status, type) pair keep their original
  // per-array relative order -- no explicit tiebreaker needed.
  return rows.sort((a, b) => {
    const byStatus = statusOrder[a.status] - statusOrder[b.status];
    if (byStatus !== 0) return byStatus;
    return NEXT_STEPS_TYPE_ORDER[a.type] - NEXT_STEPS_TYPE_ORDER[b.type];
  });
}
```

`FollowUp` has only `time_frame`/`description`/`status` — no separate `title` — so `description` plays the title role (mirroring how the current Follow-Up card already renders it, `CarePlanView.tsx:320-321`) and `time_frame` becomes the detail. `OtherInstruction.steps` stays a separate array rather than folding into `detail`: it's a short ordered list ("Sit quietly for 5 minutes." / "Write down the number."), and joining it with `·` would produce an unreadable run-on — both renderers emit it as a nested list instead, matching today's `CarePlanView.tsx:249-253` behavior.

### 4.4 `frontend/src/components/CarePlanView.tsx` — card inventory, old → new

| # | Old card (13 total) | Source field(s) | New card (8 total) |
|---|---|---|---|
| 1 | What You Need to Know | `summary` | **1. What You Need to Know** (unchanged) |
| 2 | Why You Came In | `reason_for_visit` | **2. Why You Came In** (unchanged) |
| 3 | What the Doctor Found | `diagnosis` | **3. What the Doctor Found** (drop `main_conclusion` rendering; `details`/`changed_since_last_visit` unchanged) |
| 4 | Your Medications | `medications` | merges into **4. Next Steps** |
| 5 | Tests | `tests` | merges into **4. Next Steps** |
| 6 | Procedures | `procedures` | merges into **4. Next Steps** |
| 7 | Other Instructions | `other` | merges into **4. Next Steps** |
| 8 | What to Watch For | `warning_signs` | **5. What to Watch For** (null-urgency handling added) |
| 9 | Questions to Ask at Your Next Visit | `questions` | **6. Questions to Ask at Your Next Visit** (unchanged) |
| 10 | Follow-Up | `follow_up` | merges into **4. Next Steps** |
| 11 | Other Items From Your Visit | `low_priority` | **7. Other Items From Your Visit** (unchanged) |
| 12 | Medical Terms Glossary | `terms` | **8. Medical Terms Glossary** (unchanged) |
| 13 | Data Sources | `additional_info` | **deleted entirely** |

Render order in the new file: What You Need to Know → Why You Came In → What the Doctor Found → **Next Steps** → What to Watch For → Questions → Other Items From Your Visit → Medical Terms Glossary. This is a straight re-slotting of the existing conditional-render blocks; no new state, no new props on `CarePlanView`.

**Diagnosis card** (`CarePlanView.tsx:161-191`): delete the `result.diagnosis.main_conclusion` guard clause and its `<p className="narrative-headline">` block (lines 161, 163-166). The card's guard condition becomes `result.diagnosis && result.diagnosis.details?.length > 0` (drop the `|| result.diagnosis.main_conclusion` disjunct — the field no longer exists on the type, so this is also a compile-time forcing function, not just a behavior change).

**Data Sources card** (`CarePlanView.tsx:348-358`): delete the entire block. No replacement.

**Next Steps card** (new, replaces the old Medications/Tests/Procedures/Other/Follow-Up blocks at `CarePlanView.tsx:193-262` and `316-325`):

```tsx
{(() => {
  const rows = buildNextStepsRows(result);
  return rows.length > 0 && (
    <ResultCard color="violet" icon="✅" title="Next Steps">
      {rows.map((row, i) => {
        const isDone = row.status === 'done';
        return (
          <div key={i} className="next-step-row" style={{ marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
              <span aria-hidden="true" className="next-step-checkbox"
                style={{ color: isDone ? '#059669' : '#9CA3AF', fontSize: '1.1rem' }}>
                {isDone ? '☑' : '☐'}
              </span>
              <span className="sr-only">{isDone ? 'Done: ' : 'To do: '}</span>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
                  <strong style={isDone ? { color: 'var(--text-secondary)' } : undefined}>
                    {withTerms(row.title)}
                  </strong>
                  <span className="next-step-type-label">{NEXT_STEPS_TYPE_LABELS[row.type]}</span>
                </div>
                {/* why/detail/steps use the same inline-style conventions (#1D4ED8 "Why:" line,
                    #374151 detail line, .result-list for steps) as every other card in this file */}
                {row.why && <p style={{ color: '#1D4ED8', fontSize: '0.875rem', margin: '4px 0 0 0' }}>Why: {withTerms(row.why)}</p>}
                {row.detail && <p style={{ color: '#374151', fontSize: '0.875rem', margin: '4px 0 0 0' }}>{withTerms(row.detail)}</p>}
                {(row.steps?.length ?? 0) > 0 && (
                  <ul className="result-list" style={{ marginTop: '4px' }}>
                    {row.steps?.map((step, si) => <li key={si}>{withTerms(step)}</li>)}
                  </ul>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </ResultCard>
  );
})()}
```

**Checkbox affordance, resolved.** `status: 'done'` renders `☑` in green (`#059669`, distinct from the existing violet/blue/teal category accents so it reads as a status indicator); `status: 'to_do'` renders `☐` in neutral grey. `status` is required with no null (01 §4.1), so the ternary is exhaustive by construction. A visually-hidden `sr-only` "Done: " / "To do: " prefix (the class already used for `aria-live` regions elsewhere) covers screen readers, since the glyph carries no accessible name on its own. This is a **static, read-only rendering of backend-supplied state**, so it uses `aria-hidden` + a text prefix rather than `role="checkbox"`/`aria-checked`, which would wrongly imply the control can be toggled (§3: no editable checklist, no persistence layer to write a toggle to).

**Warning-sign urgency — null handling** (`CarePlanView.tsx:264-282`, current `URGENCY_COLORS`/`URGENCY_LABELS`/`URGENCY_ORDER` maps and the sort at line 267):

```tsx
// URGENCY_COLORS/URGENCY_LABELS unchanged (emergency/call_doctor/monitor/normal_side_effect).
// URGENCY_ORDER unchanged (0-3). Two new constants, an explicit slot for null rather
// than relying on a `?? 4` fallback that only coincidentally equals "one past the last index":
const NULL_URGENCY_COLOR = '#9CA3AF'; // lighter than monitor/normal's #6B7280 -- "no info", not "low-priority-but-known"
const NULL_URGENCY_ORDER = 4;

[...result.warning_signs]
  .sort((a, b) => (a.urgency ? URGENCY_ORDER[a.urgency] : NULL_URGENCY_ORDER)
                 - (b.urgency ? URGENCY_ORDER[b.urgency] : NULL_URGENCY_ORDER))
  .map((sign, i) => {
    const color = sign.urgency ? URGENCY_COLORS[sign.urgency] : NULL_URGENCY_COLOR;
    return (
      <div key={i} style={{ borderLeft: `4px solid ${color}`, paddingLeft: '12px', marginBottom: '10px' }}>
        <strong>{withTerms(sign.symptom)}</strong>
        {sign.urgency && <span style={{ color, fontWeight: 700 }}>[{URGENCY_LABELS[sign.urgency]}]</span>}
        {sign.what_it_might_mean && <p>{withTerms(sign.what_it_might_mean)}</p>}
        <p style={{ color }}>{withTerms(sign.what_to_do)}</p>
      </div>
    );
  });
```

**Decision: a null-urgency warning sign gets no bracketed badge at all** (not "[UNKNOWN]", not "[NOT STATED]") — only the grey left border. The existing bracketed labels (`EMERGENCY`, `CALL DOCTOR`, `WATCH`, `NORMAL`) gloss a real clinical judgment the model made; inventing a fifth label for the absence of one would be the same affirmative-claim-from-silence the brief's whole first section argues against, just relocated from a schema default into a frontend string literal. Grey border plus last-sorted position is signal enough. This is a judgment call the brief leaves to the frontend layer specifically — recorded `[RESOLVED]` in §9.

The old sort's `?? 4` fallback happened to put an unmapped/`undefined` urgency last already, but the color lookup had no equivalent safety (`URGENCY_COLORS[null]` would fall through its own `?? '#6B7280'` to a color indistinguishable from `monitor`/`normal_side_effect`, silently failing the "renders grey [distinctly]" requirement). Both are replaced with an explicit `sign.urgency ? X[sign.urgency] : Y` ternary for clarity and correctness rather than relying on incidental fallback coincidence.

**`DiagnosisDetail.severity` sort — confirmed unaffected.** `SEVERITY_ORDER[a.severity?.toLowerCase() ?? ''] ?? 99` (`CarePlanView.tsx:174-177`) already sorts `undefined` last, because `severity` was already nullable pre-brief (01 §4.1's own precedent). No code change; verified by reading.

**Medication `change` rendering** (`CarePlanView.tsx:198`): old `{med.change && <span ...>[{med.change_description || 'CHANGED'}]</span>}` (boolean gate, string fallback) becomes `{med.change && <span ...>[{med.change}]</span>}` — `change` is now the string itself, so a non-empty value is both the gate and the content; the `|| 'CHANGED'` fallback is deleted since the folded field can't represent "changed=true but no description."

### 4.5 `frontend/src/utils/buildPdfHtml.ts` — mirrored changes

Every change in §4.4 is mirrored here using the **same** `buildNextStepsRows` import — the entire point of centralizing it in §4.3:

- Delete the `diagnosis.main_conclusion` branch (lines 37-53).
- `additional_info` was never referenced in this file — nothing to remove, just confirm it stays that way.
- Replace the five separate sections (`Your Medications`, `Tests`, `Procedures`, `Other Instructions`, `Follow-Up` — lines 55-128) with one `Next Steps` section built from `buildNextStepsRows(result)`:

```typescript
const rows = buildNextStepsRows(result);
if (rows.length) {
  const items = rows.map(row => {
    const box = row.status === 'done' ? '&#9745;' : '&#9744;'; // ☑ / ☐ numeric HTML entities
    const color = row.status === 'done' ? '#059669' : '#9CA3AF';
    const stepsHtml = row.steps?.length
      ? `<ul style="margin:4px 0 0 20px;">${row.steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>` : '';
    return `<div style="padding:8px 12px;margin-bottom:6px;background:#F9FAFB;border-radius:6px;">
      <span style="color:${color};">${box}</span> <strong>${escapeHtml(row.title)}</strong>
      <span style="font-size:11px;color:#6B7280;">${escapeHtml(NEXT_STEPS_TYPE_LABELS[row.type])}</span>
      ${row.why ? `<br><span style="color:#1D4ED8;font-size:13px;">Why: ${escapeHtml(row.why)}</span>` : ''}
      ${row.detail ? `<br><span style="color:#374151;font-size:13px;">${escapeHtml(row.detail)}</span>` : ''}
      ${stepsHtml}
    </div>`;
  }).join('');
  sections.push(`${h2('Next Steps')}${items}`);
}
```

- Null-safe warning-sign urgency, mirroring §4.4's decision exactly: the sort's `order[a.urgency] ?? 4`-style fallback becomes `a.urgency ? order[a.urgency] : 4`, and the bracketed `[${escapeHtml(w.urgency)}]` label (current `buildPdfHtml.ts:112`) is wrapped in `w.urgency ? ... : ''` so a null renders no label — same one-line ternary pattern as §4.4, applied to template strings instead of JSX.
- **Delete the entire readability breakdown block** (current `buildPdfHtml.ts:137-150`, the `if (includeReadability && grading?.enabled ...)` branch and its `methodMap` grouping logic) and the `grading` parameter along with it — see §4.7 for why this cascades into `downloadReport.ts`'s signature.
- Delete the `BuildPdfHtmlOptions` interface's `includeReadability` flag entirely; `includeGlossary`/`includeLowPriority` are also removed — see §4.7 for why all three options go away together, not just the readability one.

### 4.6 New CSS: `.next-step-checkbox`, `.next-step-type-label`

Two small additions to `App.css`, alongside the existing `.result-list`/`.glossary-item` block (`App.css:332-376`), using only existing custom properties:

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

No new color tokens added to `:root` — `#059669`/`#9CA3AF` are used as one-off inline hex values, matching `CarePlanView.tsx`'s existing convention (`#D97706`, `#1D4ED8`, etc. are all inline hex today, not custom properties).

### 4.7 `frontend/src/utils/downloadReport.ts` — signature simplification

**Old:**
```typescript
export function downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void {
  trackEvent({ name: 'report_downloaded', params: {} });
  const html = buildPdfHtml(carePlan, grading, {
    includeGlossary: false, includeReadability: false, includeLowPriority: false,
  });
  ...
}
```

**New:**
```typescript
export function downloadReport(carePlan: SimplifiedCarePlan): void {
  trackEvent({ name: 'report_downloaded', params: {} });
  const html = buildPdfHtml(carePlan);
  ...
}
```

**Why this is a real behavior change, not just cleanup.** Today's call site opts *out* of the glossary, readability, and low-priority sections in the actual downloaded PDF (all three flags `false`) — narrower than what `CarePlanView.tsx` shows on-screen. This sub-project's own task brief is explicit that the PDF must mirror "**the same eight sections**" as the app, so the PDF stops being a deliberately-trimmed subset. This is a direct instruction for this sub-project (the parent design brief is silent on PDF/app parity either way), implemented as stated. Since every option existed solely to carve the report down below eight sections, and no fewer-than-eight use case remains, `BuildPdfHtmlOptions` is deleted outright rather than kept with new defaults. `grading` drops from both signatures because its only consumer (the readability breakdown) is deleted (§4.5); the on-screen single before/after figure lives entirely in `ResultScreen.tsx`, unaffected, and was never duplicated into the PDF path.

`ResultScreen.tsx:124` changes from `downloadReport(care_plan, grading)` to `downloadReport(care_plan)` — a one-line update; `grading` stays in scope there for the on-screen score widget (`ResultScreen.tsx:98,100-102,112-114`), untouched.

## 5. API Change Summary

**N/A — this PRD makes no API calls and defines no request/response shapes.** It consumes 01's already-settled `CarePlanContent` HTTP response shape (01 §5/§6) as a fixed input and 04's render-time content contract (04 §6: the literal string `"Not stated in your note."` may appear in any `why` field; `questions` may be `[]`; `warning_signs[].urgency` may be `null`). No backend route, status code, or error shape is referenced or changed by anything in this PRD.

## 6. Frontend Change Summary

Every file this PRD touches, and the shape of the change:

| File | Change |
|---|---|
| `frontend/src/types/carePlan.ts` | Full rewrite per §4.1 — deletions, the `status` addition, the `change` fold, nullable `urgency`. |
| `frontend/src/types/envelope.ts` | **No change** — `SimplifiedCarePlan = CarePlanContent` is a type alias; verified by reading, not assumed. |
| `frontend/src/utils/nextSteps.ts` | **New file** — `buildNextStepsRows`, `NEXT_STEPS_TYPE_ORDER`, `NEXT_STEPS_TYPE_LABELS`, `NextStepRow`/`NextStepType` (§4.3). |
| `frontend/src/components/CarePlanView.tsx` | Eight-card reorder; Data Sources deleted; `main_conclusion` rendering deleted; Next Steps card added (calls `buildNextStepsRows`); null-safe warning-sign urgency; `change`/`change_description` fold (§4.4). |
| `frontend/src/utils/buildPdfHtml.ts` | Mirrors `CarePlanView.tsx`'s changes; readability breakdown deleted; `grading` parameter and `BuildPdfHtmlOptions` deleted (§4.5). |
| `frontend/src/App.css` | Two new rule blocks, `.next-step-checkbox`/`.next-step-type-label` (§4.6). No existing rule removed or renamed. |
| `frontend/src/utils/downloadReport.ts` | Signature drops `grading`; calls `buildPdfHtml(carePlan)` with no options (§4.7). |
| `frontend/src/components/ResultScreen.tsx` | One-line call-site update: `downloadReport(care_plan)` (§4.7). No other change — the before/after score widget (`ResultScreen.tsx:112-114`) already shows a single combined figure and is otherwise untouched. |
| `frontend/src/components/MedicalTerm.tsx` | **No change** (§4.2). |
| `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json` | Regenerated — see §7.1. |

## 7. Testing

### 7.1 `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json` — regeneration

No generator script exists for this fixture (verified by repo-wide search — it was hand-authored once "from the actual pipeline models," per the comment at `ResultScreen.test.tsx:13-15`, and committed as static JSON). It must be hand-edited to the new contract, field by field, using 01 §4.1's table as the source of truth:

- Delete top-level `care_plan.urgency`, `care_plan.additional_info`, `care_plan.raw` (all three currently present in the fixture — confirmed by direct read).
- Delete `care_plan.diagnosis.main_conclusion` ("Your blood pressure is still higher than the goal range.").
- Delete `importance`/`source` from the one `medications[0]`, `tests[0]`, `procedures[0]`, `other[0]`, `warning_signs[0]` entry each currently carries them.
- Fold `medications[0].change` (`true`) / `medications[0].change_description` ("This medicine was started today.") into `medications[0].change: "This medicine was started today."`.
- Add `status: "to_do"` to `medications[0]`, `tests[0]`, `procedures[0]`, `other[0]`, `follow_up[0]` — nothing in the fixture's existing narrative ("in 2 weeks," "daily," home monitoring not yet started) describes a completed action, so `"to_do"` is the only value consistent with the text sitting next to it (§9 records this as a content judgment, not a schema requirement).
- Add `care_plan.summary_fact_ids: [1, 2, 3]` (small, non-empty, matching 01 §7.1's own recommendation for its backend-side fixture, for consistency).
- Leave `warning_signs[0].urgency` as `"emergency"` (non-null) — the fixture's one warning sign is a real emergency case in its own narrative ("Go to the emergency room"); a null-urgency case is better covered by a small dedicated unit test (§7.3) than by mutating this shared, narratively-coherent fixture to add an artificial second warning sign.

### 7.2 Existing test files — impact and required changes

| File | Impact | Required change |
|---|---|---|
| `frontend/src/tests/components/ResultScreen.test.tsx` | Three inline fixtures carry a stray `urgency: 'normal'` key (lines 26, 68, 119) — harmless, since these literals target `JobDoc.output_data: Record<string, unknown> \| null`, so TS excess-property checking never fires. Uses `realCarePlanOutput.fixture.json` for its realistic-payload test. | Compiles and passes unchanged. Recommended cleanup: delete the three stray `urgency` keys. The realistic-payload test's own assertions (`/Lisinopril/`, `.medical-term` count) are unaffected by this PRD; it only needs §7.1's fixture regeneration to land for content fidelity. |
| `frontend/src/tests/pages/HomePage.test.tsx` | Same fixture dependency; its own inline `completedDoc` (lines 47-57) has no deleted fields — already minimal. | No change beyond §7.1's fixture regeneration. |
| `frontend/src/tests/utils/downloadReport.test.ts` | **Breaks.** (1) Every call is `downloadReport(fixture, grading)` — two-arg signature gone (§4.7). (2) Line 68's test asserts the *old* narrower PDF behavior this PRD inverts (§4.7). | Rewrite: (a) drop the second argument from all four `downloadReport(...)` calls; (b) drop the now-unused `Grading` import; (c) replace the "omits..." test with its inverse — assert `html.toContain('Medical Terms Glossary')`, `html.toContain('Other Items')`, and `html.not.toContain('Readability')`. |
| `frontend/src/tests/utils/validateFiles.test.ts` | Unaffected. | No change. |
| Every other `frontend/src/tests/**` file | Grepped for every deleted/changed field name and for `CarePlanView`/`buildPdfHtml`/`downloadReport` imports — zero hits outside the files above. | No change. |

### 7.3 New tests this PRD should add

No `CarePlanView.test.tsx` exists today — coverage is entirely indirect, through `ResultScreen.test.tsx`'s realistic-fixture render. Given this PRD adds real branching logic (status grouping, type precedence, null-urgency sort), that indirect coverage is not enough on its own; add:

- **`frontend/src/tests/utils/nextSteps.test.ts`** (new file, the load-bearing suite for this sub-project):
  - `builds one row per actionable item across all five source arrays` — one item each in `medications`/`tests`/`procedures`/`other`/`follow_up`; assert `buildNextStepsRows(...)` returns exactly 5 rows.
  - `splits to_do before done, regardless of input order` — construct rows spanning both statuses out of type-precedence order; assert every `to_do` row precedes every `done` row in the output.
  - `orders by the fixed type precedence within a status group` — one `to_do` item per type, fed in reverse-precedence order; assert output order is medication, test, procedure, follow_up, other.
  - `preserves original array order for two items of the same type and status` (stability check) — two medications, same status, distinguishable titles; assert they appear in input order.
  - `medication detail joins dosage/frequency/timing/duration with a single separator, omitting empty fields` — a medication with only `dosage` and `duration` set; assert `detail === "10 mg · for 30 days"` shape (no double separator, no leading/trailing separator).
  - `follow_up row uses description as title and time_frame as detail`.
  - `other row surfaces steps separately from detail` — assert `row.steps` is the original array, not concatenated into `row.detail`.
- **`frontend/src/tests/components/CarePlanView.test.tsx`** (new file — closes the "no direct test exists" gap):
  - `renders exactly eight top-level result cards for a fully-populated care plan` — count `.result-card` elements (or query by each expected heading) against a fixture exercising every section.
  - `does not render a Data Sources card even if additional_info-shaped data is force-injected` — regression guard against the deleted card's reappearance; construct a `result` object with an extra unexpected key and assert no "Data Sources" text renders.
  - `renders a check mark for status "done" and an empty checkbox for status "to_do"` — one medication of each status; assert the two distinct glyphs both appear (query by the `aria-hidden` glyph's parent, or by the `sr-only` "Done: "/"To do: " text).
  - `renders a null-urgency warning sign last, in grey, with no urgency badge` — three warning signs, one `null`, fed in an order where `null` is first; assert it renders last and that no bracketed label text appears next to its symptom (regression guard against the resolved "no invented label" decision in §4.4).
  - `never drops a null-urgency warning sign from the list` — same fixture; assert the count of rendered warning-sign blocks equals the input length.
- **`frontend/src/tests/utils/buildPdfHtml.test.ts`** (new file — none exists today, a real gap independent of this PRD's changes):
  - `includes a Next Steps section with a checkbox glyph per item, matching the app's type precedence order`.
  - `never includes a Readability section, even when a fully-populated Grading object exists in scope` — guards the deletion in §4.5 (note: `buildPdfHtml` no longer takes a `grading` parameter at all after this PRD, so this test simply confirms no readability content appears in output built from `CarePlanContent` alone).
  - `omits the Next Steps section entirely when all five source arrays are empty` (mirrors the existing `result.X?.length` guard pattern already used for every other section).

## 8. Manual Intervention Required From You

- **Visual QA of the Next Steps checkbox glyphs** (ngrok + pm2, `SERVICE_MODE=combined`): confirm `☑`/`☐` render as recognizable glyphs, not tofu boxes, in your actual browsers/OSes — Unicode box-drawing support varies by system font, and the app's `Inter` font stack may not cover them. If they render poorly, fall back to an inline SVG.
- **Print-preview QA of the same glyphs** — the brief calls the checkbox affordance out as "explicitly requested for print," and print-engine glyph rendering can differ from on-screen rendering across browsers. Print a sample report and confirm both states are visually distinct.
- **Confirm the `follow_up`-before-`other` type precedence (§4.3) reads correctly** against real care plans once 06's pipeline wiring produces real output — this PRD's order is a reasoned default, not validated against real patient-facing content.
- **Spot-check the regenerated `realCarePlanOutput.fixture.json`** (§7.1) for narrative coherence — a mechanical field-by-field edit risks internally inconsistent content only a human read would catch.

## 9. Open Questions & Decisions

- `[RESOLVED: Next Steps type precedence is medication (1), test (2), procedure (3), follow_up (4), other (5).]` — the brief requires "a fixed type precedence" but does not specify its order; this PRD's choice keeps the pre-merge card order for the first three types and moves `follow_up` ahead of `other` on the reasoning that a scheduled appointment is a harder commitment than a loosely-defined instruction (§4.3).
- `[RESOLVED: a null-urgency warning sign renders no bracketed badge text at all — only the grey left border and last-sorted position signal reduced information, never an invented label like "NOT STATED" or "UNKNOWN".]` — consistent with the brief's core "don't invent from silence" principle, applied at the UI-label layer rather than only the schema-default layer (§4.4).
- `[RESOLVED: the Next Steps checkbox is a static, read-only rendering (aria-hidden glyph + sr-only text prefix), not an interactive role="checkbox" control.]` — there is no persistence layer to write a toggle back to; the job document is deleted the instant `ResultScreen` mounts (brief non-goals), so an editable checkbox would misrepresent what the UI can actually do (§4.4).
- `[RESOLVED: buildPdfHtml.ts/downloadReport.ts drop their include/exclude options and render all eight sections unconditionally, inverting today's narrower production behavior.]` — a direct instruction in this sub-project's task brief ("the same eight sections"), not a re-litigation of the parent brief (silent on PDF/app parity). Flagged prominently — a real behavior change to a user's download, not a pure refactor (§4.7).
- `[RESOLVED: Test, Procedure, OtherInstruction, FollowUp are promoted from inline anonymous types to named interfaces in carePlan.ts.]` — mechanical: `nextSteps.ts` needs to reference each type by name (§4.1).
- `[RESOLVED: glossary key capitalization for card-heading display is left as-is.]` — `[DEFERRED]` per 07 §6's own framing; the higher-traffic inline-highlight surface is unaffected either way (§4.2).
- `[RESOLVED: summary_fact_ids is added to the TypeScript type for contract fidelity but read by no component.]` — matches 01 §6's own framing that 08 may ignore it (§4.1).
- `[RESOLVED: the regenerated fixture sets status: "to_do" on all five actionable items.]` — nothing in the fixture's existing narrative describes a completed action (§7.1).
- `[OPEN: whether done-state rows deserve a stronger visual treatment than a color change (e.g. strikethrough).]` Not adopted here — the brief specifies only the checkbox affordance, and unrequested visual weight risks reading as the UI grading the patient's compliance. Revisit if manual QA (§8) finds it too subtle.
- `[OPEN: no fixture exercises a null-urgency warning sign alongside non-null ones in a realistic (non-synthetic) narrative.]` §7.3's synthetic test covers the mechanism; a real example awaits 06's pipeline wiring (mirrors 04 §8's identical caveat).
