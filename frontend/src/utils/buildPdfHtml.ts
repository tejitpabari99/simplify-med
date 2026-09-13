import type { SimplifiedCarePlan, Grading } from '../types/envelope';
import { buildNextStepsRows, NEXT_STEPS_TYPE_LABELS } from './nextSteps';

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export interface BuildPdfHtmlOptions {
  includeGlossary?: boolean;
  includeReadability?: boolean;
  includeLowPriority?: boolean;
}

export function buildPdfHtml(result: SimplifiedCarePlan, grading?: Grading, options?: BuildPdfHtmlOptions): string {
  const includeGlossary = options?.includeGlossary ?? true;
  const includeReadability = options?.includeReadability ?? true;
  const includeLowPriority = options?.includeLowPriority ?? true;
  const sections: string[] = [];
  const h2 = (title: string) =>
    `<h2 style="font-size:16px;font-weight:600;color:#1a1a2e;margin:20px 0 10px;padding-bottom:6px;border-bottom:2px solid #E5E7EB;">${escapeHtml(title)}</h2>`;

  if (result.summary) {
    sections.push(`${h2('What You Need to Know')}<p style="color:#374151;line-height:1.6;margin:0;">${escapeHtml(result.summary)}</p>`);
  }

  if (result.reason_for_visit?.length) {
    const items = result.reason_for_visit.map(r =>
      `<p style="color:#374151;margin:0 0 8px 0;"><strong>${escapeHtml(r.reason)}</strong>${r.description ? `: ${escapeHtml(r.description)}` : ''}</p>`,
    ).join('');
    sections.push(`${h2('Why You Came In')}${items}`);
  }

  if (result.diagnosis && result.diagnosis.details?.length) {
    let diagnosis = '';
    if (result.diagnosis.changed_since_last_visit) {
      diagnosis += `<p style="color:#0F766E;margin:0 0 8px 0;">Compared to last visit: ${escapeHtml(result.diagnosis.changed_since_last_visit)}</p>`;
    }
    diagnosis += (result.diagnosis.details ?? []).map(det =>
      `<div style="padding:8px 12px;margin-bottom:6px;background:#F0FDF4;border-radius:6px;">
        <strong>${escapeHtml(det.plain_name ? `${det.plain_name} (${det.title})` : det.title)}</strong>
        ${det.description ? `<br><span style="color:#6B7280;font-size:13px;">${escapeHtml(det.description)}</span>` : ''}
        ${det.what_it_means_for_you ? `<br><span style="color:#B45309;font-size:13px;">What this means for you: ${escapeHtml(det.what_it_means_for_you)}</span>` : ''}
      </div>`,
    ).join('');
    sections.push(`${h2('What the Doctor Found')}${diagnosis}`);
  }

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
        ${row.change ? `<br><span style="color:#D97706;font-size:13px;font-weight:700;">Changed: ${escapeHtml(row.change)}</span>` : ''}
        ${stepsHtml}
      </div>`;
    }).join('');
    sections.push(`${h2('Next Steps')}${items}`);
  }

  if (result.warning_signs?.length) {
    const items = [...result.warning_signs]
      .sort((a, b) => {
        const order: Record<string, number> = { emergency: 0, call_doctor: 1, monitor: 2, normal_side_effect: 3 };
        return (a.urgency ? order[a.urgency] : 4) - (b.urgency ? order[b.urgency] : 4);
      })
      .map(w =>
        `<div style="padding:8px 12px;margin-bottom:6px;background:#FFF7ED;border-radius:6px;">
          <strong>${escapeHtml(w.symptom)}</strong> ${w.urgency ? `[${escapeHtml(w.urgency)}]` : ''}
          ${w.what_it_might_mean ? `<br><span style="color:#6B7280;font-size:13px;">${escapeHtml(w.what_it_might_mean)}</span>` : ''}
          <br><span style="font-size:13px;">${escapeHtml(w.what_to_do)}</span>
        </div>`,
      ).join('');
    sections.push(`${h2('What to Watch For')}${items}`);
  }

  if (result.questions?.length) {
    const items = result.questions.map(q => `<li>${escapeHtml(q)}</li>`).join('');
    sections.push(`${h2('Questions to Ask')}<ul style="margin:0;padding-left:20px;color:#0369A1;">${items}</ul>`);
  }

  if (includeLowPriority && result.low_priority?.length) {
    const items = result.low_priority.map(item => `<li>${escapeHtml(item)}</li>`).join('');
    sections.push(`${h2('Other Items')}<ul style="margin:0;padding-left:20px;color:#6B7280;">${items}</ul>`);
  }

  if (includeGlossary && result.terms && Object.keys(result.terms).length > 0) {
    const items = Object.entries(result.terms).map(([term, glossary]) =>
      `<div style="margin-bottom:6px;"><strong>${escapeHtml(term)}:</strong> <span style="color:#6B7280;">${escapeHtml(glossary.definition)}</span></div>`,
    ).join('');
    sections.push(`${h2('Medical Terms Glossary')}${items}`);
  }

  if (includeReadability && grading?.enabled && grading.entries?.length) {
    // Group entries by name: collect before and after entries
    const methodMap: Record<string, { before?: string; after?: string }> = {};
    for (const entry of grading.entries) {
      if (!methodMap[entry.name]) methodMap[entry.name] = {};
      if (entry.target === 'before') methodMap[entry.name].before = String(entry.grade);
      else if (entry.target === 'after') methodMap[entry.name].after = String(entry.grade);
    }
    const items = Object.entries(methodMap).map(([name, { before, after }]) => {
      const score = before && after ? `${escapeHtml(before)} → ${escapeHtml(after)}` : escapeHtml(before ?? after ?? '');
      return `<div style="margin-bottom:6px;"><strong>${escapeHtml(name)}:</strong> <span style="color:#374151;">${score}</span></div>`;
    }).join('');
    sections.push(`${h2('Readability')}${items}`);
  }

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>
@media print {
  body { margin: 0; padding: 16px; }
  .no-print { display: none !important; }
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: #1a1a2e; margin: 0 auto; padding: 40px 32px;
  max-width: 800px; background: #fff; font-size: 14px; line-height: 1.6;
}
h2 { font-size: 15px; font-weight: 600; color: #1a1a2e; margin: 20px 0 10px;
  padding-bottom: 6px; border-bottom: 2px solid #E5E7EB; }
p { margin: 0 0 6px 0; }
ul { margin: 4px 0 8px 20px; padding: 0; }
li { margin-bottom: 4px; }
.header { border-bottom: 3px solid #4F46E5; padding-bottom: 16px; margin-bottom: 24px; }
.header h1 { font-size: 20px; font-weight: 700; color: #4F46E5; margin: 0 0 4px; }
.header p { color: #6B7280; font-size: 12px; margin: 0; }
.footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid #E5E7EB;
  text-align: center; color: #9CA3AF; font-size: 11px; }
.print-btn { display: inline-block; padding: 8px 20px; background: #4F46E5; color: #fff;
  border: none; border-radius: 6px; font-size: 13px; cursor: pointer;
  margin-bottom: 16px; font-family: sans-serif; }
</style></head><body>
<div class="no-print">
  <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="header">
  <h1>Your Care Plan</h1>
  <p>Generated by Simplify · Data processed securely</p>
</div>
${sections.join('')}
<div class="footer">Generated by Simplify — Care plan created for patient understanding</div>
</body></html>`;
}
