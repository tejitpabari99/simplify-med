import { useState, type ReactNode } from 'react';
import type { TermsMap } from '../types/carePlan';
import type { SimplifiedCarePlan } from '../types/envelope';
import { buildNextStepsRows, NEXT_STEPS_TYPE_LABELS } from '../utils/nextSteps';
import MedicalTerm from './MedicalTerm';

function renderTextWithTerms(text: string, terms: TermsMap): ReactNode {
  if (!terms || Object.keys(terms).length === 0) return text;

  // Sort longest-first so that supersets ("hyper multiple sclerosis") beat subsets ("multiple sclerosis")
  // when they start at the same position.
  const sortedTerms = Object.keys(terms).sort((a, b) => b.length - a.length);
  const lowerText = text.toLowerCase();
  const parts: ReactNode[] = [];
  let offset = 0;
  let key = 0;

  while (offset < text.length) {
    // Find the earliest match among all terms; on tie (same start), longest wins (sortedTerms order).
    let bestStart = -1;
    let bestTerm = '';

    for (const term of sortedTerms) {
      const idx = lowerText.indexOf(term.toLowerCase(), offset);
      if (idx === -1) continue;
      if (bestStart === -1 || idx < bestStart) {
        bestStart = idx;
        bestTerm = term;
      }
    }

    if (bestStart === -1) {
      parts.push(<span key={key++}>{text.slice(offset)}</span>);
      break;
    }

    if (bestStart > offset) {
      parts.push(<span key={key++}>{text.slice(offset, bestStart)}</span>);
    }

    const displayTerm = text.slice(bestStart, bestStart + bestTerm.length);
    const glossaryEntry = terms[bestTerm];
    parts.push(
      <MedicalTerm
        key={key++}
        term={displayTerm}
        definition={glossaryEntry.definition}
        imgUrl={glossaryEntry.imgUrl}
        altText={glossaryEntry.altText}
      />,
    );
    offset = bestStart + bestTerm.length;
  }

  return <>{parts}</>;
}

