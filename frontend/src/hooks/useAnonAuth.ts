import { useEffect, useRef, useState } from 'react';
import { onAuthStateChanged, signInAnonymously, type User } from 'firebase/auth';
import { firebaseAuth } from '../api/firebase';
import { trackEvent } from '../analytics/ga';

export type AuthState = 'pending' | 'ready' | 'error';

// How long we're willing to sit in 'pending' before giving up and surfacing the
// Retry button. Without this, a signInAnonymously promise that never settles (or
// settles with no onAuthStateChanged callback) leaves authState stuck 'pending'
// forever with no actionable UI. Mirrors api.ts's waitForAuthUser for this race.
const AUTH_TIMEOUT_MS = 10_000;

export function useAnonAuth(): { authState: AuthState; user: User | null; retry: () => void } {
  const [authState, setAuthState] = useState<AuthState>('pending');
  const [user, setUser] = useState<User | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Mirrors `authState` for synchronous reads inside the timeout callback
  // below, without making that callback a dependency of the effect (it must
  // stay a plain mount/retry-only effect — see the `[attempt]` deps). Updated
  // in its own effect (not during render) per react-hooks/refs.
  const authStateRef = useRef<AuthState>(authState);
  useEffect(() => {
    authStateRef.current = authState;
  });

  useEffect(() => {
    let cancelled = false;

    const timeoutId = setTimeout(() => {
      if (cancelled || authStateRef.current !== 'pending') return;
      setAuthState('error');
      trackEvent({ name: 'auth_failed', params: {} });
    }, AUTH_TIMEOUT_MS);

    const unsubscribe = onAuthStateChanged(firebaseAuth, (firebaseUser) => {
      if (cancelled || !firebaseUser) return;
      clearTimeout(timeoutId);
      setUser(firebaseUser);
      setAuthState('ready');
      trackEvent({ name: 'auth_ready', params: {} });
    });

    signInAnonymously(firebaseAuth).catch((err) => {
      if (cancelled) return;
      console.error('useAnonAuth: signInAnonymously failed', err);
      clearTimeout(timeoutId);
      setAuthState('error');
      trackEvent({ name: 'auth_failed', params: {} });
    });

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
      unsubscribe();
    };
  }, [attempt]);

  return {
    authState,
    user,
    // Reset to 'pending' here (in the event handler, not the effect) so the retry
    // flow doesn't call setState synchronously within an effect body. The initial
    // mount already starts at 'pending' via useState, so this only matters on retry.
    retry: () => {
      setAuthState('pending');
      setAttempt(a => a + 1);
    },
  };
}
