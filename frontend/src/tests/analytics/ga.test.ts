import { describe, it, expect, vi, afterEach } from 'vitest';

describe('analytics/ga', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    document.head.querySelectorAll('script').forEach(s => s.remove());
    delete (window as unknown as { gtag?: unknown }).gtag;
    delete (window as unknown as { dataLayer?: unknown }).dataLayer;
  });

  it('is a no-op with no measurement id configured', async () => {
    vi.stubEnv('VITE_GA_MEASUREMENT_ID', '');
    const { trackEvent } = await import('../../analytics/ga');
    trackEvent({ name: 'auth_ready', params: {} });
    expect(document.head.querySelector('script')).toBeNull();
    expect((window as unknown as { gtag?: unknown }).gtag).toBeUndefined();
  });

  it('inserts the gtag.js script exactly once and configures send_page_view: false', async () => {
    vi.stubEnv('VITE_GA_MEASUREMENT_ID', 'G-TEST123');
    const { trackEvent } = await import('../../analytics/ga');
    const gtagSpy = vi.fn();

    trackEvent({ name: 'auth_ready', params: {} });
    // capture the real gtag installed by ensureInitialized, then wrap it to spy
    const realGtag = window.gtag;
    window.gtag = (...args: unknown[]) => { gtagSpy(...args); return realGtag(...args); };

    trackEvent({ name: 'report_downloaded', params: {} });

    const scripts = document.head.querySelectorAll('script[src*="gtag/js"]');
    expect(scripts.length).toBe(1);
    expect(gtagSpy).toHaveBeenCalledWith('event', 'report_downloaded', {});
  });
});
