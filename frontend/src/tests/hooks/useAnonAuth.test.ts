import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const mockOnAuthStateChanged = vi.fn();
const mockSignInAnonymously = vi.fn();
vi.mock('firebase/auth', () => ({
  onAuthStateChanged: (auth: unknown, cb: (u: unknown) => void) => {
    mockOnAuthStateChanged(auth, cb);
    return vi.fn();
  },
  signInAnonymously: (...args: unknown[]) => mockSignInAnonymously(...args),
}));
vi.mock('../../api/firebase', () => ({ firebaseAuth: {} }));
const trackEventMock = vi.fn();
vi.mock('../../analytics/ga', () => ({ trackEvent: (...a: unknown[]) => trackEventMock(...a) }));

import { useAnonAuth } from '../../hooks/useAnonAuth';

describe('useAnonAuth', () => {
  beforeEach(() => {
    mockOnAuthStateChanged.mockClear();
    mockSignInAnonymously.mockClear();
    trackEventMock.mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('starts pending, becomes ready once onAuthStateChanged fires with a user', async () => {
    mockSignInAnonymously.mockResolvedValue(undefined);
    const { result } = renderHook(() => useAnonAuth());
    expect(result.current.authState).toBe('pending');

    const cb = mockOnAuthStateChanged.mock.calls[0][1];
    act(() => cb({ uid: 'anon-1' }));

    await waitFor(() => expect(result.current.authState).toBe('ready'));
    expect(result.current.user).toEqual({ uid: 'anon-1' });
    expect(trackEventMock).toHaveBeenCalledWith({ name: 'auth_ready', params: {} });
  });

  it('becomes error when signInAnonymously rejects', async () => {
    mockSignInAnonymously.mockRejectedValue(new Error('network down'));
    const { result } = renderHook(() => useAnonAuth());

    await waitFor(() => expect(result.current.authState).toBe('error'));
    expect(trackEventMock).toHaveBeenCalledWith({ name: 'auth_failed', params: {} });
  });

  it('retry() re-invokes signInAnonymously and can recover to ready', async () => {
    mockSignInAnonymously.mockRejectedValueOnce(new Error('down'));
    const { result } = renderHook(() => useAnonAuth());
    await waitFor(() => expect(result.current.authState).toBe('error'));

    mockSignInAnonymously.mockResolvedValueOnce(undefined);
    act(() => result.current.retry());
    const cb = mockOnAuthStateChanged.mock.calls.at(-1)![1];
    act(() => cb({ uid: 'anon-2' }));

    await waitFor(() => expect(result.current.authState).toBe('ready'));
    expect(mockSignInAnonymously).toHaveBeenCalledTimes(2);
  });

  it('flips pending to error via the timeout when signInAnonymously never settles and onAuthStateChanged never fires', async () => {
    vi.useFakeTimers();
    mockSignInAnonymously.mockReturnValue(new Promise(() => { /* never settles */ }));
    const { result } = renderHook(() => useAnonAuth());
    expect(result.current.authState).toBe('pending');

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

    expect(result.current.authState).toBe('error');
    expect(trackEventMock).toHaveBeenCalledWith({ name: 'auth_failed', params: {} });
  });

  it('does not let a late-firing timeout clobber an authState that already reached ready', async () => {
    vi.useFakeTimers();
    mockSignInAnonymously.mockResolvedValue(undefined);
    const { result } = renderHook(() => useAnonAuth());

    const cb = mockOnAuthStateChanged.mock.calls[0][1];
    act(() => cb({ uid: 'anon-1' }));
    expect(result.current.authState).toBe('ready');

    trackEventMock.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

    expect(result.current.authState).toBe('ready');
    expect(trackEventMock).not.toHaveBeenCalledWith({ name: 'auth_failed', params: {} });
  });

  it('retry() after a timeout-triggered error starts a fresh timeout that can also fire', async () => {
    vi.useFakeTimers();
    mockSignInAnonymously.mockReturnValueOnce(new Promise(() => { /* never settles */ }));
    const { result } = renderHook(() => useAnonAuth());

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current.authState).toBe('error');

    trackEventMock.mockClear();
    mockSignInAnonymously.mockReturnValueOnce(new Promise(() => { /* never settles, again */ }));
    act(() => result.current.retry());
    expect(result.current.authState).toBe('pending');

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current.authState).toBe('error');
    expect(trackEventMock).toHaveBeenCalledWith({ name: 'auth_failed', params: {} });
  });

  it('clears the timeout on unmount, so no late state update fires after the component is gone', async () => {
    vi.useFakeTimers();
    mockSignInAnonymously.mockReturnValue(new Promise(() => { /* never settles */ }));
    const { unmount } = renderHook(() => useAnonAuth());
    unmount();

    await expect(act(async () => { await vi.advanceTimersByTimeAsync(10_000); })).resolves.not.toThrow();
    expect(trackEventMock).not.toHaveBeenCalledWith({ name: 'auth_failed', params: {} });
  });
});
