import { useState, useRef, useCallback } from 'react'
import { Sparkles, Database, GitBranch, Zap } from 'lucide-react'
import ChatInput from './components/ChatInput'
import ProgressPanel from './components/ProgressPanel'
import ArtifactPreview from './components/ArtifactPreview'
import PRResult from './components/PRResult'

const STEPS_CONFIG = [
  { id: 'schema',     icon: '🗄️',  label: 'Schema Lookup',       description: 'Querying DataHub catalog' },
  { id: 'lineage',    icon: '🔗',  label: 'Lineage Fetch',       description: 'Tracing data lineage' },
  { id: 'glossary',   icon: '📖',  label: 'Glossary Resolution', description: 'Resolving business terms' },
  { id: 'governance', icon: '🏷️',  label: 'Tags & Assertions',   description: 'Checking PII & quality' },
  { id: 'generation', icon: '🤖',  label: 'LLM Generation',      description: 'Generating SQL + YAML' },
  { id: 'validation', icon: '✅',  label: 'Validation',          description: 'Validating identifiers' },
  { id: 'github',     icon: '🚀',  label: 'GitHub PR',           description: 'Creating pull request' },
  { id: 'writeback',  icon: '📡',  label: 'DataHub Write-Back',  description: 'Registering model + lineage' },
]

export default function App() {
  const [steps, setSteps]           = useState([])
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedSql, setGeneratedSql] = useState('')
  const [generatedYaml, setGeneratedYaml] = useState('')
  const [prResult, setPrResult]     = useState(null)
  const [modelName, setModelName]   = useState('')
  const [currentRequest, setCurrentRequest] = useState('')
  const [serverHealth, setServerHealth] = useState(null)
  const abortRef = useRef(null)

  const handleGenerate = useCallback(async (request) => {
    if (isGenerating) return
    
    setIsGenerating(true)
    setCurrentRequest(request)
    setSteps(STEPS_CONFIG.map(s => ({ ...s, status: 'pending', message: '', data: {} })))
    setGeneratedSql('')
    setGeneratedYaml('')
    setPrResult(null)
    setModelName('')

    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request }),
        signal: abortRef.current,
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            handleEvent(event)
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Stream error:', err)
      }
    } finally {
      setIsGenerating(false)
    }
  }, [isGenerating])

  const handleEvent = useCallback((event) => {
    const { step, status, message, data } = event
    if (step === 'done') {
      setIsGenerating(false)
      return
    }
    if (step === 'error') {
      setSteps(prev => prev.map(s =>
        s.status === 'running' ? { ...s, status: 'error', message } : s
      ))
      return
    }

    // Extract artifacts from events
    if (step === 'generation' && status === 'done') {
      if (data?.sql) setGeneratedSql(data.sql)
      if (data?.modelName) setModelName(data.modelName)
    }
    if (step === 'validation' && (status === 'done' || status === 'warning')) {
      if (data?.yaml) setGeneratedYaml(data.yaml)
    }
    if (step === 'github' && status === 'done') {
      setPrResult(data)
    }
    if (step === 'github' && status === 'skipped') {
      setPrResult({ skipped: true, ...data })
      if (data?.files?.sql?.content) setGeneratedSql(prev => prev || data.files.sql.content)
      if (data?.files?.yaml?.content) setGeneratedYaml(prev => prev || data.files.yaml.content)
    }

    setSteps(prev => {
      const idx = prev.findIndex(s => s.id === step)
      if (idx === -1) return prev
      const updated = [...prev]
      updated[idx] = { ...updated[idx], status, message, data }
      return updated
    })
  }, [])

  const handleStop = () => {
    abortRef.current?.abort()
    setIsGenerating(false)
  }

  const hasArtifacts = generatedSql || generatedYaml
  const hasProgress = steps.some(s => s.status !== 'pending')

  return (
    <div className="grid-bg" style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <header style={{
        borderBottom: '1px solid var(--border)',
        padding: '12px 24px',
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        background: 'rgba(7, 8, 16, 0.9)',
        backdropFilter: 'blur(20px)',
        flexShrink: 0,
        zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: 'linear-gradient(135deg, #7c3aed, #2563eb)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18,
            boxShadow: '0 0 20px rgba(124,58,237,0.4)',
          }}>
            ⚡
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.3px' }}>
              <span className="gradient-text">dbt Model Generator</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
              Grounded in DataHub · Powered by Groq
            </div>
          </div>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <Indicator icon={<Database size={12} />} label="DataHub" active />
          <Indicator icon={<Zap size={12} />} label="Groq" active />
          <Indicator icon={<GitBranch size={12} />} label="GitHub" />
        </div>
      </header>

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left panel: Input + Progress */}
        <div style={{
          width: hasArtifacts ? '380px' : '100%',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          borderRight: hasArtifacts ? '1px solid var(--border)' : 'none',
          overflow: 'hidden',
          transition: 'width 0.3s ease',
        }}>
          <ChatInput
            onGenerate={handleGenerate}
            onStop={handleStop}
            isGenerating={isGenerating}
            compact={hasProgress}
          />
          {hasProgress && (
            <div style={{ flex: 1, overflow: 'auto', padding: '0 16px 16px' }}>
              <ProgressPanel steps={steps} />
            </div>
          )}
          {!hasProgress && <HeroContent />}
        </div>

        {/* Right panel: Artifacts + PR */}
        {hasArtifacts && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <ArtifactPreview
              sql={generatedSql}
              yaml={generatedYaml}
              modelName={modelName}
              request={currentRequest}
              steps={steps}
            />
            {prResult && (
              <PRResult result={prResult} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Indicator({ icon, label, active }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 999,
      background: active ? 'rgba(16,185,129,0.1)' : 'rgba(255,255,255,0.04)',
      border: `1px solid ${active ? 'rgba(16,185,129,0.3)' : 'var(--border)'}`,
      fontSize: 11, fontWeight: 500,
      color: active ? '#34d399' : 'var(--text-muted)',
    }}>
      {icon}
      {label}
      <div style={{
        width: 5, height: 5, borderRadius: '50%',
        background: active ? '#10b981' : 'var(--text-muted)',
        ...(active && { boxShadow: '0 0 6px #10b981' }),
      }} />
    </div>
  )
}

