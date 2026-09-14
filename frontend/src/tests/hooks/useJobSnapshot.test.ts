import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mockUnsubscribe = vi.fn();
const mockOnSnapshot = vi.fn();
const mockDoc = vi.fn();

vi.mock('firebase/firestore', () => ({
  doc: (...args: unknown[]) => mockDoc(...args),
  onSnapshot: (ref: unknown, successCb: (snap: unknown) => void, errorCb: (err: Error) => void) => {
    mockOnSnapshot(ref, successCb, errorCb);
    return mockUnsubscribe;
  },
}));
vi.mock('../../api/firebase', () => ({ firebaseDb: {} }));

import { useJobSnapshot } from '../../hooks/useJobSnapshot';

describe('useJobSnapshot', () => {
  beforeEach(() => {
    mockUnsubscribe.mockClear();
    mockOnSnapshot.mockClear();
    mockDoc.mockClear();
  });

  it('starts loading=true, jobDoc=null, exists=null when a jobId is provided', () => {
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    expect(result.current.loading).toBe(true);
    expect(result.current.jobDoc).toBeNull();
    expect(result.current.exists).toBeNull();
  });

  it('populates jobDoc and sets exists=true on snapshot, defaulting missing fields', () => {
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    const successCb = mockOnSnapshot.mock.calls[0][1];
    act(() => successCb({
      exists: () => true,
      data: () => ({ status: 'processing', stage: 2 }),
    }));
    expect(result.current.jobDoc).toEqual({
      status: 'processing', stage: 2, output_data: null, error_data: null, name: '',
    });
    expect(result.current.exists).toBe(true);
    expect(result.current.loading).toBe(false);
  });

  it('passes known terminal statuses through unchanged, preserving error_data', () => {
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    const successCb = mockOnSnapshot.mock.calls[0][1];
    act(() => successCb({
      exists: () => true,
      data: () => ({ status: 'error', stage: 3, error_data: { code: 'INTERNAL_ERROR', message: 'boom' } }),
    }));
    expect(result.current.jobDoc).toEqual({
      status: 'error', stage: 3, output_data: null,
      error_data: { code: 'INTERNAL_ERROR', message: 'boom' }, name: '',
    });
  });

  // Owner requirement: the user must never be left stuck on the spinner. If the
  // backend ever writes a status this frontend doesn't recognize (a future
  // status value, a bug, a partial/corrupt write), the hook must not pass it
  // through as-is -- callers key their "are we done" routing off this value,
  // and an unrecognized one would never match their known-terminal checks,
  // leaving the user on ProcessingScreen until the 6-minute watchdog. Normalize
  // to 'error' instead so the existing terminal-error UI takes over immediately.
  it('normalizes an unrecognized status to "error", drops any error_data, and logs the raw value', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    const successCb = mockOnSnapshot.mock.calls[0][1];
    act(() => successCb({
      exists: () => true,
      data: () => ({
        status: 'some_future_status',
        stage: 3,
        error_data: { code: 'INTERNAL_ERROR', message: 'internal detail that must not reach the user' },
      }),
    }));
    expect(result.current.jobDoc).toEqual({
      status: 'error', stage: 3, output_data: null, error_data: null, name: '',
    });
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      expect.stringContaining('unrecognized job status'),
      'some_future_status',
    );
    consoleErrorSpy.mockRestore();
  });

  it('sets jobDoc=null and exists=false when the snapshot reports the doc missing', () => {
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    const successCb = mockOnSnapshot.mock.calls[0][1];
    act(() => successCb({ exists: () => false }));
    expect(result.current.jobDoc).toBeNull();
    expect(result.current.exists).toBe(false);
    expect(result.current.loading).toBe(false);
  });

  it('sets error and loading=false on the snapshot error callback, without confirming exists=false', () => {
    const { result } = renderHook(() => useJobSnapshot('job-1'));
    const errorCb = mockOnSnapshot.mock.calls[0][2];
    const err = new Error('permission-denied');
    act(() => errorCb(err));
    expect(result.current.error).toBe(err);
    expect(result.current.loading).toBe(false);
    // A connection/permission error is NOT the same as a confirmed-missing
    // doc — exists must stay null (unknown), not flip to false.
    expect(result.current.exists).toBeNull();
  });

  it('clears jobDoc/error/exists and sets loading=false when jobId is null', () => {
    const { result, rerender } = renderHook(({ id }) => useJobSnapshot(id), { initialProps: { id: 'job-1' as string | null } });
    rerender({ id: null });
    expect(result.current.jobDoc).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.exists).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it('unsubscribes on unmount and on jobId change', () => {
    const { unmount, rerender } = renderHook(({ id }) => useJobSnapshot(id), { initialProps: { id: 'job-1' } });
    rerender({ id: 'job-2' });
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    unmount();
    expect(mockUnsubscribe).toHaveBeenCalledTimes(2);
  });
});
