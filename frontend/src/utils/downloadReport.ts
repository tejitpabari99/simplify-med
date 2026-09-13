import { buildPdfHtml } from './buildPdfHtml';
import type { SimplifiedCarePlan, Grading } from '../types/envelope';
import { trackEvent } from '../analytics/ga';

export function downloadReport(carePlan: SimplifiedCarePlan, grading: Grading): void {
  trackEvent({ name: 'report_downloaded', params: {} });
  const html = buildPdfHtml(carePlan, grading, {
    includeGlossary: true,
    includeReadability: true,
    includeLowPriority: true,
  });
  const printWindow = window.open('', '_blank');
  if (!printWindow) {
    alert('Pop-up blocked. Please allow pop-ups to download the report.');
    return;
  }
  // Can't pass 'noopener' (need the handle for document.write), so null out
  // window.opener manually -- otherwise injected markup in `html` could reach
  // back into this tab via window.opener.
  printWindow.opener = null;
  printWindow.document.write(html);
  printWindow.document.close();
  setTimeout(() => printWindow.print(), 500);
}
