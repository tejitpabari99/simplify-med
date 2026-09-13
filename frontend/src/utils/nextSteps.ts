import type {
  CarePlanContent, ItemStatus,
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
  change?: string | null;  // Medication only; null/undefined for every other row type
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
      change: m.change,
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
