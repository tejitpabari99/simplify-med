export const ALLOWED_UPLOAD_EXTENSIONS = [
  'pdf', 'txt', 'docx', 'html', 'htm', 'png', 'jpg', 'jpeg', 'webp', 'heic',
];
export const MAX_FILES = 5;
// Mirrors the backend's upload limits (5 files / 10MB aggregate / no per-file
// cap) -- keep these two values in sync. There is deliberately no per-file
// cap: only the combined size across all selected files matters.
export const MAX_AGGREGATE_BYTES = 10 * 1024 * 1024;
// Mirrors backend Constants.Uploads.MAX_TEXT_LENGTH (backend/utils/constants.py) --
// keep these two values in sync.
export const MAX_TEXT_LENGTH = 500_000;
// Mirrors backend Constants.Uploads.MAX_TEXT_BYTES (backend/utils/constants.py) --
// keep these two values in sync. This is a UTF-8-encoded *byte* budget, checked
// alongside (not instead of) the character-based MAX_TEXT_LENGTH above: non-ASCII
// text (CJK, Arabic, emoji, ...) can be well under the character cap while still
// being well over this byte cap, since those characters take more than one UTF-8
// byte each.
export const MAX_TEXT_BYTES = 350_000;
// A UTF-16 code unit encodes to at most 3 UTF-8 bytes, so the byte cap can only be
// exceeded once the character count passes MAX_TEXT_BYTES / 3 -- below that, we can
// skip the more expensive UTF-8 encode. Keeps validateText() cheap on every keystroke.
const MAX_TEXT_BYTES_CHECK_THRESHOLD = Math.floor(MAX_TEXT_BYTES / 3);

/** Formats a byte count as a short human-readable string, e.g. `1.4 MB`, `320 KB`, `0 B`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const formatted = value >= 10 ? Math.round(value).toString() : value.toFixed(1);
  return `${formatted} ${units[unitIndex]}`;
}

export function validateFiles(selected: File[]): string | null {
  if (selected.length === 0) return null;
  if (selected.length > MAX_FILES) {
    return `You can upload up to ${MAX_FILES} files at a time (selected ${selected.length}).`;
  }
  const invalidExt = selected.filter(f => {
    const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
    return !ALLOWED_UPLOAD_EXTENSIONS.includes(ext);
  });
  if (invalidExt.length > 0) {
    return `Unsupported file type: ${invalidExt.map(f => f.name).join(', ')}. ` +
      'Use PDF, TXT, DOCX, HTML, or an image (PNG/JPG/WEBP/HEIC).';
  }
  const totalBytes = selected.reduce((sum, f) => sum + f.size, 0);
  if (totalBytes > MAX_AGGREGATE_BYTES) {
    return `Combined file size is too large (max ${formatBytes(MAX_AGGREGATE_BYTES)} total). Remove a file and try again.`;
  }
  return null;
}

export function validateText(text: string): string | null {
  if (text.length > MAX_TEXT_LENGTH) {
    return `Pasted text is too long (max ${MAX_TEXT_LENGTH.toLocaleString()} characters, ` +
      `got ${text.length.toLocaleString()}). Try shortening it or uploading a file instead.`;
  }
  // Cheap pre-check (see MAX_TEXT_BYTES_CHECK_THRESHOLD above) before paying for a
  // full UTF-8 encode of a possibly very large string.
  if (text.length > MAX_TEXT_BYTES_CHECK_THRESHOLD) {
    const byteLength = new TextEncoder().encode(text).length;
    if (byteLength > MAX_TEXT_BYTES) {
      // Deliberately doesn't mention bytes/UTF-8, and deliberately doesn't blame
      // "some languages" or emoji: MAX_TEXT_BYTES is below MAX_TEXT_LENGTH, so this
      // can also trip for plain ASCII text (e.g. ~400,000 ordinary characters) that
      // never used any non-ASCII characters at all -- attributing the cause to the
      // user's language would be wrong in that case. This message stays true (and
      // non-technical) regardless of which case caused it.
      return 'This text is too long to process. Try shortening it or uploading a file instead.';
    }
  }
  return null;
}
