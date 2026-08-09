import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

const STEP_META = {
  schema:            { icon: '🗄️', label: 'Schema Lookup',        color: '#60a5fa' },
  lineage:           { icon: '🔗', label: 'Lineage Fetch',        color: '#a78bfa' },
  glossary:          { icon: '📖', label: 'Glossary Resolution',  color: '#34d399' },
  governance:        { icon: '🏷️', label: 'Tags & Assertions',    color: '#f59e0b' },
  generation:        { icon: '🤖', label: 'LLM Generation',       color: '#c084fc' },
  validation:        { icon: '✅', label: 'Validation',            color: '#10b981' },
  github:            { icon: '🚀', label: 'GitHub PR',            color: '#f97316' },
  datahub_writeback: { icon: '📡', label: 'DataHub Write-Back',   color: '#22d3ee' },
}

export default function ProgressPanel({ steps }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 12 }}>
      <p style={{
        margin: 0, fontSize: 10, fontWeight: 600,
        color: 'var(--text-muted)', textTransform: 'uppercase',
        letterSpacing: '0.1em', paddingBottom: 4,
      }}>
        Generation Pipeline
      </p>
      {steps.map((step, i) => (
        <StepRow key={step.id} step={step} index={i} />
      ))}
    </div>
  )
}

function StepRow({ step, index }) {
  const [expanded, setExpanded] = useState(false)
  const meta = STEP_META[step.id] || {}
  const hasDetails = step.status !== 'pending' && step.data && Object.keys(step.data).length > 0

  const statusColor = {
    pending: 'var(--text-muted)',
    running: '#06b6d4',
    done: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    skipped: 'var(--text-secondary)',
  }[step.status] || 'var(--text-muted)'

  const statusBg = {
    pending: 'transparent',
    running: 'rgba(6,182,212,0.08)',
    done: 'rgba(16,185,129,0.08)',
    warning: 'rgba(245,158,11,0.08)',
    error: 'rgba(239,68,68,0.08)',
    skipped: 'rgba(255,255,255,0.03)',
  }[step.status] || 'transparent'

  return (
    <div
      className="animate-step"
      style={{
        borderRadius: 10,
        border: `1px solid ${step.status !== 'pending' ? 'var(--border)' : 'transparent'}`,
        background: statusBg,
        overflow: 'hidden',
        animationDelay: `${index * 0.04}s`,
        transition: 'all 0.2s ease',
      }}
    >
      <div
        onClick={() => hasDetails && setExpanded(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 10px',
          cursor: hasDetails ? 'pointer' : 'default',
        }}
      >
        {/* Step number / icon */}
        <div style={{
          width: 28, height: 28, borderRadius: 8, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14,
          background: step.status === 'pending' ? 'var(--bg-card)' : `${meta.color}18`,
          border: `1px solid ${step.status === 'pending' ? 'var(--border)' : `${meta.color}40`}`,
        }}>
          {step.status === 'running' ? (
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              border: '2px solid transparent',
              borderTopColor: '#06b6d4',
              animation: 'spin 0.7s linear infinite',
            }} />
          ) : step.status === 'done' || step.status === 'warning' ? (
            <span>{step.status === 'warning' ? '⚠️' : '✓'}</span>
          ) : step.status === 'error' ? (
            <span>✗</span>
          ) : step.status === 'skipped' ? (
            <span style={{ fontSize: 10 }}>—</span>
          ) : (
            <span style={{ fontSize: 12, opacity: 0.4 }}>{index + 1}</span>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 12, fontWeight: 600,
            color: step.status === 'pending' ? 'var(--text-muted)' : 'var(--text-primary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {meta.label}
          </div>
          {step.message && (
            <div style={{
              fontSize: 11, color: statusColor,
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              marginTop: 1,
            }}>
              {step.message}
            </div>
          )}
        </div>

        {hasDetails && (
          <div style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </div>
        )}
      </div>

      {/* Expandable details */}
      {expanded && hasDetails && (
        <div style={{
          padding: '0 10px 10px 48px',
          borderTop: '1px solid var(--border)',
          paddingTop: 8,
        }}>
          <StepDetails stepId={step.id} data={step.data} />
        </div>
      )}
    </div>
  )
}

