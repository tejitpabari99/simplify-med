import { describe, it, expect } from 'vitest';
import { buildNextStepsRows } from '../../utils/nextSteps';
import type { CarePlanContent, Medication, Test, Procedure, OtherInstruction, FollowUp } from '../../types/carePlan';

function baseCarePlan(overrides: Partial<CarePlanContent> = {}): CarePlanContent {
  return {
    summary: '',
    summary_fact_ids: [],
    reason_for_visit: [],
    diagnosis: { details: [] },
    medications: [],
    tests: [],
    procedures: [],
    other: [],
    follow_up: [],
    warning_signs: [],
    questions: [],
    low_priority: [],
    ...overrides,
  };
}

function medication(overrides: Partial<Medication> = {}): Medication {
  return { title: 'Med', change: '', status: 'to_do', ...overrides };
}
function testItem(overrides: Partial<Test> = {}): Test {
  return { title: 'Test', description: 'desc', status: 'to_do', ...overrides };
}
function procedure(overrides: Partial<Procedure> = {}): Procedure {
  return { title: 'Procedure', status: 'to_do', ...overrides };
}
function other(overrides: Partial<OtherInstruction> = {}): OtherInstruction {
  return { title: 'Other', status: 'to_do', ...overrides };
}
function followUp(overrides: Partial<FollowUp> = {}): FollowUp {
  return { time_frame: '2 weeks', description: 'Follow up', status: 'to_do', ...overrides };
}

describe('buildNextStepsRows', () => {
  it('builds one row per actionable item across all five source arrays', () => {
    const carePlan = baseCarePlan({
      medications: [medication()],
      tests: [testItem()],
      procedures: [procedure()],
      other: [other()],
      follow_up: [followUp()],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows).toHaveLength(5);
  });

  it('splits to_do before done, regardless of input order', () => {
    const carePlan = baseCarePlan({
      medications: [medication({ title: 'Med done', status: 'done' })],
      tests: [testItem({ title: 'Test to_do', status: 'to_do' })],
      procedures: [procedure({ title: 'Procedure done', status: 'done' })],
      follow_up: [followUp({ description: 'Follow-up to_do', status: 'to_do' })],
    });
    const rows = buildNextStepsRows(carePlan);
    const firstDoneIndex = rows.findIndex(r => r.status === 'done');
    const lastToDoIndex = rows.map(r => r.status).lastIndexOf('to_do');
    expect(firstDoneIndex).toBeGreaterThan(lastToDoIndex);
  });

  it('orders by the fixed type precedence within a status group', () => {
    const carePlan = baseCarePlan({
      other: [other({ title: 'Other item' })],
      follow_up: [followUp({ description: 'Follow-up item' })],
      procedures: [procedure({ title: 'Procedure item' })],
      tests: [testItem({ title: 'Test item' })],
      medications: [medication({ title: 'Medication item' })],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows.map(r => r.type)).toEqual(['medication', 'test', 'procedure', 'follow_up', 'other']);
  });

  it('preserves original array order for two items of the same type and status', () => {
    const carePlan = baseCarePlan({
      medications: [
        medication({ title: 'First medication' }),
        medication({ title: 'Second medication' }),
      ],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows.map(r => r.title)).toEqual(['First medication', 'Second medication']);
  });

  it('medication detail joins dosage/frequency/timing/duration with a single separator, omitting empty fields', () => {
    const carePlan = baseCarePlan({
      medications: [medication({ dosage: '10 mg', duration: 'for 30 days' })],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows[0].detail).toBe('10 mg · for 30 days');
  });

  it('follow_up row uses description as title and time_frame as detail', () => {
    const carePlan = baseCarePlan({
      follow_up: [followUp({ time_frame: '3 weeks', description: 'Review labs' })],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows[0].title).toBe('Review labs');
    expect(rows[0].detail).toBe('3 weeks');
  });

  it('other row surfaces steps separately from detail', () => {
    const carePlan = baseCarePlan({
      other: [other({ title: 'Home monitoring', steps: ['Sit quietly.', 'Write it down.'], description: 'Do this daily' })],
    });
    const rows = buildNextStepsRows(carePlan);
    expect(rows[0].steps).toEqual(['Sit quietly.', 'Write it down.']);
    expect(rows[0].detail).toBe('Do this daily');
  });
});
