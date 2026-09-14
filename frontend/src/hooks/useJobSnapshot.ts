import { useEffect, useState } from 'react';
import { doc, onSnapshot } from 'firebase/firestore';
import { firebaseDb } from '../api/firebase';
import type { FirestoreJobError } from '../types/errors';

export type JobStatus = 'not_started' | 'processing' | 'completed' | 'error';

// The full set of statuses the backend ever writes to a job doc (see
// backend/models/api_response.py StatusEnum as used by backend/models/job.py,
// and the literal "completed"/"error"/"processing" strings in
// backend/utils/firebase.py's complete_job/fail_job and
// backend/routes/worker.py). StatusEnum also defines "success", but that value
// is only ever used for HTTP ApiResponse envelopes, never written as a job
// doc's `status` field.
const KNOWN_JOB_STATUSES: readonly JobStatus[] = ['not_started', 'processing', 'completed', 'error'];

function isKnownJobStatus(value: unknown): value is JobStatus {
  return typeof value === 'string' && (KNOWN_JOB_STATUSES as readonly string[]).includes(value);
}

export interface JobDoc {
  status: JobStatus;
  stage: number | null;
  output_data: Record<string, unknown> | null;
  error_data: FirestoreJobError | null;
  name: string;
}

export function useJobSnapshot(jobId: string | null): {
  jobDoc: JobDoc | null;
  // Null until the first snapshot callback arrives (loading/not-yet-known);
  // true/false thereafter reflects the doc's actual existence. Callers must
  // not treat `jobDoc === null` alone as "the job is gone" — the backend
  // creates the Firestore doc BEFORE returning job_id to the client, so a
  // jobId always refers to a real doc, but the initial snapshot can arrive
  // slightly after mount. Only `exists === false` (confirmed by a real
  // snapshot callback) means the doc was actually deleted/expired out from
  // under a live listener.
  exists: boolean | null;
  loading: boolean;
  error: Error | null;
} {
  const [jobDoc, setJobDoc] = useState<JobDoc | null>(null);
  const [exists, setExists] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(jobId !== null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!jobId) {
      // Resetting local snapshot state here is synchronizing with the Firestore
      // listener lifecycle (torn down/not started because there's no jobId), not
      // deriving state from a prop — the documented exception to this rule. See
      // https://react.dev/learn/you-might-not-need-an-effect#subscribing-to-an-external-store
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setJobDoc(null);
      setExists(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);

    const unsubscribe = onSnapshot(
      doc(firebaseDb, 'care_plan_outputs', jobId),
      (snapshot) => {
        if (!snapshot.exists()) {
          setJobDoc(null);
          setExists(false);
          setLoading(false);
          return;
        }
        const data = snapshot.data();
        const rawStatus: unknown = data.status;
        // Owner requirement: the user must never be left blocked or without
        // info. Callers key their "is this job done" routing off `status`
        // (HomePage treats only 'completed'/'error' as terminal), so a status
        // value outside the backend's known set would otherwise never match
        // and would strand the user on ProcessingScreen until the 6-minute
        // watchdog. Treat anything unrecognized as a terminal internal error
        // instead, so the existing generic error UI takes over immediately.
        // error_data is dropped rather than passed through: it wasn't written
        // by the normal fail_job() path for this status, so it isn't
        // guaranteed to be PHI-free/user-safe.
        let status: JobStatus;
        let errorData = (data.error_data ?? null) as FirestoreJobError | null;
        if (rawStatus == null) {
          status = 'completed';
        } else if (isKnownJobStatus(rawStatus)) {
          status = rawStatus;
        } else {
          console.error('useJobSnapshot: unrecognized job status from Firestore', rawStatus);
          status = 'error';
          errorData = null;
        }
        setJobDoc({
          status,
          stage: data.stage ?? null,
          output_data: data.output_data ?? null,
          error_data: errorData,
          name: data.name ?? '',
        });
        setExists(true);
        setLoading(false);
      },
      (err) => {
        setError(err);
        setLoading(false);
      },
    );

    return unsubscribe;
  }, [jobId]);

  return { jobDoc, exists, loading, error };
}
