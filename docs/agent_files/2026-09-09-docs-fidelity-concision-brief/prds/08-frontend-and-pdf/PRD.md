# PRD 08 — Frontend and PDF

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially the "Information architecture and concision" decision table and §3.10).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend` `CarePlan` contract — §6 of that PRD is the shape this PRD's types converge on), 04 (§6 — the "not stated in your note" sentinel and its exact scope), 07 (§6 — confirms no code change needed for glossary highlighting; verified independently below).
Depended on by: nothing (leaf of the decomposition).

## 1. Problem

The frontend renders the pre-inversion, pre-concision `CarePlan` shape: thirteen result cards (`frontend/src/components/CarePlanView.tsx`), a "Data Sources" card fed by a field (`additional_info`) no prompt rule populates and rendered under a fabricated heading with a variable literally named `path` (`CarePlanView.tsx:348-351`), a `diagnosis.main_conclusion` prose field the backend is deleting, `medications`/`tests`/`procedures`/`other`/`follow_up` split into five separate cards when the patient's real question is "what do I have to do," a `WarningSign.urgency` sort/color/label scheme with no null handling for a field the backend is making nullable, and a PDF export (`frontend/src/utils/buildPdfHtml.ts`) that independently duplicates every one of these problems plus a seven-method readability breakdown, currently unreachable via the production download path (see below, and §2/§4.5/§4.7 for the decision to activate rather than delete it).

Verified against the real code, not assumed from the brief: `frontend/src/types/carePlan.ts` today does **not** declare `importance` or `source` on any item type — the frontend never rendered or typed these, so their backend deletion (01 §4.1) needs no frontend removal, only confirmation. `RawArtifacts` likewise never existed in any frontend type. `CarePlan.urgency` (top-level) appears only as a stray, unused key in three inline test fixtures (`ResultScreen.test.tsx:26,68,119`) — never read by any component. The real, load-bearing work is: the eight-card collapse, the Next Steps merge with status/type ordering, the null-safe warning-sign urgency path, deleting `main_conclusion`/`additional_info` render code, folding `Medication.change`, and the PDF mirroring all of it.

One further finding, from reading `frontend/src/utils/downloadReport.ts` directly: **the seven-method breakdown, the glossary section, and the "Other Items" section are all currently dead code in the production download.** `downloadReport` calls `buildPdfHtml(carePlan, grading, { includeGlossary: false, includeReadability: false, includeLowPriority: false })` — every option that would surface any of the three in the actual downloaded report is already hard-coded `false`. No real user has ever seen any of them in the downloaded PDF; only a direct unit test of `buildPdfHtml` (which doesn't exist prior to this PRD) could exercise those branches.

**Decision: activate all three, don't delete them.** The report is scoped to mirror the app: the same eight `CarePlan` sections `CarePlanView.tsx` renders, plus the readability breakdown as supplementary detail for the patient's own downloaded record. This is a real behavior change to what patients download, not a deletion of unreachable code — see §2, §4.5, and §4.7 for the mechanics. It also surfaces a second finding: `ResultScreen.tsx` today calls `<CarePlanView result={care_plan} hideLowPriority />`, hiding the "Other Items From Your Visit" card on the result screen — the one place a real patient actually looks, as opposed to the download most will never open. Activating `includeLowPriority` in the PDF while leaving that prop in place would make the download show a section the app itself hides, which is a worse outcome than the dead-code asymmetry it replaces: it means the *only* place a patient ever sees "Other Items" is a PDF they have to think to download. **This PRD widens the result screen to match the PDF, not the other way around** — see §4.8 for the mechanics and §9 for the rejected alternative (narrowing the PDF back down instead).

## 2. Goals

- Collapse thirteen result cards to eight, in the brief's specified order, in both `CarePlanView.tsx` and `buildPdfHtml.ts`.
- Build one shared, order-and-precedence-defining module (`frontend/src/utils/nextSteps.ts`) that both the app and the PDF call, so "the same plan always renders in the same order, in the app and in the PDF" is a structural guarantee, not a maintained-by-hand coincidence between two files.
- Update `frontend/src/types/carePlan.ts` to match 01's backend contract exactly: remove `additional_info`, `CarePlan.urgency` (already absent — confirm and guard against reintroduction), `Diagnosis.main_conclusion`; fold `Medication.change`/`change_description`; add required `status` to the five actionable-item types; make `WarningSign.urgency` nullable; add `summary_fact_ids` (unused by any renderer, present for type fidelity only).
- Make every `WarningSign.urgency` consumer (sort, color, badge label) null-safe, with null rendering grey, sorting last, and never being dropped from the list.
- Delete the "Data Sources" card and `diagnosis.main_conclusion` rendering from both `CarePlanView.tsx` and `buildPdfHtml.ts`.
- Activate the PDF's dormant `includeGlossary`/`includeReadability`/`includeLowPriority` sections by flipping all three flags to `true` at the `downloadReport.ts` call site, so the downloaded report carries the same eight `CarePlan` sections the app shows plus the readability breakdown as supplementary detail (§4.7). The flags themselves stay in place as parameters — only the values passed change.
- Widen the result screen, not the PDF: delete `ResultScreen.tsx`'s `hideLowPriority` prop pass-through and the now-unconsumed `hideLowPriority` prop on `CarePlanView` itself, so the "Other Items From Your Visit" card renders on screen under the same `result.low_priority?.length > 0` guard every other card already uses (§4.8). The result screen and the PDF end up showing the identical eight sections.
- Give done-state Next Steps rows a strikethrough in addition to their existing color change, in both `CarePlanView.tsx` and `buildPdfHtml.ts`, so the distinction survives black-and-white printing (§4.4, §4.5).
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
                  <strong style={isDone ? { color: 'var(--text-secondary)', textDecoration: 'line-through' } : undefined}>
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

**Done-state rows also get a strikethrough, not just a color change.** Color alone is not a reliable done/to-do signal: not every viewer perceives the `var(--text-secondary)` vs. default-text difference, and the whole point of this card is that it survives print — the report is routinely printed in black and white, where a color-only distinction disappears entirely. `textDecoration: 'line-through'` is added to the same conditional style object on the title `<strong>` above, alongside the existing color change, so both signals travel together and neither depends on the other. This resolves the `[OPEN]` item in §9 that left this un-adopted.

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
    const isDone = row.status === 'done';
    const box = isDone ? '&#9745;' : '&#9744;'; // ☑ / ☐ numeric HTML entities
    const color = isDone ? '#059669' : '#9CA3AF';
    // Strikethrough travels with the color change, not instead of it (§4.4's
    // resolved decision) -- it's the signal that survives black-and-white
    // printing, which is the whole reason this row exists as a print target.
    const titleStyle = isDone ? 'text-decoration:line-through;' : '';
    const stepsHtml = row.steps?.length
      ? `<ul style="margin:4px 0 0 20px;">${row.steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>` : '';
    return `<div style="padding:8px 12px;margin-bottom:6px;background:#F9FAFB;border-radius:6px;">
      <span style="color:${color};">${box}</span> <strong style="${titleStyle}">${escapeHtml(row.title)}</strong>
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
- **Keep the readability breakdown block, the `grading` parameter, and the `BuildPdfHtmlOptions` interface exactly as they are today — none of the three is deleted.** This reverses what an earlier pass of this PRD proposed: the decided scope (§1, §2) is that the downloaded report mirrors the app's eight `CarePlan` sections plus the readability breakdown as supplementary detail, not a further-trimmed subset of it. `buildPdfHtml.ts:137-150` (the `if (includeReadability && grading?.enabled ...)` branch and its `methodMap` grouping) needs no code change at all — it has been correct and independently testable since it was written; it has simply never executed in production because every caller passed `false`. The only change of substance is at the call site (§4.7), not in this file's logic.
- **Section order changes to match `CarePlanView.tsx`'s eight-card order.** Today's `buildPdfHtml.ts` pushes Glossary (`:130-135`) before Readability (`:137-150`) before Other Items/low-priority (`:152-155`) — an order that predates the eight-card collapse and never had to match the app, since two of the three were unreachable. Once all three render for real, move the low-priority block to before the glossary block, so the shared eight sections appear in exactly the order the table in §4.4 defines (`...` → Other Items From Your Visit (7) → Medical Terms Glossary (8)), and keep Readability appended last, after Glossary — it isn't one of the eight `CarePlan` sections and has no on-screen equivalent beyond the single combined score `ResultScreen.tsx` shows (§4.7), so it reads as a print-only appendix rather than a ninth card competing with the eight for a position in that order.

**Knock-on consequences of widening the PDF, now that all three sections render:**

- **Page count.** A jargon-dense or fully-graded note now produces a materially longer printed report than the narrower one every real user has seen to date — a glossary card, a low-priority list, and a seven-row readability table are all new print real estate, typically adding one page or a partial page. No new pagination mechanism is introduced: `buildPdfHtml.ts` has no `page-break-*` CSS today and this PRD adds none; the existing `@media print { body { margin:0; padding:16px } }` block (`buildPdfHtml.ts` bottom) is untouched, so the added content flows through the same default browser print pagination every other section already relies on. Not a new class of risk, just more of an existing one.
- **Missing/empty glossary in print.** `buildPdfHtml.ts:130`'s existing guard — `includeGlossary && result.terms && Object.keys(result.terms).length > 0` — is unchanged. A note with no glossary terms (or `terms` absent) prints no "Medical Terms Glossary" heading at all, exactly like today's on-screen behavior (`CarePlanView.tsx`'s equivalent guard) and exactly like today's PDF behavior for every section gated on `result.X?.length` — there is no dangling empty section header to worry about; the guard that already existed is sufficient once the flag flips to `true`.
- **Screen/PDF parity for "Other Items," not asymmetry.** `ResultScreen.tsx:122` today renders `<CarePlanView result={care_plan} hideLowPriority />`, suppressing the low-priority card on the always-visible result screen. Flipping `includeLowPriority` to `true` here without also touching `ResultScreen.tsx` would make the downloaded report show a section the app itself hides from the one place a real patient actually looks. §4.8 removes that gap at the source — `hideLowPriority` is deleted, not carried forward as a documented exception — so by the time this section's flag flips to `true`, the app already shows the same card the PDF is about to. There is nothing left to reconcile here: this section's job is only to confirm the guard (`result.low_priority?.length`, `buildPdfHtml.ts:152`'s existing check) is the same shape as the app's post-§4.8 guard (`result.low_priority?.length > 0`), which it already is.

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

### 4.7 `frontend/src/utils/downloadReport.ts` — flip the three flags, signature unchanged

**Before this PRD:**
```typescript
export function downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void {
  trackEvent({ name: 'report_downloaded', params: {} });
  const html = buildPdfHtml(carePlan, grading, {
    includeGlossary: false, includeReadability: false, includeLowPriority: false,
  });
  ...
}
```

**After this PRD:**
```typescript
export function downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void {
  trackEvent({ name: 'report_downloaded', params: {} });
  const html = buildPdfHtml(carePlan, grading, {
    includeGlossary: true, includeReadability: true, includeLowPriority: true,
  });
  ...
}
```

The signature is **unchanged** — `carePlan` and `grading` are both still required, since `grading` remains the readability block's only input (§4.5, kept, not deleted). `BuildPdfHtmlOptions` in `buildPdfHtml.ts` is likewise unchanged: it already defaults all three flags to `true` when omitted (`options?.includeGlossary ?? true`, `buildPdfHtml.ts:19-21`), so this call site's only job was ever to override those defaults down to `false`. The flags stay in place as parameters — they remain a real knob a future caller could still use to trim the report — and only the three literal values passed here change, from `false` to `true`. Passing them explicitly (rather than dropping the options argument and relying on the defaults) is deliberate: a reader of `downloadReport.ts` should see the three-section decision spelled out at the one call site that makes it, not have to go infer it from `buildPdfHtml.ts`'s defaults in a different file.

**Why this is a real behavior change, not just cleanup.** Today's call site opts *out* of the glossary, readability, and low-priority sections in the actual downloaded PDF (all three flags `false`). This sub-project's decided scope is that the PDF report mirrors the app: the same eight `CarePlan` sections `CarePlanView.tsx` renders, plus the readability breakdown as supplementary detail for the patient's own downloaded record — not a further-trimmed subset, and, for the readability breakdown specifically, not limited to the single combined figure `ResultScreen.tsx` shows on screen (`ResultScreen.tsx:98,100-102,112-114`, untouched) either. This is a direct instruction for this sub-project; §4.5's third knock-on bullet and §4.8 cover the one section (low-priority items) that needed a companion change on the app side so the PDF isn't showing the patient something the result screen hides.

`ResultScreen.tsx:122`'s call site (`downloadReport(care_plan, grading)`) needs **no change** — it already passes both arguments in the signature this PRD keeps.

### 4.8 `frontend/src/components/ResultScreen.tsx` / `CarePlanView.tsx` — delete `hideLowPriority`

**Verified against the real code: `ResultScreen.tsx:122` is `hideLowPriority`'s only consumer.** Grepped the whole frontend for the identifier — three hits total: the prop's declaration and default (`CarePlanView.tsx:94,97`), its one read site (`CarePlanView.tsx:327`, `{!hideLowPriority && result.low_priority?.length > 0 && (...)}`), and its one call site (`ResultScreen.tsx:122`). No other screen, test helper, or story passes it. A prop with exactly one caller and no product reason for that caller to differ from the default is not a real extensibility point — it's the one place the "screen-concise / PDF-complete" split from an earlier pass of this PRD was implemented, and that split is rejected (§1, §9). **Decision: delete the prop entirely, from the interface and its one call site — not just stop passing it.** Consistent with the parent brief's repeated preference for deleting a code path with no remaining consumer over keeping it "just in case" (02 §9's disposition of the old `extract_text_from_pdf`, applied here at the component-prop level rather than the function level).

**`ResultScreen.tsx:122`, before:**
```tsx
<CarePlanView result={care_plan} hideLowPriority />
```

**After:**
```tsx
<CarePlanView result={care_plan} />
```

**`CarePlanView.tsx:92-98`, before:**
```tsx
export default function CarePlanView({
  result,
  hideLowPriority = false,
}: {
  result: SimplifiedCarePlan;
  hideLowPriority?: boolean;
}) {
```

**After:**
```tsx
export default function CarePlanView({
  result,
}: {
  result: SimplifiedCarePlan;
}) {
```

**`CarePlanView.tsx:327`, before:**
```tsx
{!hideLowPriority && result.low_priority?.length > 0 && (
```

**After:**
```tsx
{result.low_priority?.length > 0 && (
```

This is now the same guard shape as every other optional card in the file (`result.follow_up?.length > 0`, `result.questions?.length > 0`, `Object.keys(terms).length > 0`) — "Other Items From Your Visit" stops being the one card an unrelated boolean prop can suppress out from under its own data.

**Knock-on consequences of widening the result screen, checked against the real code:**

- **Section order is unaffected.** The low-priority card's position — 7th of eight, between Questions and Medical Terms Glossary — was never controlled by `hideLowPriority`; that prop only gated whether the card rendered at all, not where. §4.4's eight-card order and §4.5's mirrored PDF order (`... → Other Items From Your Visit (7) → Medical Terms Glossary (8)`) already agree with each other and need no further change now that the screen actually reaches that branch.
- **Screen length.** For any result whose `low_priority` is non-empty, the result screen gains one more card than it renders today. This is the smallest possible version of that cost: the card is `collapsible defaultOpen={false}` (`CarePlanView.tsx:327`, unchanged by this PRD), so it adds one collapsed header — not an expanded list — to the page's scroll length, identical to how "Medical Terms Glossary" already behaves today for a result with `terms`.
- **Empty-state behavior is unaffected.** `result.low_priority?.length > 0` is `false` for an empty or absent array — the card renders nothing at all in that case, on screen exactly as in the PDF (§4.5's knock-on bullet). There is no dangling header or "no other items" placeholder to add; the guard that already existed on `CarePlanView`'s side is sufficient once the caller-side override is gone.

## 5. API Change Summary

**N/A — this PRD makes no API calls and defines no request/response shapes.** It consumes 01's already-settled `CarePlanContent` HTTP response shape (01 §5/§6) as a fixed input and 04's render-time content contract (04 §6: the literal string `"Not stated in your note."` may appear in any `why` field; `questions` may be `[]`; `warning_signs[].urgency` may be `null`). No backend route, status code, or error shape is referenced or changed by anything in this PRD.

## 6. Frontend Change Summary

Every file this PRD touches, and the shape of the change:

| File | Change |
|---|---|
| `frontend/src/types/carePlan.ts` | Full rewrite per §4.1 — deletions, the `status` addition, the `change` fold, nullable `urgency`. |
| `frontend/src/types/envelope.ts` | **No change** — `SimplifiedCarePlan = CarePlanContent` is a type alias; verified by reading, not assumed. |
| `frontend/src/utils/nextSteps.ts` | **New file** — `buildNextStepsRows`, `NEXT_STEPS_TYPE_ORDER`, `NEXT_STEPS_TYPE_LABELS`, `NextStepRow`/`NextStepType` (§4.3). |
| `frontend/src/components/CarePlanView.tsx` | Eight-card reorder; Data Sources deleted; `main_conclusion` rendering deleted; Next Steps card added (calls `buildNextStepsRows`), done-state rows get strikethrough + color; null-safe warning-sign urgency; `change`/`change_description` fold (§4.4); `hideLowPriority` prop deleted from the component's interface, "Other Items From Your Visit" guard changes to match every other card's `result.X?.length > 0` shape (§4.8). |
| `frontend/src/utils/buildPdfHtml.ts` | Mirrors `CarePlanView.tsx`'s Next Steps/null-urgency/strikethrough changes; readability breakdown, `grading` parameter, and `BuildPdfHtmlOptions` all **kept, unchanged**; low-priority section moves ahead of the glossary section to match the app's eight-card order, Readability stays appended last (§4.5). |
| `frontend/src/App.css` | Two new rule blocks, `.next-step-checkbox`/`.next-step-type-label` (§4.6). No existing rule removed or renamed. |
| `frontend/src/utils/downloadReport.ts` | Signature **unchanged**; the three `BuildPdfHtmlOptions` values passed to `buildPdfHtml` flip from `false` to `true` (§4.7). |
| `frontend/src/components/ResultScreen.tsx` | `downloadReport(care_plan, grading)` (`ResultScreen.tsx:124`) already matches the unchanged two-argument signature (§4.7) — no change there. The before/after score widget (`ResultScreen.tsx:112-114`) already shows a single combined figure and is otherwise untouched. One real change: `hideLowPriority` is deleted from the `<CarePlanView>` call site at line 122 (§4.8). |
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
| `frontend/src/tests/components/ResultScreen.test.tsx` | Three inline fixtures carry a stray `urgency: 'normal'` key (lines 26, 68, 119) — harmless, since these literals target `JobDoc.output_data: Record<string, unknown> \| null`, so TS excess-property checking never fires. Uses `realCarePlanOutput.fixture.json` for its realistic-payload test. **The test at `:61-77`, `'does not render "Other Items From Your Visit" even when low_priority has entries'`, breaks on content**: it asserts the old `hideLowPriority`-suppressed behavior this PRD deletes (§4.8). | Recommended cleanup: delete the three stray `urgency` keys. Invert the `:61-77` test rather than deleting it — same fixture (`low_priority: ['Drink more water']`), same render, opposite assertions: `expect(screen.getByText('Other Items From Your Visit')).toBeInTheDocument()` and `expect(screen.getByText('Drink more water')).toBeInTheDocument()`. Rename it to say what it now pins, e.g. `'renders "Other Items From Your Visit" when low_priority has entries'` — the old name and the old body both described a since-rejected intentional suppression, and a future reader who sees only a deleted assertion (with no replacement) could assume the card's disappearance was an accident to fix rather than a deliberate, already-decided widening; the inverted test is what should stop them from "restoring" `hideLowPriority`. The realistic-payload test's own assertions (`/Lisinopril/`, `.medical-term` count) are unaffected by this PRD; it only needs §7.1's fixture regeneration to land for content fidelity. |
| `frontend/src/tests/pages/HomePage.test.tsx` | Same fixture dependency; its own inline `completedDoc` (lines 47-57) has no deleted fields — already minimal. | No change beyond §7.1's fixture regeneration. |
| `frontend/src/tests/utils/downloadReport.test.ts` | Signature is unchanged, so all five `downloadReport(fixture, grading)` call sites (`:33,47,57,64,72`) keep compiling untouched. **The test at `:68-80` breaks on content**, though: `'omits the Medical Terms Glossary, Readability, and Other Items sections from the downloaded report'` asserts the *old* narrower PDF behavior (glossary/readability/Other Items all absent) that this PRD inverts (§4.7). | Rewrite that one test's name and body only: replace it with its inverse — assert `html.toContain('Medical Terms Glossary')`, `html.toContain('Readability')`, and `html.toContain('Other Items')`, using the fixture's existing `terms`/`low_priority`/`grading` data (no new fixture fields needed — `:9-22`'s fixture already carries a glossary term, a low-priority item, and enabled grading entries). No other change to this file. |
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
  - `renders a strikethrough on a done row's title but not on a to_do row's title` — same two-status fixture; assert the done title's computed/inline style includes `line-through` and the to_do title's does not — regression guard for the resolved `[OPEN]` item in §9 (color change alone is not sufficient, particularly for black-and-white print).
  - `renders a null-urgency warning sign last, in grey, with no urgency badge` — three warning signs, one `null`, fed in an order where `null` is first; assert it renders last and that no bracketed label text appears next to its symptom (regression guard against the resolved "no invented label" decision in §4.4).
  - `never drops a null-urgency warning sign from the list` — same fixture; assert the count of rendered warning-sign blocks equals the input length.
- **`frontend/src/tests/utils/buildPdfHtml.test.ts`** (new file — none exists today, a real gap independent of this PRD's changes):
  - `includes a Next Steps section with a checkbox glyph per item, matching the app's type precedence order`.
  - `includes the Medical Terms Glossary, Readability, and Other Items sections when their flags default to true and their data is present` — direct-unit-tests the three branches (`includeGlossary`/`includeReadability`/`includeLowPriority`) that were unreachable through `downloadReport` before this PRD (§1); this is the "direct unit test of `buildPdfHtml`" the Problem section notes never existed.
  - `orders the Other Items section before the Medical Terms Glossary section, with Readability last` — a fixture populating `low_priority`, `terms`, and `grading` together; assert `html.indexOf('Other Items') < html.indexOf('Medical Terms Glossary') < html.indexOf('Readability')`, guarding the reordering in §4.5.
  - `omits a section when its flag is explicitly false`, e.g. `includeGlossary: false` — confirms the flags still function as real knobs, not vestigial parameters, now that their default call site no longer exercises the `false` branch.
  - `renders no Medical Terms Glossary heading at all when terms is empty` — guards the existing `Object.keys(result.terms).length > 0` guard (§4.5's knock-on bullet) now that the flag defaults to reaching this code.
  - `renders a strikethrough style on a done Next Steps row's title in the generated HTML, and none on a to_do row's` — string-search or DOM-parse the output for `text-decoration:line-through` scoped to the correct row; same regression concern as the mirrored `CarePlanView.test.tsx` case, applied to the PDF's HTML string output.
  - `omits the Next Steps section entirely when all five source arrays are empty` (mirrors the existing `result.X?.length` guard pattern already used for every other section).

## 8. Manual Intervention Required From You

- **Visual QA of the Next Steps checkbox glyphs** (ngrok + pm2, `SERVICE_MODE=combined`): confirm `☑`/`☐` render as recognizable glyphs, not tofu boxes, in your actual browsers/OSes — Unicode box-drawing support varies by system font, and the app's `Inter` font stack may not cover them. If they render poorly, fall back to an inline SVG.
- **Print-preview QA of the same glyphs** — the brief calls the checkbox affordance out as "explicitly requested for print," and print-engine glyph rendering can differ from on-screen rendering across browsers. Print a sample report and confirm both states are visually distinct.
- **Black-and-white print QA of the done-state strikethrough** — print (or print-preview in grayscale) a sample report with a mix of done/to-do Next Steps rows and confirm the strikethrough is legible without color: this is the entire reason strikethrough was adopted over color alone (§4.4, §9), and no automated test can substitute for looking at actual printer output.
- **Confirm the `follow_up`-before-`other` type precedence (§4.3) reads correctly** against real care plans once 06's pipeline wiring produces real output — this PRD's order is a reasoned default, not validated against real patient-facing content.
- **Spot-check the regenerated `realCarePlanOutput.fixture.json`** (§7.1) for narrative coherence — a mechanical field-by-field edit risks internally inconsistent content only a human read would catch.
- **Capture a real mixed-urgency warning-sign fixture from the first end-to-end pipeline run** (post-06, ngrok + pm2, `SERVICE_MODE=combined`): once a real note produces a `CarePlan` whose `warning_signs` mix a null urgency alongside non-null ones in the same list, save it as a fixture and add a coverage case exercising the null-urgency sort/render path against that realistic narrative — supplementing, not replacing, the synthetic unit tests in §7.3. Not automatable before 06 wires a real pipeline run; consistent with PRD 04 §8's identical reasoning for its own real-note smoke tests.

## 9. Open Questions & Decisions

- `[RESOLVED: Next Steps type precedence is medication (1), test (2), procedure (3), follow_up (4), other (5).]` — the brief requires "a fixed type precedence" but does not specify its order; this PRD's choice keeps the pre-merge card order for the first three types and moves `follow_up` ahead of `other` on the reasoning that a scheduled appointment is a harder commitment than a loosely-defined instruction (§4.3).
- `[RESOLVED: a null-urgency warning sign renders no bracketed badge text at all — only the grey left border and last-sorted position signal reduced information, never an invented label like "NOT STATED" or "UNKNOWN".]` — consistent with the brief's core "don't invent from silence" principle, applied at the UI-label layer rather than only the schema-default layer (§4.4).
- `[RESOLVED: the Next Steps checkbox is a static, read-only rendering (aria-hidden glyph + sr-only text prefix), not an interactive role="checkbox" control.]` — there is no persistence layer to write a toggle back to; the job document is deleted the instant `ResultScreen` mounts (brief non-goals), so an editable checkbox would misrepresent what the UI can actually do (§4.4).
- `[RESOLVED: buildPdfHtml.ts/downloadReport.ts keep their include/exclude options — BuildPdfHtmlOptions, its three flags, and the grading parameter are all unchanged — and downloadReport.ts's call site flips all three flag values from false to true, activating rather than deleting the glossary, readability, and low-priority sections.]` — a direct decision for this sub-project: the report mirrors the app's eight sections plus the readability breakdown as supplementary detail, not a further-trimmed subset, and the flags remain real knobs rather than being deleted outright. Flagged prominently — a real behavior change to a user's download, not a pure refactor (§4.5, §4.7).
- `[RESOLVED: the result screen and the PDF show the same eight sections — hideLowPriority is deleted outright, not kept as a documented screen/PDF asymmetry.]` — An earlier pass of this PRD found that activating `includeLowPriority` in the PDF (§4.7) would make the download show a section (`ResultScreen.tsx:122`'s `hideLowPriority` prop) the app itself hides on screen, and recorded that gap as a deliberate "screen stays concise, PDF is the fuller record" split. That framing is rejected: the sections in a `CarePlan` are worth showing to the patient, full stop, and the download is not an acceptable place to relegate the only one they'll actually see — most patients never open the PDF at all, so "the PDF has it" is not equivalent to "the patient sees it." §4.8 deletes `hideLowPriority` from both its one call site (`ResultScreen.tsx:122`) and `CarePlanView`'s interface, grep-confirmed to have no other consumer, rather than keeping a single-caller prop around to preserve behavior nobody has asked to preserve — consistent with 02 §9's disposition of `extract_text_from_pdf` (delete a code path with no remaining reason to exist, don't keep it as a "just in case"). **Rejected alternative: narrow the PDF back down instead** — pass `includeLowPriority: false` at the `downloadReport.ts` call site (§4.7) rather than touching `ResultScreen.tsx`, restoring the pre-PRD status quo everywhere. Rejected for the same reason: the owner's explicit instruction is that the app widens to match the PDF, not the reverse, and — since none of this is in production — there is no existing on-screen behavior worth preserving for its own sake here (`ResultScreen.test.tsx:61`'s prior assertion pinned a choice, not a load-bearing production behavior). The test itself is inverted, not deleted, in §7.2, so the new intended behavior is what future readers find pinned in its place.
- `[RESOLVED: Test, Procedure, OtherInstruction, FollowUp are promoted from inline anonymous types to named interfaces in carePlan.ts.]` — mechanical: `nextSteps.ts` needs to reference each type by name (§4.1).
- `[RESOLVED: glossary key capitalization for card-heading display is left as-is.]` — `[DEFERRED]` per 07 §6's own framing; the higher-traffic inline-highlight surface is unaffected either way (§4.2).
- `[RESOLVED: summary_fact_ids is added to the TypeScript type for contract fidelity but read by no component.]` — matches 01 §6's own framing that 08 may ignore it (§4.1).
- `[RESOLVED: the regenerated fixture sets status: "to_do" on all five actionable items.]` — nothing in the fixture's existing narrative describes a completed action (§7.1).
- `[RESOLVED: done-state rows get a strikethrough in addition to the existing color change, in both CarePlanView.tsx and buildPdfHtml.ts.]` — adopted because color alone is not a reliable done/to-do signal: not every viewer perceives the color difference, and the report is routinely printed in black and white, where a color-only distinction disappears entirely. Strikethrough is a shape-based signal that survives grayscale print, which is the whole point of a printable report (§4.4, §4.5); tested in §7.3.
- `[RESOLVED: the existing §7.3 synthetic test covers the null-urgency sort/render mechanism and is sufficient to build against; capturing a realistic mixed-urgency fixture from an actual clinical narrative requires a real end-to-end pipeline run, which cannot exist until 06 wires ground()/assemble_and_render() into iter_steps.]` — mirrors PRD 04 §8's identical disposition for its own can't-validate-without-a-real-run caveats. Moved to a concrete post-06 action in §8 rather than left open, so the gap is tracked instead of forgotten.
- **Forward pointer, not this PRD's own finding:** PRD 18 (diagnosis-soundness, written later in the same branch) discovered that `frontend/src/types/carePlan.ts`'s `CarePlanContent.summary_fact_ids: number[]` is declared required even though `_strip_internal_provenance` always strips the key server-side, so the type asserts a shape that is never true at runtime — see line 601 above, where this PRD originally added the field "for contract fidelity." PRD 18 §6/§9 assigns the cleanup here, to whichever future task touches `carePlan.ts`: delete `summary_fact_ids` from the `CarePlanContent` interface, matching how the six item-level `source_fact_ids` fields are already correctly omitted. Not actioned by this PRD; recorded here so a future `dev-tasks` run on this file doesn't miss it.
