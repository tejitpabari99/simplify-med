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

// How long we're willing to let a POST /jobs request hang before giving up. Per
// docs/architecture.md, /jobs resolves the input (including merging/uploading
// files up to the 10MB aggregate cap) and enqueues a Cloud Task synchronously
// before returning 202 -- slower than a trivial round trip, but never minutes.
// Without this, a request that never settles (dropped connection, a proxy that
// swallows the response) leaves the Simplify button stuck on "Starting..."
// forever with no way for the visitor to retry short of reloading the page.
const CREATE_JOB_TIMEOUT_MS = 60_000;

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

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CREATE_JOB_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_URL}/jobs`, { method: 'POST', headers, body: formData, signal: controller.signal });
  } catch (err) {
    // Covers both a genuine network failure (offline, DNS, TLS) and our own
    // timeout abort above -- either way `fetch()` throws a raw, technical
    // error (e.g. "Failed to fetch" / "The user aborted a request.") that
    // must never reach the visitor verbatim.
    console.error('api: createJob fetch failed', err);
    throw new Error(
      controller.signal.aborted
        ? "That's taking longer than expected. Please check your connection and try again."
        : "Couldn't reach the server. Please check your connection and try again.",
    );
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    let parsed: unknown;
    try { parsed = await res.json(); } catch { parsed = null; }
    if (parsed && typeof parsed === 'object' && (parsed as ApiErrorResponse).error) {
      const errBody = parsed as ApiErrorResponse;
      throw new ApiError(errBody.error, errBody.requestId ?? null);
    }
    // Non-JSON (or unrecognized-shape) error body -- e.g. a 5xx from a proxy/LB
    // in front of the service, or an INTERNAL_ERROR the backend couldn't
    // format. Log the status for diagnostics but never show a bare status
    // code/statusText as if it were an explanation.
    console.error(`api: createJob failed with a non-standard error response (status ${res.status})`);
    throw new Error('Something went wrong on our end. Please try again.');
  }

  try {
    return await res.json();
  } catch (err) {
    // A 2xx with a body that isn't valid JSON is still an unexpected/internal
    // failure -- surface the generic message, not the raw SyntaxError text.
    console.error('api: createJob succeeded but the response body was not valid JSON', err);
    throw new Error('Something went wrong on our end. Please try again.');
  }
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
