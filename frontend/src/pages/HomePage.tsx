import { useState, useRef } from 'react';
import type { AppState } from '../types/carePlan';
import { useAnonAuth } from '../hooks/useAnonAuth';
import { useJobSnapshot } from '../hooks/useJobSnapshot';
import type { JobDoc } from '../hooks/useJobSnapshot';
import { useUnloadCleanup } from '../hooks/useUnloadCleanup';
import { deleteJob } from '../api/api';
import UploadScreen from '../components/UploadScreen';
import ProcessingScreen from '../components/ProcessingScreen';
import ResultScreen from '../components/ResultScreen';
import Footer from '../components/Footer';

export default function HomePage() {
  const [appState, setAppState] = useState<AppState>('upload');
  const [jobId, setJobId] = useState<string | null>(null);
  // Captured once the live snapshot first reaches a terminal state. Rendering
  // the result screen from this copy (rather than the live jobDoc) is what
  // keeps the screen up after the backend deletes the document — see below.
  const [finalJobDoc, setFinalJobDoc] = useState<JobDoc | null>(null);
  const { authState, retry } = useAnonAuth();
  // Once finalJobDoc is captured there is nothing left to watch: passing null
  // here tears down the Firestore listener (useJobSnapshot's existing,
  // tested unsubscribe-on-null-id path) so a subsequent "document deleted"
  // event from the listener can never null out what we render.
  const { jobDoc, exists: jobExists, error: snapshotError } = useJobSnapshot(finalJobDoc ? null : jobId);
  const deletedRef = useRef<Set<string>>(new Set());

  useUnloadCleanup(jobId, appState, deletedRef);

  function handleJobCreated(id: string) {
    setJobId(id);
    setAppState('processing');
  }

  if (appState === 'processing' && !finalJobDoc && jobDoc && (jobDoc.status === 'completed' || jobDoc.status === 'error')) {
    setFinalJobDoc(jobDoc);
    setAppState('result');
  }

  function handleRestart() {
    // "Start over" can now be reached from the processing screen's watchdog
    // (job stuck, but not yet confirmed gone — see ProcessingScreen) as well
    // as its jobGone/snapshotError branches. Best-effort clean up the
    // abandoned job rather than leaving it solely to the TTL backstop;
    // deletedRef is the same idempotency guard ResultScreen/useUnloadCleanup
    // use, so this can never double-fire a delete for the same job.
    if (jobId && !deletedRef.current.has(jobId)) {
      deletedRef.current.add(jobId);
      void deleteJob(jobId).catch(() => { /* best-effort; expires_at is the safety net */ });
    }
    setJobId(null);
    setFinalJobDoc(null);
    setAppState('upload');
  }

  return (
    <div className="home-page">
      {appState === 'upload' && (
        <UploadScreen authState={authState} onAuthRetry={retry} onJobCreated={handleJobCreated} />
      )}
      {appState === 'processing' && (
        <ProcessingScreen
          jobDoc={jobDoc}
          snapshotError={snapshotError}
          jobExists={jobExists}
          onRestart={handleRestart}
        />
      )}
      {appState === 'result' && finalJobDoc && (
        <ResultScreen jobDoc={finalJobDoc} jobId={jobId} deletedRef={deletedRef} onRestart={handleRestart} />
      )}
      <Footer />
    </div>
  );
}
