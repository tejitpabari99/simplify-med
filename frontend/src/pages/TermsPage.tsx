import { Link } from 'react-router-dom';

export default function TermsPage() {
  return (
    <div className="legal-page">
      <Link to="/">← Back to Simplify</Link>
      <article>
        <h1>Terms & Conditions — Simplify</h1>
        <p>Last updated: September 4, 2026</p>

        <p>By using this tool, you agree to the following terms.</p>

        <h2>1. What this is</h2>
        <p>
          This is a free, public demonstration of Simplify's care-plan simplification technology
          ("the Service"). It is provided for evaluation and demonstration purposes only.
        </p>

        <h2>2. No medical advice</h2>
        <p>
          The Service uses an AI model to rewrite and score care-plan text. It is <strong>not
          medical advice</strong>, is <strong>not a substitute for professional clinical
          judgment</strong>, and must not be relied upon for any medical, treatment, or
          health-related decision. Always consult a qualified healthcare professional.
        </p>

        <h2>3. No real patient data</h2>
        <p>
          You agree not to upload or submit any real, identifiable patient health
          information. Use sample, redacted, or fictional content only. You are solely
          responsible for the content you submit.
        </p>

        <h2>4. Provided "as is," no warranty</h2>
        <p>
          The Service is provided <strong>"as is" and "as available,"</strong> without
          warranties of any kind, express or implied, including but not limited to accuracy,
          reliability, availability, merchantability, or fitness for a particular purpose.
          We do not guarantee the Service will be uninterrupted, error-free, or available at
          any given time, and it may be changed, suspended, or withdrawn at any time without
          notice.
        </p>

        <h2>5. No reliance for clinical decisions</h2>
        <p>
          Any output produced by the Service — including simplified text, readability
          scores, and downloaded reports — is generated automatically and may be incomplete,
          inaccurate, or out of date. You agree not to rely on any output of this Service for
          a clinical, treatment, insurance, or legal decision.
        </p>

        <h2>6. Acceptable use</h2>
        <p>You agree not to:</p>
        <ul>
          <li>
            Use the Service for any unlawful purpose, or to submit content you do not have
            the right to submit.
          </li>
          <li>Attempt to disrupt, overload, or circumvent the Service's rate limits or security controls.</li>
          <li>Use automated tools to submit requests at a volume beyond normal individual use.</li>
          <li>
            Attempt to reverse-engineer, scrape, or extract the underlying model, prompts, or
            infrastructure.
          </li>
        </ul>
        <p>We may block or rate-limit any use that we believe violates these terms.</p>

        <h2>7. Rate limits</h2>
        <p>
          To keep the Service free and available to everyone, submissions are limited per
          visitor (currently 5 per hour, subject to change without notice).
        </p>

        <h2>8. Limitation of liability</h2>
        <p>
          To the fullest extent permitted by law, we are not liable for any direct,
          indirect, incidental, consequential, or special damages arising from your use of,
          or inability to use, the Service, including any damages resulting from reliance on
          its output.
        </p>

        <h2>9. Right to withdraw the Service</h2>
        <p>
          We may modify, suspend, or discontinue the Service, in whole or in part, at any
          time and without notice or liability.
        </p>

        <h2>10. Changes to these terms</h2>
        <p>
          We may update these terms as the Service evolves. Continued use of the Service
          after a change constitutes acceptance of the updated terms.
        </p>

        <h2>11. Contact</h2>
        <p>Questions about these terms can be directed to tejitpabari99@gmail.com.</p>
      </article>
    </div>
  );
}
