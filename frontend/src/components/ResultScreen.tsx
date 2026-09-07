import { useEffect, useRef } from 'react';
import CarePlanView from './CarePlanView';
import type { CarePlanInternal } from '../types/envelope';
import type { JobDoc } from '../hooks/useJobSnapshot';
import { deleteJob } from '../api/api';
import { downloadReport } from '../utils/downloadReport';
import { trackEvent } from '../analytics/ga';
import ErrorBoundary from './ErrorBoundary';

interface ResultScreenProps {
  jobDoc: JobDoc;
  jobId: string | null;
  deletedRef: React.MutableRefObject<Set<string>>;
  onRestart: () => void;
}

export default function ResultScreen({ jobDoc, jobId, deletedRef, onRestart }: ResultScreenProps) {
  const trackedRef = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Move focus to this screen's heading on arrival: ResultScreen mounts fresh exactly
  // once per completed/errored job, announcing "results have arrived" to
  // screen-reader users regardless of which branch below actually renders.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  // Primary DELETE trigger (layer 1) — fires once, on reaching this screen,
  // sharing deletedRef with HomePage's safety-net trigger so the two can
  // never double-fire in a way that matters (DELETE is idempotent anyway).
  useEffect(() => {
    if (!jobId || deletedRef.current.has(jobId)) return;
    deletedRef.current.add(jobId);
    void deleteJob(jobId).catch(() => { /* best-effort */ });
  }, [jobId, deletedRef]);

  const outputData = jobDoc.output_data as unknown as CarePlanInternal | null;

  useEffect(() => {
    if (trackedRef.current) return;
    if (jobDoc.status === 'completed' && outputData) {
      trackedRef.current = true;
      // Defensively-accessed: output_data's shape is only a TypeScript contract, not
      // a runtime guarantee, and a partially-populated payload must not crash this effect.
      const entries = outputData.grading?.entries ?? [];
      const combined = entries.filter(e => e.name === 'combined');
      const before = combined.find(e => e.target === 'before')?.grade ?? 0;
      const after = combined.find(e => e.target === 'after')?.grade ?? 0;
      trackEvent({
        name: 'simplify_complete',
        params: {
          total_duration_ms: outputData.metrics?.total_duration_ms ?? 0,
          score_before: before,
          score_after: after,
        },
      });
    } else if (jobDoc.status === 'error' && jobDoc.error_data) {
      trackedRef.current = true;
      trackEvent({
        name: 'simplify_pipeline_error',
        params: { error_code: jobDoc.error_data.code, stage_reached: jobDoc.stage },
      });
    }
  }, [jobDoc, outputData]);

  if (jobDoc.status === 'error') {
    const message = jobDoc.error_data?.user_hint ?? jobDoc.error_data?.message
      ?? 'Something went wrong while creating your care plan.';
    return (
      <div className="glass-card">
        <h1 ref={headingRef} tabIndex={-1} className="section-title">{jobDoc.name || 'Your care plan'}</h1>
        <p className="sr-only" role="status" aria-live="polite">There was a problem creating your care plan.</p>
        <p className="error-box">{message}</p>
        <button className="cta-btn" onClick={onRestart}>Try again</button>
      </div>
    );
  }

  // Explicit, honest fallback for a "completed" job with no output_data — must never
  // silently render nothing and look like a blank page.
  if (!outputData) {
    return (
      <div className="glass-card">
        <h1 ref={headingRef} tabIndex={-1} className="section-title">{jobDoc.name || 'Your care plan'}</h1>
        <p className="sr-only" role="status" aria-live="polite">There was a problem creating your care plan.</p>
        <p className="error-box">
          Processing finished, but we couldn't load your results. Nothing was saved.
        </p>
        <button className="cta-btn" onClick={onRestart}>Start over</button>
      </div>
    );
  }

  // The payload's real-world shape can diverge from the CarePlanInternal type (a
  // partial write, schema drift), so optional-chain and default every field below
  // rather than let a missing nice-to-have (score, date) hide the actual result.
  const care_plan = outputData.care_plan;
  const grading = outputData.grading ?? { entries: [], enabled: false, graded_at: null };
  const metrics = outputData.metrics;
  const combined = (grading.entries ?? []).filter(e => e.name === 'combined');
  const before = combined.find(e => e.target === 'before')?.grade;
  const after = combined.find(e => e.target === 'after')?.grade;
  const formattedDate = metrics?.created_at
    ? new Date(metrics.created_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
    : null;

  return (
    <div>
      <h1 ref={headingRef} tabIndex={-1}>{jobDoc.name || 'Your care plan'}</h1>
      <p className="sr-only" role="status" aria-live="polite">Your care plan is ready.</p>
      {formattedDate && <p>{formattedDate}</p>}
      {before != null && after != null && (
        <p className="score-widget">Simplification score {before} (before) → {after} (after)</p>
      )}
      {care_plan ? (
        <>
          {/* Local safety net: CarePlanView reads a payload this component
              only casts, never validates. If it throws on an unexpected
              shape, degrade to a message here instead of losing the whole
              result screen (or, absent the app-root boundary, the whole page). */}
          <ErrorBoundary title="We couldn't display your care plan" onReset={onRestart}>
            <CarePlanView result={care_plan} hideLowPriority />
          </ErrorBoundary>
          <button className="cta-btn" onClick={() => downloadReport(care_plan, grading)}>
            Download report
          </button>
        </>
      ) : (
        <p className="error-box">Your care plan details couldn't be loaded, but processing did finish.</p>
      )}
    </div>
  );
}