function ResultCard({
  color,
  icon,
  title,
  collapsible = false,
  defaultOpen = true,
  children,
}: {
  color: string;
  icon: string;
  title: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(collapsible ? defaultOpen : true);

  return (
    <div className={`result-card ${color}`}>
      <div
        className="result-card-header"
        onClick={() => collapsible && setOpen(current => !current)}
        style={{ cursor: collapsible ? 'pointer' : 'default' }}
      >
        <span className="result-card-title">
          <span>{icon}</span>
          <span>{title}</span>
        </span>
        {collapsible && <span className={`result-card-toggle ${open ? 'open' : ''}`}>▼</span>}
      </div>
      <div className={`result-card-body ${open ? '' : 'collapsed'}`}>{children}</div>
    </div>
  );
}

export default function CarePlanView({
  result,
}: {
  result: SimplifiedCarePlan;
}) {
  const terms = result.terms ?? {};
  const withTerms = (text: string) => renderTextWithTerms(text, terms);
  // navigator.clipboard can be undefined (old WebViews, non-secure origins) and
  // writeText can reject, so give a brief "Copied"/"Copy failed" affordance either way.
  const [copyStatus, setCopyStatus] = useState<Record<number, 'copied' | 'failed'>>({});
  function handleCopyQuestion(i: number, text: string) {
    const clearAfterDelay = (status: 'copied' | 'failed') => {
      setCopyStatus(prev => ({ ...prev, [i]: status }));
      setTimeout(() => {
        setCopyStatus(prev => {
          if (prev[i] !== status) return prev;
          const next = { ...prev };
          delete next[i];
          return next;
        });
      }, 2000);
    };
    if (!navigator.clipboard) {
      clearAfterDelay('failed');
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => clearAfterDelay('copied'),
      () => clearAfterDelay('failed'),
    );
  }
  const URGENCY_COLORS: Record<string, string> = {
    emergency: '#DC2626',
    call_doctor: '#D97706',
    monitor: '#6B7280',
    normal_side_effect: '#6B7280',
  };
  const URGENCY_LABELS: Record<string, string> = {
    emergency: 'EMERGENCY',
    call_doctor: 'CALL DOCTOR',
    monitor: 'WATCH',
    normal_side_effect: 'NORMAL',
  };
  const URGENCY_ORDER: Record<string, number> = { emergency: 0, call_doctor: 1, monitor: 2, normal_side_effect: 3 };
  const NULL_URGENCY_COLOR = '#9CA3AF'; // lighter than monitor/normal's #6B7280 -- "no info", not "low-priority-but-known"
  const NULL_URGENCY_ORDER = 4;

  return (
    <div className="result-cards">
      {result.summary && (
        <div className="result-card" style={{ background: 'var(--surface-green-muted, #E8EDE3)' }}>
          <div className="result-card-body" style={{ paddingTop: '16px' }}>
            <h2 style={{ fontWeight: 700, fontSize: '1.1rem', marginBottom: '0.5rem' }}>What You Need to Know</h2>
            <p className="summary-paragraph">{withTerms(result.summary)}</p>
          </div>
        </div>
      )}

      {result.reason_for_visit?.length > 0 && (
        <ResultCard color="blue" icon="📅" title="Why You Came In">
          {result.reason_for_visit.map((r, i) => (
            <div key={i} style={{ marginBottom: '8px' }}>
              <strong>{withTerms(r.reason)}</strong>
              {r.description && <p style={{ color: 'var(--text-secondary)', margin: '4px 0 0 0', fontSize: '0.9rem' }}>{withTerms(r.description)}</p>}
            </div>
          ))}
        </ResultCard>
      )}

      {result.diagnosis && result.diagnosis.details?.length > 0 && (
        <ResultCard color="teal" icon="🔍" title="What the Doctor Found">
          {result.diagnosis.changed_since_last_visit && (
            <p style={{ color: '#0F766E', fontSize: '0.875rem', marginBottom: '12px' }}>
              Compared to last visit: {withTerms(result.diagnosis.changed_since_last_visit)}
            </p>
          )}
          {(() => {
            const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
            const sortedDetails = [...(result.diagnosis.details ?? [])].sort(
              (a, b) => (SEVERITY_ORDER[a.severity?.toLowerCase() ?? ''] ?? 99) - (SEVERITY_ORDER[b.severity?.toLowerCase() ?? ''] ?? 99)
            );
            return sortedDetails;
          })().map((det, i) => (
            <div key={i} style={{ paddingLeft: '12px', borderLeft: '4px solid #EF4444', marginBottom: '10px' }}>
              <strong>{withTerms(det.plain_name ? `${det.plain_name} (${det.title})` : det.title)}</strong>
              <p style={{ color: 'var(--text-secondary)', margin: '4px 0', fontSize: '0.9rem' }}>{withTerms(det.description)}</p>
              {det.what_it_means_for_you && (
                <p style={{ color: '#B45309', fontSize: '0.85rem', fontStyle: 'italic', margin: '4px 0 0 0' }}>
                  What this means for you: {withTerms(det.what_it_means_for_you)}
                </p>
              )}
            </div>
          ))}
        </ResultCard>
      )}

      {(() => {
        const rows = buildNextStepsRows(result);
        return rows.length > 0 && (
          <ResultCard color="violet" icon="✅" title="Next Steps">
            {rows.map((row, i) => {
              const isDone = row.status === 'done';
              return (
                <div key={i} className="next-step-row" style={{ marginBottom: '12px' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                    <span aria-hidden="true" className="next-step-checkbox"
                      style={{ color: isDone ? '#059669' : '#9CA3AF', fontSize: '1.1rem' }}>
                      {isDone ? '☑' : '☐'}
                    </span>
                    <span className="sr-only">{isDone ? 'Done: ' : 'To do: '}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
                        <strong style={isDone ? { color: 'var(--text-secondary)', textDecoration: 'line-through' } : undefined}>
                          {withTerms(row.title)}
                        </strong>
                        <span className="next-step-type-label">{NEXT_STEPS_TYPE_LABELS[row.type]}</span>
                      </div>
                      {row.why && <p style={{ color: '#1D4ED8', fontSize: '0.875rem', margin: '4px 0 0 0' }}>Why: {withTerms(row.why)}</p>}
                      {row.detail && <p style={{ color: '#374151', fontSize: '0.875rem', margin: '4px 0 0 0' }}>{withTerms(row.detail)}</p>}
                      {row.change && (
                        <p style={{ color: '#D97706', fontSize: '0.8rem', fontWeight: '700', margin: '4px 0 0 0' }}>
                          Changed: {withTerms(row.change)}
                        </p>
                      )}
                      {(row.steps?.length ?? 0) > 0 && (
                        <ul className="result-list" style={{ marginTop: '4px' }}>
                          {row.steps?.map((step, si) => <li key={si}>{withTerms(step)}</li>)}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </ResultCard>
        );
      })()}

      {result.warning_signs?.length > 0 && (
        <ResultCard color="gray" icon="⚠️" title="What to Watch For">
          {[...result.warning_signs]
            .sort((a, b) => (a.urgency ? URGENCY_ORDER[a.urgency] : NULL_URGENCY_ORDER)
                          - (b.urgency ? URGENCY_ORDER[b.urgency] : NULL_URGENCY_ORDER))
            .map((sign, i) => {
              const color = sign.urgency ? URGENCY_COLORS[sign.urgency] : NULL_URGENCY_COLOR;
              return (
                <div key={i} style={{ borderLeft: `4px solid ${color}`, paddingLeft: '12px', marginBottom: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <strong>{withTerms(sign.symptom)}</strong>
                    {sign.urgency && <span style={{ color, fontSize: '0.75rem', fontWeight: '700' }}>[{URGENCY_LABELS[sign.urgency]}]</span>}
                  </div>
                  {sign.what_it_might_mean && <p style={{ color: '#6B7280', fontSize: '0.875rem', margin: '4px 0' }}>{withTerms(sign.what_it_might_mean)}</p>}
                  <p style={{ color, fontWeight: '500', fontSize: '0.875rem', margin: '4px 0 0 0' }}>{withTerms(sign.what_to_do)}</p>
                </div>
              );
            })}
        </ResultCard>
      )}

      {result.questions?.length > 0 && (
        <ResultCard color="blue" icon="❓" title="Questions to Ask at Your Next Visit">
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '12px' }}>
            These are suggested questions based on what was discussed.
          </p>
          <ul className="result-list">
            {result.questions.map((q, i) => (
              <li key={i} style={{ color: '#0369A1', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <span style={{ flex: 1 }}>{withTerms(q)}</span>
                <button
                  onClick={() => handleCopyQuestion(i, q)}
                  style={{
                    background: 'none',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-pill)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.75rem',
                    padding: '2px 10px',
                    cursor: 'pointer',
                    fontFamily: 'Inter, sans-serif',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  {copyStatus[i] === 'copied' ? 'Copied' : copyStatus[i] === 'failed' ? 'Copy failed' : 'Copy'}
                </button>
              </li>
            ))}
          </ul>
        </ResultCard>
      )}

      {result.low_priority?.length > 0 && (
        <ResultCard color="gray" icon="ℹ️" title="Other Items From Your Visit" collapsible defaultOpen={false}>
          <ul className="result-list">
            {result.low_priority.map((item, i) => <li key={i}>{withTerms(item)}</li>)}
          </ul>
        </ResultCard>
      )}

      {Object.keys(terms).length > 0 && (
        <ResultCard color="gray" icon="📖" title="Medical Terms Glossary" collapsible defaultOpen={false}>
          <div className="glossary-list">
            {Object.entries(terms).map(([term, glossary]) => (
              <div className="glossary-item" key={term}>
                <span className="glossary-term">{term}</span>
                <span className="glossary-def">{glossary.definition}</span>
              </div>
            ))}
          </div>
        </ResultCard>
      )}
    </div>
  );
}
