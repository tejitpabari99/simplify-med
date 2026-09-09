import { Link } from 'react-router-dom';

export default function PrivacyPage() {
  return (
    <div className="legal-page">
      <Link to="/" className="back-button">
        <span className="back-button-arrow" aria-hidden="true">←</span>
        <span>Back to Simplify</span>
      </Link>
      <article>
        <h1>Privacy Policy for Simplify</h1>
        <p>Last updated: September 4, 2026</p>

        <p>
          This page explains how Simplify ("the Service") handles your information.
          Simplify is a free, public tool. Please read this before uploading anything.
        </p>

        <h2>The short version</h2>
        <ul>
          <li>
            We don't create accounts or collect your name, email, or any other contact
            information.
          </li>
          <li>
            Documents and text you submit are processed automatically and deleted as soon
            as your results are shown, with an automatic backstop if that never happens.
            We don't keep a copy.
          </li>
          <li>
            We use Google Analytics to count visits and understand how the tool is used.
            We don't send document content to Analytics.
          </li>
          <li>
            This is a demonstration tool. It's not a substitute for professional medical
            advice.
          </li>
        </ul>

        <h2>What we process</h2>
        <p>When you upload a file or paste text, it is sent to:</p>
        <ul>
          <li>
            <strong>Google Cloud Vertex AI (Gemini)</strong>, to generate your simplified
            care plan and score its readability.
          </li>
          <li>
            <strong>Google Firebase</strong>, to coordinate the background job that
            processes your submission and briefly store its status and result while it
            runs.
          </li>
        </ul>
        <p>
          These are the only third parties involved in processing your content. Both are
          Google Cloud services operating under Google's standard cloud data-processing
          terms.
        </p>

        <h2>How long we keep your content</h2>
        <p>
          Your content doesn't outlive the job that processes it. Uploaded files are
          deleted from storage as soon as text has been extracted, and the job record,
          including the simplified output, is deleted as soon as your browser finishes
          displaying your results (you don't need to close the tab for this to happen). If
          results are never displayed, for example if you close the tab mid-process, an
          automatic backstop removes the record anyway, typically within a day. We don't
          keep a permanent copy, use your content to train any model, or share it with
          anyone.
        </p>

        <h2>Analytics</h2>
        <p>
          We use <strong>Google Analytics</strong> to understand how people use this tool:
          how many people visit, which input method they choose, whether the tool succeeds
          or fails, and how long processing takes. Google Analytics sets cookies and
          collects standard usage data, such as browser type and approximate location.
        </p>
        <p>
          <strong>We never send document content, filenames, or care-plan text to Google
          Analytics.</strong> The events we record are limited to counts, categories, and
          timings (for example, "a PDF was uploaded," "processing took 22 seconds," "the
          report was downloaded"), never the substance of what you uploaded.
        </p>

        <h2>Not medical advice</h2>
        <p>
          The simplified text and readability score are generated automatically by an AI
          model and may contain errors or omissions. <strong>This tool does not provide
          medical advice</strong> and must never be used as the basis for a clinical or
          treatment decision. Always consult a qualified healthcare professional about your
          care.
        </p>

        <h2>Rate limiting</h2>
        <p>
          To keep this free demo available to everyone, we limit submissions per visitor.
          If you're rate-limited, please try again later.
        </p>

        <h2>Changes to this policy</h2>
        <p>
          We may update this policy as the tool evolves. The "Last updated" date above
          reflects the most recent change.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about Simplify can be directed to{' '}
          <a href="mailto:tejitpabari99@gmail.com">tejitpabari99@gmail.com</a>.
        </p>
      </article>
    </div>
  );
}
