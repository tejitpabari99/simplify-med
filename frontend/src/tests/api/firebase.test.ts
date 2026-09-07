import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Real Firebase SDK calls (initializeApp/getAuth/getFirestore) are irrelevant
// to what this file tests -- the VITE_API_PROCESSING_URL guard -- and would
// otherwise require a real config. Stub them out so only firebase.ts's own
// module-load logic runs.
vi.mock('firebase/app', () => ({ initializeApp: vi.fn(() => ({})) }));
vi.mock('firebase/auth', () => ({ getAuth: vi.fn(() => ({})) }));
vi.mock('firebase/firestore', () => ({ getFirestore: vi.fn(() => ({})) }));

describe('firebase.ts API_URL guard', () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('throws a clear, loud error at module load when VITE_API_PROCESSING_URL is unset', async () => {
    vi.stubEnv('VITE_API_PROCESSING_URL', '');
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    await expect(import('../../api/firebase')).rejects.toThrow(/VITE_API_PROCESSING_URL/);
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining('VITE_API_PROCESSING_URL'));

    consoleErrorSpy.mockRestore();
  });

  it('strips a trailing slash so `${API_URL}/jobs` never doubles up', async () => {
    vi.stubEnv('VITE_API_PROCESSING_URL', 'https://host.example.com/');
    const mod = await import('../../api/firebase');
    expect(mod.API_URL).toBe('https://host.example.com');
  });

  it('leaves a clean URL (no trailing slash) unchanged', async () => {
    vi.stubEnv('VITE_API_PROCESSING_URL', 'https://host.example.com');
    const mod = await import('../../api/firebase');
    expect(mod.API_URL).toBe('https://host.example.com');
  });
});
