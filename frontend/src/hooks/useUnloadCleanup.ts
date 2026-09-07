import { useEffect } from 'react';
import type { AppState } from '../types/carePlan';
import { deleteJob } from '../api/api';

// visibilitychange->hidden only triggers delete once appState === 'result': firing it
// during 'processing' would delete a still-running job the moment the user switches
// tabs or locks their phone, permanently stranding it. An abandoned processing job is
// instead left to the backend's TTL (`expires_at`) as the real safety net.
// window.pagehide fires unconditionally for any non-upload appState — unlike
// visibilitychange, it only fires on genuine navigation-away/teardown (including
// bfcache eviction), so it's safe to treat as "done with this tab" either way.
export function useUnloadCleanup(
  jobId: string | null,
  appState: AppState,
  deletedRef: React.MutableRefObject<Set<string>>,
): void {
  useEffect(() => {
    if (!jobId || appState === 'upload') return;

    const fireOnce = () => {
      if (deletedRef.current.has(jobId)) return;
      deletedRef.current.add(jobId);
      void deleteJob(jobId).catch(() => { /* best-effort; expires_at is the safety net */ });
    };

    const onVisibilityChange = () => {
      if (appState === 'result' && document.visibilityState === 'hidden') fireOnce();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('pagehide', fireOnce);

    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('pagehide', fireOnce);
    };
  }, [jobId, appState, deletedRef]);
}
