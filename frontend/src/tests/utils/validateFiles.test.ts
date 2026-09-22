import { describe, it, expect } from 'vitest';
import { validateFiles, validateText, formatBytes, MAX_FILES, MAX_TEXT_LENGTH } from '../../utils/validateFiles';

function fakeFile(name: string, sizeBytes: number): File {
  const file = new File([''], name);
  Object.defineProperty(file, 'size', { value: sizeBytes });
  return file;
}

describe('validateFiles', () => {
  it('accepts a valid mixed selection under both caps', () => {
    expect(validateFiles([fakeFile('a.pdf', 1000), fakeFile('b.png', 2000)])).toBeNull();
  });

  it('returns null for an empty selection', () => {
    expect(validateFiles([])).toBeNull();
  });

  it('rejects more than MAX_FILES with the exact count', () => {
    const files = Array.from({ length: MAX_FILES + 1 }, (_, i) => fakeFile(`f${i}.pdf`, 100));
    const err = validateFiles(files);
    expect(err).toContain(`up to ${MAX_FILES} files`);
    expect(err).toContain(`selected ${MAX_FILES + 1}`);
  });

  it('rejects a disallowed extension, listing the filename', () => {
    const err = validateFiles([fakeFile('animated.gif', 100)]);
    expect(err).toContain('animated.gif');
  });

  it('accepts a single file well over the old 10MB per-file cap, as long as the total is under the aggregate cap', () => {
    // There is no per-file limit any more -- only the combined size matters.
    expect(validateFiles([fakeFile('big.pdf', 9 * 1024 * 1024)])).toBeNull();
  });

  it('rejects a selection whose combined size exceeds the 10MB aggregate cap', () => {
    const files = [fakeFile('a.pdf', 4 * 1024 * 1024), fakeFile('b.pdf', 4 * 1024 * 1024), fakeFile('c.pdf', 4 * 1024 * 1024)];
    const err = validateFiles(files);
    expect(err).toContain('10 MB total');
  });
});

describe('formatBytes', () => {
  it('renders sub-KB sizes in bytes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
  });

  it('renders KB sizes with no decimal once the value is 10 or more', () => {
    expect(formatBytes(320 * 1024)).toBe('320 KB');
  });

  it('renders sub-10 KB/MB values with one decimal place', () => {
    expect(formatBytes(Math.round(1.4 * 1024 * 1024))).toBe('1.4 MB');
  });

  it('formats the exported aggregate limit as a whole megabyte value', () => {
    expect(formatBytes(10 * 1024 * 1024)).toBe('10 MB');
  });
});

describe('validateText', () => {
  it('accepts plain ASCII text comfortably under the character cap', () => {
    expect(validateText('a'.repeat(300_000))).toBeNull();
  });

  it('rejects ASCII text over the character cap with the exact length in the existing message', () => {
    const text = 'a'.repeat(MAX_TEXT_LENGTH + 1);
    const err = validateText(text);
    expect(err).toContain(`${MAX_TEXT_LENGTH + 1}`.replace(/\B(?=(\d{3})+(?!\d))/g, ','));
  });
});
