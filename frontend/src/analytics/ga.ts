const MEASUREMENT_ID = import.meta.env.VITE_GA_MEASUREMENT_ID as string | undefined;

declare global {
  interface Window {
    dataLayer: unknown[];
    gtag: (...args: unknown[]) => void;
  }
}

let initialized = false;

function ensureInitialized(): void {
  if (initialized || !MEASUREMENT_ID) return;
  initialized = true;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag(...args: unknown[]) { window.dataLayer.push(args); };
  window.gtag('js', new Date());
  window.gtag('config', MEASUREMENT_ID, { send_page_view: false });
  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
  document.head.appendChild(script);
}

export type AnalyticsEvent =
  | { name: 'page_view'; params: { page_path: string; page_title: string } }
  | { name: 'input_mode_selected'; params: { mode: 'file' | 'text' } }
  | { name: 'files_selected'; params: { file_count: number; file_types: string } }
  | { name: 'simplify_clicked'; params: { input_mode: 'file' | 'text'; file_count: number } }
  | { name: 'simplify_submit_success'; params: Record<string, never> }
  | { name: 'simplify_submit_error'; params: { error_code: string; http_status: number | null } }
  | { name: 'pipeline_step_start'; params: { step_id: number; step_key: string } }
  | { name: 'pipeline_step_complete'; params: { step_id: number; step_key: string } }
  | { name: 'simplify_complete'; params: { total_duration_ms: number; score_before: number; score_after: number } }
  | { name: 'simplify_pipeline_error'; params: { error_code: string; stage_reached: number | null } }
  | { name: 'report_downloaded'; params: Record<string, never> }
  | { name: 'legal_link_clicked'; params: { link: 'privacy' | 'terms'; source_screen: string } }
  | { name: 'auth_ready'; params: Record<string, never> }
  | { name: 'auth_failed'; params: Record<string, never> };

export function trackEvent(event: AnalyticsEvent): void {
  if (!MEASUREMENT_ID) return;
  ensureInitialized();
  window.gtag('event', event.name, event.params);
}
