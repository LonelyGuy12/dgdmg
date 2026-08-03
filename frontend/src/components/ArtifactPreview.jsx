import { useState, useCallback } from 'react'
import { Copy, Check, Database, GitBranch, ChevronDown, ChevronRight } from 'lucide-react'

export default function ArtifactPreview({ sql, yaml, modelName, request, steps }) {
  const [activeTab, setActiveTab] = useState('sql')
  const [copied, setCopied] = useState(false)
  const [contextExpanded, setContextExpanded] = useState(false)

  const content = activeTab === 'sql' ? sql : yaml

  const handleCopy = useCallback(async () => {
    if (!content) return
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [content])

  const schemaStep = steps.find(s => s.id === 'schema')
  const lineageStep = steps.find(s => s.id === 'lineage')
  const glossaryStep = steps.find(s => s.id === 'glossary')
  const govStep = steps.find(s => s.id === 'governance')

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      overflow: 'hidden', padding: '12px 16px 0',
    }}>
      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        marginBottom: 10, flexShrink: 0,
      }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {['sql', 'yaml'].map(tab => (
            <button
              key={tab}
              className={`tab-pill ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab === 'sql' ? '📄 .sql' : '📋 schema.yml'}
            </button>
          ))}
        </div>

        {modelName && (
          <span style={{
            fontSize: 12, fontWeight: 600, color: '#c084fc',
            fontFamily: 'JetBrains Mono, monospace',
            background: 'rgba(192,132,252,0.1)',
            border: '1px solid rgba(192,132,252,0.2)',
            padding: '3px 10px', borderRadius: 6,
          }}>
            {modelName}
          </span>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={handleCopy}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 7,
              background: copied ? 'rgba(16,185,129,0.15)' : 'var(--bg-elevated)',
              border: `1px solid ${copied ? 'rgba(16,185,129,0.3)' : 'var(--border)'}`,
              color: copied ? '#10b981' : 'var(--text-secondary)',
              fontSize: 11, fontWeight: 500, cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>

      {/* DataHub Context collapsible */}
      <div style={{
        marginBottom: 8, flexShrink: 0,
        border: '1px solid var(--border)',
        borderRadius: 8,
        overflow: 'hidden',
      }}>
        <button
          onClick={() => setContextExpanded(v => !v)}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 8,
            padding: '7px 12px',
            background: 'var(--bg-card)',
            border: 'none', cursor: 'pointer',
            color: 'var(--text-secondary)',
            fontSize: 11, fontWeight: 600,
            textAlign: 'left',
          }}
        >
          <Database size={11} style={{ color: '#60a5fa' }} />
          <span style={{ color: 'var(--text-secondary)' }}>DataHub Context Used</span>
          <div style={{ marginLeft: 'auto' }}>
            {contextExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          </div>
        </button>

        {contextExpanded && (
          <div style={{
            padding: '10px 12px',
            background: 'rgba(255,255,255,0.02)',
            borderTop: '1px solid var(--border)',
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12,
          }}>
            <ContextBlock
              icon="🗄️" title="Tables Fetched"
              items={schemaStep?.data?.datasets?.map(d => d.name) || []}
            />
            <ContextBlock
              icon="🔗" title="Lineage Edges"
              items={lineageStep?.data?.edges?.map(e => `${e.upstream} → ${e.downstream}`) || []}
            />
            <ContextBlock
              icon="📖" title="Terms Resolved"
              items={glossaryStep?.data?.terms?.map(t => t.name) || []}
              extra={govStep?.data?.piiColumns?.length > 0 ? `⚠ ${govStep.data.piiColumns.length} PII columns` : null}
            />
          </div>
        )}
      </div>

      {/* Code viewer */}
      <div style={{
        flex: 1, overflow: 'auto',
        borderRadius: 10,
        border: '1px solid var(--border)',
        background: '#0d0f1e',
        marginBottom: 0,
      }}>
        {content ? (
          <pre style={{
            margin: 0,
            padding: '16px',
            fontFamily: 'JetBrains Mono, Fira Code, monospace',
            fontSize: 12,
            lineHeight: 1.7,
            color: '#cdd6f4',
            overflowX: 'auto',
            whiteSpace: 'pre',
            counterReset: 'line',
          }}>
            {content.split('\n').map((line, i) => (
              <div key={i} style={{ display: 'flex', gap: 16 }}>
                <span style={{
                  color: '#3d4057',
                  userSelect: 'none',
                  minWidth: 28,
                  textAlign: 'right',
                  flexShrink: 0,
                  fontSize: 11,
                }}>
                  {i + 1}
                </span>
                <span dangerouslySetInnerHTML={{ __html: highlightLine(line, activeTab) }} />
              </div>
            ))}
          </pre>
        ) : (
          <div style={{
            height: '100%', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            color: 'var(--text-muted)', fontSize: 13,
          }}>
            <div className="shimmer" style={{
              width: '60%', height: 12, borderRadius: 6,
            }} />
          </div>
        )}
      </div>
    </div>
  )
}

function ContextBlock({ icon, title, items, extra }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 5 }}>
        {icon} {title}
      </div>
      {items.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>none</div>
      )}
      {items.slice(0, 5).map((item, i) => (
        <div key={i} style={{
          fontSize: 11, color: 'var(--text-secondary)',
          fontFamily: 'JetBrains Mono, monospace',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          marginBottom: 2,
        }}>
          {item}
        </div>
      ))}
      {extra && (
        <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 4 }}>{extra}</div>
      )}
    </div>
  )
}

// Simple syntax highlighter
function highlightLine(line, type) {
  if (type === 'sql') {
    return line
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\b(SELECT|FROM|WHERE|JOIN|ON|LEFT|RIGHT|INNER|OUTER|GROUP BY|ORDER BY|WITH|AS|AND|OR|NOT|IN|IS|NULL|CASE|WHEN|THEN|ELSE|END|DISTINCT|HAVING|UNION|ALL)\b/gi,
        '<span style="color:#89b4fa;font-weight:600">$1</span>')
      .replace(/\{\{[^}]+\}\}/g, m =>
        `<span style="color:#a6e3a1;font-style:italic">${m}</span>`)
      .replace(/'([^']*)'/g,
        `<span style="color:#f38ba8">'$1'</span>`)
      .replace(/--([^\n]*)/g,
        `<span style="color:#6c7086;font-style:italic">--$1</span>`)
      .replace(/\b(\d+)\b/g,
        `<span style="color:#fab387">$1</span>`)
  }
  // YAML
  return line
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^(\s*)([\w_-]+):/gm,
      `$1<span style="color:#89b4fa">$2</span>:`)
    .replace(/: (.+)$/gm, (m, v) =>
      v.startsWith("'") || v.startsWith('"')
        ? `: <span style="color:#f38ba8">${v}</span>`
        : `: <span style="color:#a6e3a1">${v}</span>`)
    .replace(/^(\s*- )/gm,
      `<span style="color:#89dceb">$1</span>`)
    .replace(/#([^\n]*)/g,
      `<span style="color:#6c7086">#$1</span>`)
}
