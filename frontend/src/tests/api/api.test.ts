import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../api/firebase', () => ({
  firebaseAuth: { currentUser: null },
  API_URL: 'http://localhost:8080',
}));

const mockOnAuthStateChanged = vi.fn();
const mockSignInAnonymously = vi.fn();
vi.mock('firebase/auth', () => ({
  onAuthStateChanged: (auth: unknown, cb: (u: unknown) => void) => {
    mockOnAuthStateChanged(auth, cb);
    return vi.fn(); // unsubscribe
  },
  signInAnonymously: (...args: unknown[]) => mockSignInAnonymously(...args),
}));

import { createJob, deleteJob } from '../../api/api';
import * as firebaseModule from '../../api/firebase';

function setCurrentUser(user: unknown) {
  (firebaseModule.firebaseAuth as { currentUser: unknown }).currentUser = user;
}

describe('api', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch');
    mockOnAuthStateChanged.mockReset();
    mockSignInAnonymously.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    setCurrentUser(null);
  });

  describe('createJob', () => {
    it('POSTs to /jobs with an Authorization header and the given FormData', async () => {
      const mockUser = { getIdToken: vi.fn().mockResolvedValue('tok-abc') };
      setCurrentUser(mockUser);
      fetchSpy.mockResolvedValue(new Response(JSON.stringify({ job_id: 'job-1' }), { status: 202 }));

      const fd = new FormData();
      fd.append('text', 'hi');
      const result = await createJob(fd);

      expect(result).toEqual({ job_id: 'job-1' });
      const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8080/jobs');
      expect(init.method).toBe('POST');
      expect(init.body).toBe(fd);
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-abc');
    });

    it('throws ApiError with the server code/userHint on a 400/429 error envelope', async () => {
      const mockUser = { getIdToken: vi.fn().mockResolvedValue('tok') };
      setCurrentUser(mockUser);
      fetchSpy.mockResolvedValue(new Response(JSON.stringify({
        status: 'error',
        error: { code: 'RATE_LIMIT_EXCEEDED', message: 'Rate limit exceeded', details: null, timestamp: '2026-01-01T00:00:00Z', path: '/jobs', user_hint: 'Try again later.', retryable: true },
        requestId: 'req-1',
      }), { status: 429 }));

      await expect(createJob(new FormData())).rejects.toMatchObject({
        code: 'RATE_LIMIT_EXCEEDED',
        userHint: 'Try again later.',
      });
    });

    it('waits for onAuthStateChanged to resolve a user when currentUser is initially null, then succeeds with no error', async () => {
      setCurrentUser(null);
      const mockUser = { getIdToken: vi.fn().mockResolvedValue('tok-late') };
      fetchSpy.mockResolvedValue(new Response(JSON.stringify({ job_id: 'job-2' }), { status: 202 }));

      const resultPromise = createJob(new FormData());

      // Auth resolves shortly after the request starts — simulate onAuthStateChanged
      // firing once signInAnonymously (kicked off elsewhere, e.g. useAnonAuth) completes.
      await vi.waitFor(() => expect(mockOnAuthStateChanged).toHaveBeenCalled());
      const cb = mockOnAuthStateChanged.mock.calls[0][1] as (u: unknown) => void;
      setCurrentUser(mockUser);
      cb(mockUser);

      const result = await resultPromise;
      expect(result).toEqual({ job_id: 'job-2' });
      expect(mockSignInAnonymously).not.toHaveBeenCalled();
      const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-late');
    });

    it('self-heals via signInAnonymously when the initial wait times out, then succeeds', async () => {
      vi.useFakeTimers();
      setCurrentUser(null);
      const mockUser = { getIdToken: vi.fn().mockResolvedValue('tok-healed') };
      mockSignInAnonymously.mockImplementation(async () => {
        setCurrentUser(mockUser);
      });
      fetchSpy.mockResolvedValue(new Response(JSON.stringify({ job_id: 'job-3' }), { status: 202 }));

      const resultPromise = createJob(new FormData());
      // Nobody ever calls the onAuthStateChanged callback with a user, so the initial
      // wait must time out before the self-heal kicks in.
      await vi.advanceTimersByTimeAsync(5000);

      const result = await resultPromise;
      expect(result).toEqual({ job_id: 'job-3' });
      expect(mockSignInAnonymously).toHaveBeenCalledTimes(1);
    });

    it('throws a generic, non-sign-in error if the wait and the self-heal both fail', async () => {
      vi.useFakeTimers();
      setCurrentUser(null);
      mockSignInAnonymously.mockRejectedValue(new Error('network down'));

      const resultPromise = createJob(new FormData());
      const assertion = expect(resultPromise).rejects.toThrow("Couldn't start your session. Please refresh and try again.");
      await vi.advanceTimersByTimeAsync(5000); // initial waitForAuthUser timeout
      await vi.advanceTimersByTimeAsync(5000); // post-self-heal waitForAuthUser timeout
      await assertion;

      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('maps a raw Firebase SDK error from getIdToken() to a plain-English message, logging the original', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const rawFirebaseError = new Error('Firebase: Error (auth/network-request-failed).');
      const mockUser = { getIdToken: vi.fn().mockRejectedValue(rawFirebaseError) };
      setCurrentUser(mockUser);

      let caught: unknown;
      try {
        await createJob(new FormData());
      } catch (err) {
        caught = err;
      }

      expect(caught).toBeInstanceOf(Error);
      const message = (caught as Error).message;
      expect(message).toBe('Something went wrong starting your session. Please try again.');
      // Never leak the raw SDK text, and never mention signing in -- this is a
      // no-login app.
      expect(message).not.toMatch(/firebase|sign.?in|log.?in/i);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(consoleErrorSpy).toHaveBeenCalledWith('api: user.getIdToken() failed', rawFirebaseError);
      consoleErrorSpy.mockRestore();
    });
  });

  describe('deleteJob', () => {
    it('sends DELETE with keepalive:true and the Authorization header', async () => {
      const mockUser = { getIdToken: vi.fn().mockResolvedValue('tok') };
      setCurrentUser(mockUser);
      fetchSpy.mockResolvedValue(new Response(null, { status: 204 }));

      await deleteJob('job-1');

      const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://localhost:8080/jobs/job-1');
      expect(init.method).toBe('DELETE');
      expect(init.keepalive).toBe(true);
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    });

    it('is a no-op (no fetch call, no thrown error, no self-heal sign-in) when no user shows up within the wait window', async () => {
      vi.useFakeTimers();
      setCurrentUser(null);

      const donePromise = deleteJob('job-1');
      await vi.advanceTimersByTimeAsync(5000);
      await donePromise;

      expect(fetchSpy).not.toHaveBeenCalled();
      expect(mockSignInAnonymously).not.toHaveBeenCalled();
    });
  });
});
