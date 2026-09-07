import { useEffect, useState } from 'react';
import { doc, onSnapshot } from 'firebase/firestore';
import { firebaseDb } from '../api/firebase';
import type { FirestoreJobError } from '../types/errors';

export type JobStatus = 'not_started' | 'processing' | 'completed' | 'error';

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
        setJobDoc({
          status: (data.status as JobStatus) ?? 'completed',
          stage: data.stage ?? null,
          output_data: data.output_data ?? null,
          error_data: data.error_data ?? null,
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
