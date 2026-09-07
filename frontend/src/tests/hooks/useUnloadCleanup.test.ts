import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const deleteJobMock = vi.fn().mockResolvedValue(undefined);
vi.mock('../../api/api', () => ({ deleteJob: (...a: unknown[]) => deleteJobMock(...a) }));

import { useUnloadCleanup } from '../../hooks/useUnloadCleanup';

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

describe('useUnloadCleanup', () => {
  beforeEach(() => {
    deleteJobMock.mockClear();
    setVisibility('visible');
  });

  it('does NOT call deleteJob when the tab is backgrounded (visibilitychange->hidden) while appState is "processing"', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'processing', deletedRef));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));

    expect(deleteJobMock).not.toHaveBeenCalled();
    expect(deletedRef.current.has('job-1')).toBe(false);
  });

  it('DOES call deleteJob when the tab is backgrounded (visibilitychange->hidden) while appState is "result"', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'result', deletedRef));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));

    expect(deleteJobMock).toHaveBeenCalledWith('job-1');
    expect(deletedRef.current.has('job-1')).toBe(true);
  });

  it('calls deleteJob on pagehide regardless of appState ("processing")', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'processing', deletedRef));

    window.dispatchEvent(new Event('pagehide'));

    expect(deleteJobMock).toHaveBeenCalledWith('job-1');
    expect(deletedRef.current.has('job-1')).toBe(true);
  });

  it('calls deleteJob on pagehide regardless of appState ("result")', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'result', deletedRef));

    window.dispatchEvent(new Event('pagehide'));

    expect(deleteJobMock).toHaveBeenCalledWith('job-1');
    expect(deletedRef.current.has('job-1')).toBe(true);
  });

  it('does nothing while appState is "upload"', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'upload', deletedRef));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('pagehide'));

    expect(deleteJobMock).not.toHaveBeenCalled();
  });

  it('does not double-fire: visibilitychange then pagehide only deletes once', () => {
    const deletedRef = { current: new Set<string>() };
    renderHook(() => useUnloadCleanup('job-1', 'result', deletedRef));

    setVisibility('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('pagehide'));

    expect(deleteJobMock).toHaveBeenCalledTimes(1);
  });
});
