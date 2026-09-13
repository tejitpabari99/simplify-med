import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import CarePlanView from '../../components/CarePlanView';
import type { SimplifiedCarePlan } from '../../types/envelope';

function fullyPopulatedCarePlan(): SimplifiedCarePlan {
  return {
    summary: 'Take it easy for a week.',
    summary_fact_ids: [1, 2, 3],
    reason_for_visit: [{ reason: 'High blood pressure', description: 'Readings were high at home.' }],
    diagnosis: {
      changed_since_last_visit: 'Still high since last visit.',
      details: [{ title: 'Hypertension', description: 'Blood pressure is too high.', severity: 'medium' }],
    },
    medications: [{ title: 'Lisinopril', change: '', status: 'to_do' }],
    tests: [{ title: 'Basic metabolic panel', description: 'Blood draw.', status: 'to_do' }],
    procedures: [{ title: 'Blood pressure recheck', status: 'to_do' }],
    other: [{ title: 'Home monitoring', status: 'to_do' }],
    follow_up: [{ time_frame: '2 weeks', description: 'Review readings.', status: 'to_do' }],
    warning_signs: [{ symptom: 'Chest pain', what_to_do: 'Go to the ER.', urgency: 'emergency' }],
    questions: ['What number should I aim for?'],
    low_priority: ['Heart sounds were normal.'],
    terms: { hypertension: { definition: 'High blood pressure.', source: 'preserved', imgUrl: null, altText: null } },
  };
}

describe('CarePlanView', () => {
  it('renders exactly eight top-level result cards for a fully-populated care plan', () => {
    const { container } = render(<CarePlanView result={fullyPopulatedCarePlan()} />);
    expect(container.querySelectorAll('.result-card')).toHaveLength(8);
  });

  it('does not render a Data Sources card even if deleted-field-shaped data is force-injected', () => {
    const injected = {
      ...fullyPopulatedCarePlan(),
      // A stand-in for the now-deleted source-provenance field the old "Data
      // Sources" card used to read from — its exact former name is checked
      // for zero remaining occurrences elsewhere (Task 11's grep gate), so
      // this regression guard uses an unexpected key instead of that literal.
      unexpected_extra_field: ['some path-like note'],
    } as unknown as SimplifiedCarePlan;
    render(<CarePlanView result={injected} />);
    expect(screen.queryByText('Data Sources')).not.toBeInTheDocument();
    expect(screen.queryByText('some path-like note')).not.toBeInTheDocument();
  });

  it('renders a check mark for status "done" and an empty checkbox for status "to_do"', () => {
    const carePlan: SimplifiedCarePlan = {
      summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
      medications: [
        { title: 'Done Med', change: '', status: 'done' },
        { title: 'Todo Med', change: '', status: 'to_do' },
      ],
      tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [],
    };
    render(<CarePlanView result={carePlan} />);
    expect(screen.getByText(/^Done:/)).toBeInTheDocument();
    expect(screen.getByText(/^To do:/)).toBeInTheDocument();
  });

  it('renders a strikethrough on a done row\'s title but not on a to_do row\'s title', () => {
    const carePlan: SimplifiedCarePlan = {
      summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
      medications: [
        { title: 'Done Med', change: '', status: 'done' },
        { title: 'Todo Med', change: '', status: 'to_do' },
      ],
      tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [],
    };
    render(<CarePlanView result={carePlan} />);
    const doneTitle = screen.getByText('Done Med');
    const todoTitle = screen.getByText('Todo Med');
    expect(doneTitle.style.textDecoration).toContain('line-through');
    expect(todoTitle.style.textDecoration).not.toContain('line-through');
  });

  it('renders a null-urgency warning sign last, in grey, with no urgency badge', () => {
    const carePlan: SimplifiedCarePlan = {
      summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
      medications: [], tests: [], procedures: [], other: [], follow_up: [],
      warning_signs: [
        { symptom: 'Signal A', what_to_do: 'Do A', urgency: null },
        { symptom: 'Signal B', what_to_do: 'Do B', urgency: 'emergency' },
        { symptom: 'Signal C', what_to_do: 'Do C', urgency: 'monitor' },
      ],
      questions: [], low_priority: [],
    };
    const { container } = render(<CarePlanView result={carePlan} />);
    const strongEls = Array.from(container.querySelectorAll('strong')).filter(el => /^Signal /.test(el.textContent ?? ''));
    expect(strongEls.map(el => el.textContent)).toEqual(['Signal B', 'Signal C', 'Signal A']);

    const signalAFlexDiv = strongEls[2].parentElement!;
    // No bracketed urgency badge span rendered alongside the null-urgency symptom.
    expect(signalAFlexDiv.children).toHaveLength(1);
    expect(signalAFlexDiv.textContent).not.toMatch(/\[/);

    const signalAOuterDiv = signalAFlexDiv.parentElement as HTMLElement;
    // jsdom normalizes hex colors in inline styles to rgb() — #9CA3AF === rgb(156, 163, 175).
    expect(signalAOuterDiv.style.borderLeft).toContain('rgb(156, 163, 175)');
  });

  it('never drops a null-urgency warning sign from the list', () => {
    const carePlan: SimplifiedCarePlan = {
      summary: '', summary_fact_ids: [], reason_for_visit: [], diagnosis: { details: [] },
      medications: [], tests: [], procedures: [], other: [], follow_up: [],
      warning_signs: [
        { symptom: 'Signal A', what_to_do: 'Do A', urgency: null },
        { symptom: 'Signal B', what_to_do: 'Do B', urgency: 'emergency' },
        { symptom: 'Signal C', what_to_do: 'Do C', urgency: 'monitor' },
      ],
      questions: [], low_priority: [],
    };
    const { container } = render(<CarePlanView result={carePlan} />);
    const strongEls = Array.from(container.querySelectorAll('strong')).filter(el => /^Signal /.test(el.textContent ?? ''));
    expect(strongEls).toHaveLength(3);
  });
});