function HeroContent() {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '0 40px 60px',
      gap: 24,
    }}>
      <div style={{ textAlign: 'center', maxWidth: 480 }}>
        <div style={{ fontSize: 48, marginBottom: 12, filter: 'drop-shadow(0 0 20px rgba(124,58,237,0.5))' }}>⚡</div>
        <h1 style={{ fontSize: 28, fontWeight: 800, margin: 0, letterSpacing: '-0.5px' }}>
          <span className="gradient-text">DataHub-Grounded</span><br />
          <span style={{ color: 'var(--text-primary)' }}>dbt Model Generator</span>
        </h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: 12, fontSize: 14, lineHeight: 1.7 }}>
          Describe your transformation in plain English. The agent queries DataHub for real schema, 
          lineage, and glossary context — then generates validated dbt SQL + YAML and opens a GitHub PR.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, width: '100%', maxWidth: 460 }}>
        {[
          { icon: '🗄️', label: 'Schema grounded', desc: 'No hallucinated columns' },
          { icon: '🔗', label: 'Lineage-aware', desc: 'Correct joins & refs' },
          { icon: '📖', label: 'Glossary-resolved', desc: 'Business terms → SQL' },
          { icon: '🚀', label: 'PR ready', desc: 'Commits both files' },
        ].map(f => (
          <div key={f.label} className="glass" style={{ padding: '12px 14px', borderRadius: 10 }}>
            <div style={{ fontSize: 18, marginBottom: 4 }}>{f.icon}</div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{f.label}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{f.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
