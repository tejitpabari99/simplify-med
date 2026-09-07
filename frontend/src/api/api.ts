import { onAuthStateChanged, signInAnonymously, type User } from 'firebase/auth';
import { firebaseAuth } from './firebase';
import { API_URL } from './firebase';
import { ApiError } from '../types/errors';
import type { ApiErrorResponse } from '../types/errors';

export interface CreateJobResponse {
  job_id: string;
}

// How long we're willing to wait for the anonymous auth session to resolve before
// treating it as unavailable. This is a no-login app — a "please sign in" style
// error must never reach the user, so every path below tolerates a missing user for a
// while before giving up.
const AUTH_WAIT_TIMEOUT_MS = 5000;

/**
 * Resolves with the first non-null Firebase auth user, or `null` if none shows up
 * within `timeoutMs`. Covers the startup race where a request is made before
 * `signInAnonymously` (kicked off by useAnonAuth on mount) has completed, and any
 * transient window where the anonymous session is momentarily lost.
 */
function waitForAuthUser(timeoutMs: number): Promise<User | null> {
  return new Promise((resolve) => {
    if (firebaseAuth.currentUser) {
      resolve(firebaseAuth.currentUser);
      return;
    }

    let settled = false;
    const finish = (user: User | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      unsubscribe();
      resolve(user);
    };

    const timer = setTimeout(() => finish(firebaseAuth.currentUser), timeoutMs);
    const unsubscribe = onAuthStateChanged(firebaseAuth, (user) => {
      if (user) finish(user);
    });
  });
}

/**
 * Resolves the current anonymous Firebase user, self-healing where possible: check
 * `currentUser`, wait briefly for `onAuthStateChanged`, then retry once via
 * `signInAnonymously`. Only throws once all three fail, and never mentions "signing in" —
 * not something a visitor of this no-login app can act on.
 */
async function getCurrentUser(): Promise<User> {
  let user = firebaseAuth.currentUser ?? (await waitForAuthUser(AUTH_WAIT_TIMEOUT_MS));

  if (!user) {
    try {
      await signInAnonymously(firebaseAuth);
    } catch (err) {
      console.error('api: self-heal signInAnonymously failed', err);
    }
    user = firebaseAuth.currentUser ?? (await waitForAuthUser(AUTH_WAIT_TIMEOUT_MS));
  }

  if (!user) {
    throw new Error("Couldn't start your session. Please refresh and try again.");
  }
  return user;
}

async function getAuthHeader(): Promise<Record<string, string>> {
  const user = await getCurrentUser();
  let token: string;
  try {
    token = await user.getIdToken();
  } catch (err) {
    // getIdToken() can reject with a raw Firebase SDK error (e.g. "Firebase: Error
    // (auth/network-request-failed)."), which would otherwise reach the caller's
    // catch-all and be shown to the visitor verbatim. Log the real error, surface a
    // plain-English one that never mentions "signing in" (no-login app).
    console.error('api: user.getIdToken() failed', err);
    throw new Error('Something went wrong starting your session. Please try again.');
  }
  return { Authorization: `Bearer ${token}` };
}

export async function createJob(formData: FormData): Promise<CreateJobResponse> {
  const headers = await getAuthHeader();
  const res = await fetch(`${API_URL}/jobs`, { method: 'POST', headers, body: formData });
  if (!res.ok) {
    let parsed: unknown;
    try { parsed = await res.json(); } catch { parsed = null; }
    if (parsed && typeof parsed === 'object' && (parsed as ApiErrorResponse).error) {
      const errBody = parsed as ApiErrorResponse;
      throw new ApiError(errBody.error, errBody.requestId ?? null);
    }
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Best-effort, fire-and-forget job deletion. Uses fetch(keepalive) rather than
 * navigator.sendBeacon so a DELETE with an Authorization header can be sent from an
 * unload handler. Unlike createJob, never self-heals or throws — no user in time
 * just means a no-op, since there's nothing to clean up without a session. */
export async function deleteJob(jobId: string): Promise<void> {
  const user = firebaseAuth.currentUser ?? (await waitForAuthUser(AUTH_WAIT_TIMEOUT_MS));
  if (!user) return;
  const token = await user.getIdToken();
  await fetch(`${API_URL}/jobs/${jobId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
    keepalive: true,
  });
}
