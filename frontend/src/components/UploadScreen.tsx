import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import type { AuthState } from '../hooks/useAnonAuth';
import { createJob } from '../api/api';
import {
  validateFiles,
  validateText,
  MAX_FILES,
  MAX_AGGREGATE_BYTES,
  formatBytes,
} from '../utils/validateFiles';
import { trackEvent } from '../analytics/ga';
import { ApiError } from '../types/errors';

type InputMode = 'file' | 'text';

interface UploadScreenProps {
  authState: AuthState;
  onAuthRetry: () => void;
  onJobCreated: (jobId: string) => void;
}

const ACCEPTED_EXTENSIONS = '.pdf,.txt,.docx,.html,.htm,.png,.jpg,.jpeg,.webp,.heic';

function isSameFile(a: File, b: File): boolean {
  return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
}

function fileExtBadge(name: string): string {
  const ext = name.split('.').pop()?.toUpperCase() ?? '';
  return ext.slice(0, 4) || 'FILE';
}

export default function UploadScreen({ authState, onAuthRetry, onJobCreated }: UploadScreenProps) {
  const [mode, setMode] = useState<InputMode>('file');
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Move focus to this screen's heading on arrival -- this component mounts fresh on
  // initial load and every time "Start over"/"Try again" returns here.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  function selectMode(next: InputMode) {
    setMode(next);
    setError(null);
    trackEvent({ name: 'input_mode_selected', params: { mode: next } });
  }

  function handleFilesSelected(selected: File[]) {
    const deduped = selected.filter(incoming => !files.some(existing => isSameFile(existing, incoming)));
    if (deduped.length === 0) return;
    const combined = [...files, ...deduped];
    const validationError = validateFiles(combined);
    setError(validationError);
    if (validationError) return;
    setFiles(combined);
    const fileTypes = [...new Set(combined.map(f => f.name.split('.').pop()?.toLowerCase() ?? ''))].sort().join(',');
    trackEvent({ name: 'files_selected', params: { file_count: combined.length, file_types: fileTypes } });
  }

  function handleInputChange(e: ChangeEvent<HTMLInputElement>) {
    handleFilesSelected(Array.from(e.target.files ?? []));
    e.target.value = '';
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    handleFilesSelected(Array.from(e.dataTransfer.files ?? []));
  }

  function removeFile(index: number) {
    setFiles(prev => prev.filter((_, i) => i !== index));
    setError(null);
  }

  function handleTextChange(value: string) {
    setText(value);
    setError(validateText(value));
  }

  const hasValidInput = mode === 'file' ? files.length > 0 && !error : text.trim().length > 0 && !error;
  const disabled = authState !== 'ready' || !hasValidInput || submitting;
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);

  async function handleSubmit() {
    // Defense in depth: the Simplify button is already disabled while auth isn't ready
    // (see `disabled` above), but guard here too so a submit can never fire while the
    // anonymous session is still starting up.
    if (authState !== 'ready') return;
    trackEvent({ name: 'simplify_clicked', params: { input_mode: mode, file_count: mode === 'file' ? files.length : 0 } });
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      if (mode === 'file') {
        files.forEach(f => formData.append('files', f));
      } else {
        formData.append('text', text);
      }
      const { job_id } = await createJob(formData);
      trackEvent({ name: 'simplify_submit_success', params: {} });
      onJobCreated(job_id);
    } catch (err) {
      let errorCode = 'NETWORK_ERROR';
      let message = 'Something went wrong. Please try again.';
      if (err instanceof ApiError) {
        errorCode = err.code;
        message = err.userHint ?? err.message;
      } else if (err instanceof Error) {
        message = err.message;
      }
      trackEvent({ name: 'simplify_submit_error', params: { error_code: errorCode, http_status: null } });
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <header style={{ textAlign: 'center' }}>
        <h1 ref={headingRef} tabIndex={-1}>Simplify</h1>
        <p>Turn your care plan into plain language</p>
      </header>

      {authState === 'error' && (
        <div className="error-box">
          Couldn&apos;t start your session.{' '}
          <button onClick={onAuthRetry}>Retry</button>
        </div>
      )}

      {authState === 'pending' && (
        <div className="auth-pending-hint" role="status">
          Getting ready…
        </div>
      )}

      <div className="input-tabs">
        <button
          type="button"
          className={`input-tab ${mode === 'file' ? 'active' : ''}`}
          onClick={() => selectMode('file')}
        >
          Upload files
        </button>
        <button
          type="button"
          className={`input-tab ${mode === 'text' ? 'active' : ''}`}
          onClick={() => selectMode('text')}
        >
          Paste text
        </button>
      </div>

      {mode === 'file' ? (
        <div>
          <div
            className={`upload-zone ${dragActive ? 'drag-active' : ''}`}
            onDragOver={e => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_EXTENSIONS}
              className="upload-zone-input"
              aria-hidden="true"
              tabIndex={-1}
              onChange={handleInputChange}
            />
            <button
              type="button"
              className="upload-zone-trigger"
              onClick={() => fileInputRef.current?.click()}
            >
              <span className="upload-icon" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 16V4" />
                  <path d="M7 8l5-5 5 5" />
                  <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
                </svg>
              </span>
              <span className="upload-zone-primary">
                Drag files here or <span className="upload-zone-browse">browse</span>
              </span>
              <span className="upload-zone-secondary">
                PDF, TXT, DOCX, HTML, or an image (PNG/JPG/WEBP/HEIC)
              </span>
              <span className="upload-zone-limits">
                Up to {MAX_FILES} files · {formatBytes(MAX_AGGREGATE_BYTES)} total
              </span>
            </button>
          </div>

          {files.length > 0 && (
            <div className="file-list">
              {files.map((f, i) => (
                <div key={`${f.name}-${f.lastModified}-${i}`} className="file-card">
                  <span className="file-card-icon" aria-hidden="true">{fileExtBadge(f.name)}</span>
                  <span className="file-card-info">
                    <span className="file-card-name" title={f.name}>{f.name}</span>
                    <span className="file-card-size">{formatBytes(f.size)}</span>
                  </span>
                  <button
                    type="button"
                    className="file-card-remove"
                    aria-label={`Remove ${f.name}`}
                    onClick={() => removeFile(i)}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <div className="file-list-footer">
                {files.length} of {MAX_FILES} files · {formatBytes(totalBytes)} of {formatBytes(MAX_AGGREGATE_BYTES)}
              </div>
            </div>
          )}
        </div>
      ) : (
        <textarea
          className="text-input-area"
          value={text}
          onChange={e => handleTextChange(e.target.value)}
          placeholder="Paste your care plan text here…"
        />
      )}

      {error && <div className="error-box">{error}</div>}

      <button className="cta-btn" disabled={disabled} onClick={handleSubmit}>
        {submitting ? 'Starting…' : 'Simplify'}
      </button>
    </div>
  );
}
