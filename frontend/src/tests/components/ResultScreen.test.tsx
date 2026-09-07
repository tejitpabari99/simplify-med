import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const deleteJobMock = vi.fn().mockResolvedValue(undefined);
vi.mock('../../api/api', () => ({ deleteJob: (...a: unknown[]) => deleteJobMock(...a) }));
const downloadReportMock = vi.fn();
vi.mock('../../utils/downloadReport', () => ({ downloadReport: (...a: unknown[]) => downloadReportMock(...a) }));
vi.mock('../../analytics/ga', () => ({ trackEvent: vi.fn() }));

import ResultScreen from '../../components/ResultScreen';
import type { JobDoc } from '../../hooks/useJobSnapshot';
// A real backend envelope generated from the actual pipeline models, not hand-typed.
// Unlike the minimal fixtures below, it has non-empty reason_for_visit / medications /
// warning_signs / terms so it exercises CarePlanView's ResultCard and MedicalTerm branches.
import realCarePlanOutput from '../fixtures/realCarePlanOutput.fixture.json';

const completedJobDoc: JobDoc = {
  status: 'completed', stage: 5, name: 'Jan 5 Care Plan', error_data: null,
  output_data: {
    metrics: { created_at: '2026-01-05T10:00:00Z', total_duration_ms: 12000 },
    grading: { entries: [
      { name: 'combined', target: 'before', grade: 42, grade_breakdown: null, reasoning: null },
      { name: 'combined', target: 'after', grade: 78, grade_breakdown: null, reasoning: null },
    ], enabled: true, graded_at: null },
    care_plan: { doc_type: 'care_plan', urgency: 'normal', version: '1.2', summary: 'Rest up.', reason_for_visit: [], diagnosis: { details: [] }, medications: [], tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [] },
  },
};

const errorJobDoc: JobDoc = {
  status: 'error', stage: 2, name: '', output_data: null,
  error_data: { code: 'INTERNAL_ERROR', message: 'boom', user_hint: 'Something went wrong. Please try again.', retryable: true, details: null, timestamp: '2026-01-05T10:00:00Z' },
};

describe('ResultScreen', () => {
  const deletedRef = { current: new Set<string>() };
  beforeEach(() => { deletedRef.current = new Set(); deleteJobMock.mockClear(); downloadReportMock.mockClear(); });

  it('renders title, date (no prefix), before->after score, and CarePlanView content on completed', () => {
    render(<ResultScreen jobDoc={completedJobDoc} jobId="job-1" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(screen.getByText('Jan 5 Care Plan')).toBeInTheDocument();
    expect(screen.getByText('January 5, 2026')).toBeInTheDocument();
    expect(screen.queryByText(/Simplified on/)).not.toBeInTheDocument();
    expect(screen.getByText('Simplification score 42 (before) → 78 (after)')).toBeInTheDocument();
    expect(screen.getByText('Rest up.')).toBeInTheDocument();
  });

  it('moves focus to the heading and announces arrival via aria-live on a completed result', () => {
    render(<ResultScreen jobDoc={completedJobDoc} jobId="job-1" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(document.activeElement?.tagName).toBe('H1');
    expect(document.activeElement).toHaveTextContent('Jan 5 Care Plan');
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(/care plan is ready/i);
  });

  it('moves focus to the heading and announces the problem via aria-live on an error result', () => {
    render(<ResultScreen jobDoc={errorJobDoc} jobId="job-2" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(document.activeElement?.tagName).toBe('H1');
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(/problem creating your care plan/i);
  });

  it('does not render "Other Items From Your Visit" even when low_priority has entries', () => {
    const jobDoc: JobDoc = {
      status: 'completed', stage: 5, name: 'With Low Priority', error_data: null,
      output_data: {
        metrics: { created_at: '2026-01-05T10:00:00Z' },
        grading: { entries: [], enabled: false, graded_at: null },
        care_plan: {
          doc_type: 'care_plan', urgency: 'normal', version: '1.2', summary: 'Rest up.',
          reason_for_visit: [], diagnosis: { details: [] }, medications: [], tests: [],
          procedures: [], other: [], follow_up: [], warning_signs: [], questions: [],
          low_priority: ['Drink more water'],
        },
      },
    };
    render(<ResultScreen jobDoc={jobDoc} jobId="job-5" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(screen.queryByText('Other Items From Your Visit')).not.toBeInTheDocument();
    expect(screen.queryByText('Drink more water')).not.toBeInTheDocument();
  });

  it('renders the error message and Try again button on error, calling onRestart when clicked', async () => {
    const onRestart = vi.fn();
    const user = userEvent.setup();
    render(<ResultScreen jobDoc={errorJobDoc} jobId="job-2" deletedRef={deletedRef} onRestart={onRestart} />);
    expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRestart).toHaveBeenCalledOnce();
  });

  it('calls downloadReport when "Download report" is clicked', async () => {
    const user = userEvent.setup();
    render(<ResultScreen jobDoc={completedJobDoc} jobId="job-1" deletedRef={deletedRef} onRestart={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Download report' }));
    expect(downloadReportMock).toHaveBeenCalledOnce();
  });

  it('renders a full realistic backend payload (with terms glossary + medications + warning signs) without throwing', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const jobDoc: JobDoc = {
      status: 'completed', stage: 5, name: 'High Blood Pressure', error_data: null,
      output_data: realCarePlanOutput as unknown as Record<string, unknown>,
    };
    const { container } = render(<ResultScreen jobDoc={jobDoc} jobId="job-real-1" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(screen.getByText('High Blood Pressure')).toBeInTheDocument();
    // Renders a medication (exercises CarePlanView's list branches).
    expect(screen.getByText(/Lisinopril/)).toBeInTheDocument();
    // The summary text contains "hypertension", which is in the terms
    // glossary — renderTextWithTerms wraps it in <MedicalTerm>, a component
    // with useState/useId/useRef/useEffect.
    expect(container.querySelectorAll('.medical-term').length).toBeGreaterThan(0);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  it('renders the care plan without crashing when grading is missing entirely', () => {
    const jobDoc: JobDoc = {
      status: 'completed', stage: 5, name: 'No Grading', error_data: null,
      output_data: {
        metrics: { created_at: '2026-01-05T10:00:00Z' },
        care_plan: { doc_type: 'care_plan', urgency: 'normal', version: '1.2', summary: 'Drink water.', reason_for_visit: [], diagnosis: { details: [] }, medications: [], tests: [], procedures: [], other: [], follow_up: [], warning_signs: [], questions: [], low_priority: [] },
        // grading key omitted entirely — simulates a partial/malformed write.
      },
    };
    render(<ResultScreen jobDoc={jobDoc} jobId="job-3" deletedRef={deletedRef} onRestart={vi.fn()} />);
    expect(screen.getByText('No Grading')).toBeInTheDocument();
    expect(screen.getByText('Drink water.')).toBeInTheDocument();
    // No before/after score widget when there's nothing to compute it from.
    expect(screen.queryByText(/→/)).not.toBeInTheDocument();
  });

  it('shows an explicit restart message — never a blank screen — when a completed job has null output_data', () => {
    const onRestart = vi.fn();
    const jobDoc: JobDoc = {
      status: 'completed', stage: 5, name: 'Ghost Job', error_data: null, output_data: null,
    };
    const { container } = render(
      <ResultScreen jobDoc={jobDoc} jobId="job-4" deletedRef={deletedRef} onRestart={onRestart} />,
    );
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByText(/couldn't load your results/)).toBeInTheDocument();
    screen.getByRole('button', { name: 'Start over' }).click();
    expect(onRestart).toHaveBeenCalledOnce();
  });
});
