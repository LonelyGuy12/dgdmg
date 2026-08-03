import { useState } from 'react'
import { Send, Square, Sparkles } from 'lucide-react'

const EXAMPLES = [
  "join orders with customer lifetime value, filtered to active accounts",
  "daily revenue by product category excluding cancelled orders",
  "customer churn risk score based on recency of last order",
  "orders with PII-safe customer info for BI dashboards",
]

export default function ChatInput({ onGenerate, onStop, isGenerating, compact }) {
  const [value, setValue] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!value.trim() || isGenerating) return
    onGenerate(value.trim())
  }

  const handleExample = (ex) => {
    setValue(ex)
  }

  return (
    <div style={{
      padding: compact ? '12px 16px' : '24px 24px 16px',
      borderBottom: '1px solid var(--border)',
      background: 'rgba(7,8,16,0.6)',
      backdropFilter: 'blur(20px)',
      flexShrink: 0,
    }}>
      {!compact && (
        <div style={{ marginBottom: 14 }}>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Describe your transformation
          </p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div style={{ position: 'relative' }}>
          <textarea
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e)
            }}
            placeholder="e.g. build a model joining orders with customer lifetime value, filtered to active accounts…"
            disabled={isGenerating}
            rows={compact ? 2 : 3}
            style={{
              width: '100%',
              background: 'var(--bg-elevated)',
              border: `1px solid ${isGenerating ? 'var(--accent-purple)' : 'var(--border-bright)'}`,
              borderRadius: 12,
              padding: '12px 50px 12px 14px',
              color: 'var(--text-primary)',
              fontSize: 13,
              fontFamily: 'Inter, sans-serif',
              resize: 'none',
              outline: 'none',
              lineHeight: 1.5,
              transition: 'border-color 0.2s',
              boxShadow: isGenerating ? '0 0 0 2px rgba(124,58,237,0.2)' : 'none',
            }}
          />
          <button
            type={isGenerating ? 'button' : 'submit'}
            onClick={isGenerating ? onStop : undefined}
            style={{
              position: 'absolute',
              right: 10,
              bottom: 10,
              width: 32,
              height: 32,
              borderRadius: 8,
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: isGenerating
                ? 'rgba(239,68,68,0.15)'
                : (!value.trim() ? 'var(--bg-card)' : 'linear-gradient(135deg, #7c3aed, #2563eb)'),
              color: isGenerating ? '#ef4444' : (value.trim() ? '#fff' : 'var(--text-muted)'),
              transition: 'all 0.15s',
            }}
          >
            {isGenerating
              ? <Square size={14} />
              : <Send size={14} />
            }
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          <Sparkles size={11} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
          {EXAMPLES.map(ex => (
            <button
              key={ex}
              type="button"
              onClick={() => handleExample(ex)}
              disabled={isGenerating}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 999,
                padding: '3px 10px',
                fontSize: 11,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s',
                maxWidth: 200,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = 'var(--text-primary)'
                e.currentTarget.style.borderColor = 'var(--border-bright)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = 'var(--text-secondary)'
                e.currentTarget.style.borderColor = 'var(--border)'
              }}
            >
              {ex.length > 35 ? ex.slice(0, 35) + '…' : ex}
            </button>
          ))}
        </div>
      </form>
    </div>
  )
}
