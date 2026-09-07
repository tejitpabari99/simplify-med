import { Link } from 'react-router-dom';

export default function PrivacyPage() {
  return (
    <div className="legal-page">
      <Link to="/">← Back to Simplify</Link>
      <article>
        <h1>Privacy Policy — Simplify</h1>
        <p>Last updated: September 4, 2026</p>

        <p>
          This page describes how Simplify ("this tool," "the
          Service") handles your information. This is a free, public tool. Please read this
          before uploading anything.
        </p>

        <h2>The short version</h2>
        <ul>
          <li>
            We do not create accounts, and we do not collect your name, email address, or
            any contact information.
          </li>
          <li>
            Documents and text you submit are processed automatically and deleted as soon as
            your browser finishes displaying your results, with an automatic backstop that
            removes anything left behind if that never happens. We do not keep a copy.
          </li>
          <li>
            We use Google Analytics to count visits and understand how the tool is used. We
            do not send any of your document content to Analytics.
          </li>
          <li>
            This is a demonstration tool. It is not a substitute for professional medical
            advice, and it is not a HIPAA-covered service. Do not upload real patient
            information.
          </li>
        </ul>

        <h2>What we process</h2>
        <p>When you upload a file or paste text, it is sent to:</p>
        <ul>
          <li>
            <strong>Google Cloud Vertex AI (Gemini)</strong>, to generate the simplified
            version of your care plan and to score how readable it is.
          </li>
          <li>
            <strong>Google Firebase</strong>, to coordinate the background job that processes
            your submission (a temporary, anonymous session — see "Accounts" below) and to
            briefly store the job's status and result while it runs.
          </li>
        </ul>
        <p>
          These are the only third parties involved in processing your content, and both are
          Google Cloud services operating under Google's standard cloud data-processing
          terms.
        </p>

        <h2>How long we keep your content</h2>
        <p>
          We designed this tool around one rule: <strong>your content should not outlive the
          job that processes it.</strong>
        </p>
        <ul>
          <li>The uploaded file(s) or pasted text are used only to generate your simplified result.</li>
          <li>The underlying file is deleted from our storage as soon as text has been extracted from it.</li>
          <li>
            The job record (including the simplified output) is deleted as soon as your
            browser has finished displaying your results — you don't need to close the tab or
            navigate away for this to happen. As a safety net — in case results are never
            displayed, for example if you close the tab mid-process — an automatic backstop
            still removes it, typically within a day.
          </li>
          <li>
            We do not keep a permanent copy, we do not use your content to train any model,
            and we do not share it with anyone.
          </li>
        </ul>
        <p>
          This means: your content <strong>is</strong> briefly written to a database and
          cloud storage bucket, because that is how the automated processing pipeline works —
          but it is deleted immediately after processing, not retained. We will never say
          "nothing is stored"; we will always say "nothing is kept."
        </p>

        <h2>Accounts</h2>
        <p>
          This tool does not have user accounts. To let the page track your submission's
          progress, we automatically create an <strong>anonymous, temporary Firebase
          identity</strong> in your browser when you load the page. It is not linked to your
          name, email, or any other identifying information, and it does not persist any
          personal data. Anonymous identities that are no longer in use are periodically
          deleted.
        </p>

        <h2>Analytics</h2>
        <p>
          We use <strong>Google Analytics 4</strong> to understand how people use this tool
          — for example, how many people visit, which input method they choose, whether the
          tool succeeds or fails, and how long processing takes. Google Analytics sets
          cookies and collects standard usage data (like your browser type and approximate
          location) in your browser.
        </p>
        <p>
          <strong>We do not send any document content, filenames, or care-plan text to
          Google Analytics.</strong> The events we record are limited to counts, categories,
          and timings (for example, "a PDF was uploaded," "processing took 22 seconds," "the
          report was downloaded") — never the substance of what you uploaded.
        </p>
        <p>
          If you would prefer not to be measured by Google Analytics, you can use a browser
          extension or setting that blocks Google Analytics scripts; the tool will still
          work.
        </p>

        <h2>Do not upload real patient information</h2>
        <p>
          This is a public demo. <strong>Do not upload real, identifiable patient health
          information (PHI)</strong> — use a sample, redacted, or fictional care plan
          instead. This service is not covered by a HIPAA Business Associate Agreement and
          is not intended for real clinical use.
        </p>

        <h2>Not medical advice</h2>
        <p>
          The simplified text and readability score are generated automatically by an AI
          model and may contain errors, omissions, or inaccuracies. <strong>This tool does
          not provide medical advice</strong> and must never be used as the basis for a
          clinical or treatment decision. Always consult a qualified healthcare professional
          about your care.
        </p>

        <h2>Rate limiting</h2>
        <p>
          To keep this free demo available to everyone, submissions are limited per visitor.
          If you are rate-limited, please try again later.
        </p>

        <h2>Changes to this policy</h2>
        <p>
          We may update this policy as the tool evolves. The "Last updated" date at the top
          will reflect the most recent change.
        </p>

        <h2>Contact</h2>
        <p>Questions about Simplify can be directed to tejitpabari99@gmail.com.</p>
      </article>
    </div>
  );
}
