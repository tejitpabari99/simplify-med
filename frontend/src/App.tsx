import { Routes, Route, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import HomePage from './pages/HomePage';
import PrivacyPage from './pages/PrivacyPage';
import TermsPage from './pages/TermsPage';
import ErrorBoundary from './components/ErrorBoundary';
import { trackEvent } from './analytics/ga';

function usePageViewTracking(): void {
  const location = useLocation();
  useEffect(() => {
    trackEvent({ name: 'page_view', params: { page_path: location.pathname, page_title: document.title } });
  }, [location.pathname]);
}

export default function App() {
  usePageViewTracking();
  return (
    // App-root safety net: an uncaught render/effect exception ANYWHERE below
    // must never blank the whole page (there's no other boundary in the
    // tree). onReset reloads rather than just clearing local state, since a
    // crash this high up may leave router/child state unrecoverable any
    // other way.
    <ErrorBoundary title="Something went wrong" onReset={() => window.location.reload()}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </ErrorBoundary>
  );
}
