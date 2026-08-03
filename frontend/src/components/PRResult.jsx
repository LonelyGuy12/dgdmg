import { ExternalLink, AlertTriangle, CheckCircle, Info, GitPullRequest, XCircle } from 'lucide-react'

export default function PRResult({ result }) {
  if (!result) return null

  const { pr, files, piiWarnings = [], assertionWarnings = [], skipped, reason } = result
  const hasPII = piiWarnings.length > 0
  const hasAssertionWarnings = assertionWarnings.length > 0

  return (
    <div style={{
      flexShrink: 0,
      borderTop: '1px solid var(--border)',
      padding: '12px 16px',
      background: 'rgba(7,8,16,0.8)',
      backdropFilter: 'blur(20px)',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        {/* PR link or skipped message */}
        {skipped ? (
          <div style={{
            flex: '0 0 auto',
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 14px', borderRadius: 9,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--border)',
          }}>
            <Info size={14} style={{ color: 'var(--text-muted)' }} />
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
                PR Creation Skipped
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
                {reason || 'Set GITHUB_TOKEN + GITHUB_REPO in .env to enable'}
              </div>
            </div>
          </div>
        ) : pr && (
          <a
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              flex: '0 0 auto',
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 14px', borderRadius: 9,
              background: 'rgba(16,185,129,0.1)',
              border: '1px solid rgba(16,185,129,0.25)',
              color: '#10b981',
              textDecoration: 'none',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'rgba(16,185,129,0.18)'
              e.currentTarget.style.borderColor = 'rgba(16,185,129,0.4)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'rgba(16,185,129,0.1)'
              e.currentTarget.style.borderColor = 'rgba(16,185,129,0.25)'
            }}
          >
            <GitPullRequest size={14} />
            <div>
              <div style={{ fontSize: 12, fontWeight: 700 }}>
                PR #{pr.number} Created ✓
              </div>
              <div style={{ fontSize: 11, color: '#6ee7b7', marginTop: 1, maxWidth: 220,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {pr.title}
              </div>
            </div>
            <ExternalLink size={11} style={{ marginLeft: 4, opacity: 0.7 }} />
          </a>
        )}

        {/* Files committed */}
        {files && (
          <div style={{
            flex: '0 0 auto',
            padding: '8px 12px', borderRadius: 9,
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
              FILES
            </div>
            {[
              typeof files.sql === 'string' ? files.sql : files.sql?.path,
              typeof files.yaml === 'string' ? files.yaml : files.yaml?.path,
            ].filter(Boolean).map(path => (
              <div key={path} style={{
                fontSize: 11, color: 'var(--text-secondary)',
                fontFamily: 'JetBrains Mono, monospace',
                marginBottom: 2,
              }}>
                📄 {path}
              </div>
            ))}
          </div>
        )}

        {/* Warnings */}
        {hasPII && (
          <WarningBadge
            icon={<AlertTriangle size={13} />}
            color="#f59e0b"
            label={`${piiWarnings.length} PII column${piiWarnings.length > 1 ? 's' : ''} — noted in PR`}
            tooltip={piiWarnings.slice(0, 3).map(w => `${w.dataset}.${w.column}`).join(', ')}
          />
        )}

        {hasAssertionWarnings && (
          <WarningBadge
            icon={<XCircle size={13} />}
            color="#ef4444"
            label={`${assertionWarnings.length} failing assertion${assertionWarnings.length > 1 ? 's' : ''} — noted in PR`}
            tooltip={assertionWarnings.map(w => `${w.dataset}: ${w.type}`).join(', ')}
          />
        )}

        {!hasPII && !hasAssertionWarnings && (
          <div style={{
            flex: '0 0 auto',
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, color: '#10b981',
            padding: '8px 12px', borderRadius: 9,
            background: 'rgba(16,185,129,0.06)',
            border: '1px solid rgba(16,185,129,0.15)',
          }}>
            <CheckCircle size={12} />
            No PII or quality issues
          </div>
        )}
      </div>
    </div>
  )
}

function WarningBadge({ icon, color, label, tooltip }) {
  return (
    <div
      title={tooltip}
      style={{
        flex: '0 0 auto',
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '8px 12px', borderRadius: 9,
        background: `${color}12`,
        border: `1px solid ${color}30`,
        color,
        fontSize: 11, fontWeight: 500,
        cursor: 'help',
      }}
    >
      {icon}
      {label}
    </div>
  )
}