function StepDetails({ stepId, data }) {
  if (stepId === 'schema' && data.datasets) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.datasets.map(ds => (
          <div key={ds.name} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 11, color: 'var(--text-secondary)',
          }}>
            <span style={{
              padding: '1px 6px', borderRadius: 4,
              background: 'rgba(96,165,250,0.1)',
              color: '#60a5fa', fontSize: 10, fontWeight: 600,
              fontFamily: 'JetBrains Mono, monospace',
            }}>
              {ds.platform}
            </span>
            <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{ds.name}</span>
            <span style={{ color: 'var(--text-muted)' }}>{ds.fieldCount} cols</span>
            {ds.freshness === 'stale' && (
              <span style={{ color: '#f59e0b', fontSize: 10 }}>⚠ stale</span>
            )}
          </div>
        ))}
      </div>
    )
  }

  if (stepId === 'lineage' && data.edges) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {data.edges.map((e, i) => (
          <div key={i} style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'JetBrains Mono, monospace' }}>
            <span style={{ color: '#7c3aed' }}>{e.upstream}</span>
            <span style={{ color: 'var(--text-muted)', margin: '0 6px' }}>→</span>
            <span style={{ color: '#2563eb' }}>{e.downstream}</span>
          </div>
        ))}
      </div>
    )
  }

  if (stepId === 'glossary' && data.terms) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.terms.length === 0 && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>No business terms found in request</span>
        )}
        {data.terms.map(t => (
          <div key={t.name}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#34d399' }}>{t.name}</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2, lineHeight: 1.4 }}>{t.definition}</div>
          </div>
        ))}
      </div>
    )
  }

  if (stepId === 'governance') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.piiColumns?.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#f59e0b', marginBottom: 3 }}>
              ⚠ PII Columns ({data.piiColumns.length})
            </div>
            {data.piiColumns.slice(0, 4).map((c, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                {c.dataset}.<span style={{ color: '#ef4444' }}>{c.column}</span>
                <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>[{c.tags.join(', ')}]</span>
              </div>
            ))}
          </div>
        )}
        {data.assertionWarnings?.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#ef4444', marginBottom: 3 }}>
              ✗ Failing Assertions ({data.assertionWarnings.length})
            </div>
            {data.assertionWarnings.map((w, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {w.dataset} — {w.type} on {w.column || 'table'}
              </div>
            ))}
          </div>
        )}
        {!data.piiColumns?.length && !data.assertionWarnings?.length && (
          <span style={{ fontSize: 11, color: '#10b981' }}>✓ No PII or failing assertions found</span>
        )}
      </div>
    )
  }

  if (stepId === 'generation' && data.reasoning) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
        <strong style={{ color: 'var(--text-primary)' }}>Model:</strong>{' '}
        <code style={{ color: '#c084fc' }}>{data.modelName}</code>
        <div style={{ marginTop: 4 }}>{data.reasoning}</div>
      </div>
    )
  }

  if (stepId === 'validation') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {data.valid
          ? <span style={{ fontSize: 11, color: '#10b981' }}>✓ All identifiers validated against DataHub schema</span>
          : <span style={{ fontSize: 11, color: '#f59e0b' }}>⚠ Validation completed with warnings</span>
        }
        {data.warnings?.map((w, i) => (
          <div key={i} style={{ fontSize: 11, color: '#f59e0b' }}>{w}</div>
        ))}
      </div>
    )
  }

  if (stepId === 'datahub_writeback') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.urn && (
          <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
            <span style={{ color: 'var(--text-muted)', marginRight: 6 }}>URN</span>
            <code style={{
              color: '#22d3ee', fontSize: 10,
              fontFamily: 'JetBrains Mono, monospace',
              wordBreak: 'break-all',
            }}>
              {data.urn}
            </code>
          </div>
        )}
        {data.lineageEdges?.length > 0 && (
          <div style={{ fontSize: 11, color: '#a78bfa' }}>
            🔗 Added {data.lineageEdges.length} lineage edge(s):{' '}
            {data.lineageEdges.map(e => e.upstream).join(', ')}
          </div>
        )}
      </div>
    )
  }

  return null
}
