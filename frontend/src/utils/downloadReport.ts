import { buildPdfHtml } from './buildPdfHtml';
import type { SimplifiedCarePlan, Grading } from '../types/envelope';
import { trackEvent } from '../analytics/ga';

/** Thrown by {@link downloadReport} for a failure the caller should show the
 * visitor an inline message for (as opposed to the pop-up-blocked case, which
 * downloadReport already handles itself via `alert`). The message is always
 * pre-written to be safe to show directly -- callers should not need to
 * inspect the cause, only display `.message`. */
export class DownloadReportError extends Error {}

export function downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void {
  trackEvent({ name: 'report_downloaded', params: {} });

  // result/grading's real-world shape is only a TypeScript contract (see
  // ResultScreen's own comment to this effect) -- a partial/malformed payload
  // must produce an inline message, not a silent no-op on the Download button
  // or an unhandled exception from this onClick handler.
  let html: string;
  try {
    html = buildPdfHtml(carePlan, grading, {
      includeGlossary: true,
      includeReadability: true,
      includeLowPriority: true,
    });
  } catch (err) {
    console.error('downloadReport: buildPdfHtml failed', err);
    throw new DownloadReportError("Couldn't prepare your report. Please try again.");
  }

  const printWindow = window.open('', '_blank');
  if (!printWindow) {
    alert('Pop-up blocked. Please allow pop-ups to download the report.');
    return;
  }

  try {
    // Can't pass 'noopener' (need the handle for document.write), so null out
    // window.opener manually -- otherwise injected markup in `html` could reach
    // back into this tab via window.opener.
    printWindow.opener = null;
    printWindow.document.write(html);
    printWindow.document.close();
  } catch (err) {
    console.error('downloadReport: writing the report window failed', err);
    throw new DownloadReportError("Couldn't open your report. Please try again.");
  }

  setTimeout(() => {
    // Best-effort only: the report itself is already visible in printWindow
    // (with its own in-page "Print / Save as PDF" button) by this point, so a
    // print() failure here (e.g. the visitor already closed the tab) is not
    // worth surfacing back to the original screen -- just don't let it become
    // an unhandled exception in a timer callback.
    try {
      printWindow.print();
    } catch (err) {
      console.error('downloadReport: print() failed', err);
    }
  }, 500);
}
