import { describe, it, expect } from 'vitest';
import { buildPdfHtml } from '../../utils/buildPdfHtml';
import type { SimplifiedCarePlan, Grading } from '../../types/envelope';

function baseCarePlan(overrides: Partial<SimplifiedCarePlan> = {}): SimplifiedCarePlan {
  return {
    summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
    medications: [], tests: [], procedures: [], other: [], follow_up: [],
    warning_signs: [], questions: [], low_priority: [],
    ...overrides,
  };
}

const enabledGrading: Grading = {
  enabled: true,
  graded_at: null,
  entries: [
    { name: 'combined', target: 'before', grade: 42, grade_breakdown: null, reasoning: null },
    { name: 'combined', target: 'after', grade: 78, grade_breakdown: null, reasoning: null },
  ],
};

describe('buildPdfHtml', () => {
  it('includes a Next Steps section with a checkbox glyph per item, matching the app\'s type precedence order', () => {
    const carePlan = baseCarePlan({
      other: [{ title: 'Other item', status: 'to_do' }],
      follow_up: [{ time_frame: '1 week', description: 'Follow-up item', status: 'to_do' }],
      procedures: [{ title: 'Procedure item', status: 'to_do' }],
      tests: [{ title: 'Test item', description: 'desc', status: 'to_do' }],
      medications: [{ title: 'Medication item', change: '', status: 'to_do' }],
    });
    const html = buildPdfHtml(carePlan);
    expect(html).toContain('Next Steps');
    expect((html.match(/&#9744;|&#9745;/g) ?? [])).toHaveLength(5);
    const order = ['Medication item', 'Test item', 'Procedure item', 'Follow-up item', 'Other item'];
    const indices = order.map(title => html.indexOf(title));
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThan(indices[i - 1]);
    }
  });

  it('includes the Medical Terms Glossary, Readability, and Other Items sections when their flags default to true and their data is present', () => {
    const carePlan = baseCarePlan({
      low_priority: ['Drink more water'],
      terms: { hypertension: { definition: 'High blood pressure', source: 'preserved', imgUrl: null, altText: null } },
    });
    const html = buildPdfHtml(carePlan, enabledGrading);
    expect(html).toContain('Medical Terms Glossary');
    expect(html).toContain('Readability');
    expect(html).toContain('Other Items');
  });

  it('orders the Other Items section before the Medical Terms Glossary section, with Readability last', () => {
    const carePlan = baseCarePlan({
      low_priority: ['Drink more water'],
      terms: { hypertension: { definition: 'High blood pressure', source: 'preserved', imgUrl: null, altText: null } },
    });
    const html = buildPdfHtml(carePlan, enabledGrading);
    expect(html.indexOf('Other Items')).toBeLessThan(html.indexOf('Medical Terms Glossary'));
    expect(html.indexOf('Medical Terms Glossary')).toBeLessThan(html.indexOf('Readability'));
  });

  it('omits a section when its flag is explicitly false', () => {
    const carePlan = baseCarePlan({
      terms: { hypertension: { definition: 'High blood pressure', source: 'preserved', imgUrl: null, altText: null } },
    });
    const html = buildPdfHtml(carePlan, undefined, { includeGlossary: false });
    expect(html).not.toContain('Medical Terms Glossary');
  });

  it('renders no Medical Terms Glossary heading at all when terms is empty', () => {
    const carePlan = baseCarePlan({ terms: {} });
    const html = buildPdfHtml(carePlan);
    expect(html).not.toContain('Medical Terms Glossary');
  });

  it('renders a strikethrough style on a done Next Steps row\'s title in the generated HTML, and none on a to_do row\'s', () => {
    const carePlan = baseCarePlan({
      medications: [
        { title: 'Done Med', change: '', status: 'done' },
        { title: 'Todo Med', change: '', status: 'to_do' },
      ],
    });
    const html = buildPdfHtml(carePlan);
    const doneIdx = html.indexOf('Done Med');
    const doneStrongOpen = html.lastIndexOf('<strong', doneIdx);
    const doneStrongTag = html.slice(doneStrongOpen, doneIdx);
    expect(doneStrongTag).toContain('text-decoration:line-through');

    const todoIdx = html.indexOf('Todo Med');
    const todoStrongOpen = html.lastIndexOf('<strong', todoIdx);
    const todoStrongTag = html.slice(todoStrongOpen, todoIdx);
    expect(todoStrongTag).not.toContain('text-decoration:line-through');
  });

  it('omits the Next Steps section entirely when all five source arrays are empty', () => {
    const carePlan = baseCarePlan();
    const html = buildPdfHtml(carePlan);
    expect(html).not.toContain('Next Steps');
  });

  it('renders a medication\'s change note in the Next Steps section, HTML-escaped', () => {
    const carePlan = baseCarePlan({
      medications: [{ title: 'Lisinopril', change: 'Dose <increased> & "adjusted"', status: 'to_do' }],
    });
    const html = buildPdfHtml(carePlan);
    expect(html).toContain('Changed: Dose &lt;increased&gt; &amp; &quot;adjusted&quot;');
    expect(html).not.toContain('Dose <increased>');
  });

  it('omits the change line when Medication.change is empty', () => {
    const carePlan = baseCarePlan({
      medications: [{ title: 'Lisinopril', change: '', status: 'to_do' }],
    });
    const html = buildPdfHtml(carePlan);
    expect(html).not.toContain('Changed:');
  });

  it('includes the couldn\'t-confirm fallback when reason_for_visit is present but diagnosis.details is empty', () => {
    const carePlan = baseCarePlan({
      reason_for_visit: [{ reason: 'High blood pressure', description: 'Readings were high.' }],
      diagnosis: { details: [] },
    });
    const html = buildPdfHtml(carePlan);
    expect(html).toContain("We couldn't confirm the specific findings from your note.");
  });

  it('omits the "What the Doctor Found" section when there is no evidence of a visit', () => {
    const carePlan = baseCarePlan({ reason_for_visit: [], diagnosis: { details: [] } });
    const html = buildPdfHtml(carePlan);
    expect(html).not.toContain('What the Doctor Found');
  });
});
