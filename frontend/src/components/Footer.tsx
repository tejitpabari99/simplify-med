import { Link, useLocation } from 'react-router-dom';
import { trackEvent } from '../analytics/ga';

export default function Footer() {
  const location = useLocation();
  return (
    <footer className="app-footer">
      <p>No documents are saved — content is deleted immediately after processing.</p>
      <p>This is a demo, not medical advice.</p>
      <p>
        <Link
          to="/privacy"
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => trackEvent({ name: 'legal_link_clicked', params: { link: 'privacy', source_screen: location.pathname } })}
        >
          Privacy Policy
        </Link>
        {' · '}
        <Link
          to="/terms"
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => trackEvent({ name: 'legal_link_clicked', params: { link: 'terms', source_screen: location.pathname } })}
        >
          Terms & Conditions
        </Link>
      </p>
    </footer>
  );
}
