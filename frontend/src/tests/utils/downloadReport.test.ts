import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const trackEventMock = vi.fn();
vi.mock('../../analytics/ga', () => ({ trackEvent: (...a: unknown[]) => trackEventMock(...a) }));

import { downloadReport } from '../../utils/downloadReport';
import type { SimplifiedCarePlan, Grading } from '../../types/envelope';

const fixture: SimplifiedCarePlan = {
  summary: 'Take it easy for a week.', reason_for_visit: [], diagnosis: { details: [] },
  medications: [], tests: [], procedures: [], other: [], follow_up: [],
  warning_signs: [], questions: [], low_priority: ['Drink more water'],
  terms: { hypertension: { definition: 'High blood pressure', source: 'medical', imgUrl: null, altText: null } },
};
const grading: Grading = {
  enabled: true,
  graded_at: null,
  entries: [
    { name: 'combined', target: 'before', grade: 42, grade_breakdown: null, reasoning: null },
    { name: 'combined', target: 'after', grade: 78, grade_breakdown: null, reasoning: null },
  ],
};

describe('downloadReport', () => {
  beforeEach(() => { vi.useFakeTimers(); trackEventMock.mockClear(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it('writes non-empty HTML and calls print() after the 500ms delay', () => {
    const printSpy = vi.fn();
    const fakeWindow = { document: { write: vi.fn(), close: vi.fn() }, print: printSpy };
    vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window);

    downloadReport(fixture, grading);

    expect(fakeWindow.document.write).toHaveBeenCalledOnce();
    const html = fakeWindow.document.write.mock.calls[0][0] as string;
    expect(html).toContain('Take it easy for a week.');
    expect(printSpy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(500);
    expect(printSpy).toHaveBeenCalledOnce();
  });

  it('nulls printWindow.opener after opening the window (defense-in-depth vs stored XSS)', () => {
    const fakeWindow = { document: { write: vi.fn(), close: vi.fn() }, print: vi.fn(), opener: { some: 'window' } };
    vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window);

    downloadReport(fixture, grading);

    expect(fakeWindow.document.write).toHaveBeenCalledOnce();
    expect(fakeWindow.opener).toBeNull();
  });

  it('alerts and never calls document.write when the pop-up is blocked', () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});

    downloadReport(fixture, grading);

    expect(alertSpy).toHaveBeenCalledOnce();
  });

  it('calls trackEvent with exactly report_downloaded', () => {
    vi.spyOn(window, 'open').mockReturnValue({ document: { write: vi.fn(), close: vi.fn() }, print: vi.fn() } as unknown as Window);
    downloadReport(fixture, grading);
    expect(trackEventMock).toHaveBeenCalledWith({ name: 'report_downloaded', params: {} });
  });

  it('omits the Medical Terms Glossary, Readability, and Other Items sections from the downloaded report', () => {
    const fakeWindow = { document: { write: vi.fn(), close: vi.fn() }, print: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window);

    downloadReport(fixture, grading);

    const html = fakeWindow.document.write.mock.calls[0][0] as string;
    expect(html).not.toContain('Medical Terms Glossary');
    expect(html).not.toContain('Readability');
    expect(html).not.toContain('Other Items');
    // Sanity check: the rest of the report is still present.
    expect(html).toContain('Take it easy for a week.');
  });
});
