import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { startSession } from '../api/client'
import ApiKeyDialog from '../components/ApiKeyDialog'
import './Setup.css'

const INIT_STEPS = [
  'Uploading your resume…',
  'Reading job description…',
  'Matching your skills to the role…',
  'Planning your interview…',
  'Almost ready…',
]

const PRESET_MODES = [
  { id: 'quick',    label: 'Quick',    duration: '10 min', desc: 'Fast-paced screening round. Core concepts and fundamentals.',                      durationMins: 10 },
  { id: 'standard', label: 'Standard', duration: '20 min', desc: 'Full technical deep-dive. Architecture, design patterns, problem-solving.',         durationMins: 20 },
  { id: 'custom',   label: 'Custom',   duration: 'You choose', desc: 'Set your own duration from 5 to 60 minutes.',                                   durationMins: null },
]

// Shared drop zone component
function DropZone({ label, file, onFile, onRemove, accept = '.pdf', hint = 'Supports .pdf files only', inputId }) {
  const [dragOver, setDragOver] = useState(false)

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f?.type === 'application/pdf') onFile(f)
  }

  return (
    <div className="setup-card">
      <div className="card-label">{label}</div>
      <div
        className={`drop-zone ${dragOver ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => document.getElementById(inputId).click()}
      >
        <input
          id={inputId}
          type="file"
          accept={accept}
          style={{ display: 'none' }}
          onChange={e => { const f = e.target.files[0]; if (f) onFile(f) }}
        />
        {file ? (
          <div className="drop-file-info">
            <span className="drop-icon">📄</span>
            <div>
              <div className="drop-filename">{file.name}</div>
              <div className="drop-filesize">{(file.size / 1024).toFixed(1)} KB · PDF</div>
            </div>
            <button className="drop-remove" onClick={e => { e.stopPropagation(); onRemove() }}>✕</button>
          </div>
        ) : (
          <div className="drop-placeholder">
            <span className="drop-icon">⬆</span>
            <div className="drop-title">Drop PDF here or click to upload</div>
            <div className="drop-hint">{hint}</div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Setup() {
  const navigate = useNavigate()
  const [mode, setMode]                 = useState('standard')
  const [customDuration, setCustomDuration] = useState(30)
  const [resumeFile, setResumeFile]     = useState(null)
  const [jdFile, setJdFile]             = useState(null)   // ← now a File, not text
  const [loading, setLoading]           = useState(false)
  const [loadingStep, setLoadingStep]   = useState(0)
  const [error, setError]               = useState('')
  const [showApiDialog, setShowApiDialog] = useState(false)
  const [llmConfig, setLlmConfig]       = useState(null)

  const validateCustomDuration = () => {
    const val = parseInt(customDuration)
    if (isNaN(val) || val < 5 || val > 60) {
      setError('Custom duration must be between 5 and 60 minutes.')
      return false
    }
    return true
  }

  const handleStartClick = () => {
    if (!resumeFile)  { setError('Please upload your resume PDF.'); return }
    if (!jdFile)      { setError('Please upload the job description PDF.'); return }
    if (mode === 'custom' && !validateCustomDuration()) return
    setError('')
    setShowApiDialog(true)
  }

  const handleApiKeyConfirm = async (config) => {
    setShowApiDialog(false)
    setLlmConfig(config)
    await beginSession(config)
  }

  const beginSession = async (config) => {
    setLoading(true)
    setLoadingStep(0)
    const stepInterval = setInterval(() => {
      setLoadingStep(i => Math.min(i + 1, INIT_STEPS.length - 1))
    }, 1800)
    try {
      const duration = mode === 'custom' ? parseInt(customDuration) : null
      // Pass jdFile directly — backend extracts text from PDF
      const session = await startSession(resumeFile, jdFile, mode, config, duration)
      sessionStorage.setItem('interviewSession', JSON.stringify(session))
      if (config) {
        sessionStorage.setItem('llmConfig', JSON.stringify({ provider: config.provider, model: config.model }))
      }
      navigate('/interview/run')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start session. Please try again.')
    } finally {
      clearInterval(stepInterval)
      setLoading(false)
    }
  }

  const resolvedDuration = mode === 'custom'
    ? `${customDuration} min`
    : PRESET_MODES.find(m => m.id === mode)?.duration

  return (
    <div className="setup-page">
      {showApiDialog && <ApiKeyDialog onConfirm={handleApiKeyConfirm} />}

      <div className="setup-container">
        <div className="setup-header">
          <div className="section-label">New Interview</div>
          <h1 className="section-title">Configure your<br />interview session</h1>
          <p className="section-desc">Upload your resume and job description PDF. The AI will generate a role-specific interviewer and conduct a fully voice-based interview.</p>
        </div>

        {/* LLM CONFIG BADGE */}
        {llmConfig && !loading && (
          <div className="llm-config-badge">
            <span className="llm-config-dot" style={{
              background: llmConfig.provider === 'openai' ? '#10a37f'
                : llmConfig.provider === 'anthropic' ? '#d4622a' : '#4285f4'
            }} />
            <span>Using <strong>{llmConfig.provider}</strong> · {llmConfig.model}</span>
            <button className="llm-config-change" onClick={() => setShowApiDialog(true)}>Change</button>
          </div>
        )}

        {/* DURATION */}
        <div className="setup-card">
          <div className="card-label">Interview Duration</div>
          <div className="mode-grid">
            {PRESET_MODES.map(m => (
              <div key={m.id} className={`mode-card ${mode === m.id ? 'active' : ''}`} onClick={() => setMode(m.id)}>
                <div className="mode-top">
                  <div className="mode-name">{m.label}</div>
                  <div className="mode-radio">{mode === m.id && <span className="mode-radio-dot" />}</div>
                </div>
                <div className="mode-stats">
                  <span className="mode-stat">⏱ {m.duration}</span>
                  <span className="mode-stat mode-stat-ai">🤖 AI Persona</span>
                </div>
                <div className="mode-desc">{m.desc}</div>
              </div>
            ))}
          </div>

          {mode === 'custom' && (
            <div className="custom-duration-wrap">
              <div className="custom-duration-label">Set duration (minutes)</div>
              <div className="custom-duration-row">
                {[5, 10, 15, 20, 30, 45, 60].map(val => (
                  <button key={val} className={`duration-chip ${parseInt(customDuration) === val ? 'active' : ''}`}
                    onClick={() => setCustomDuration(val)} type="button">{val}m</button>
                ))}
                <div className="custom-duration-input-wrap">
                  <input type="number" className="custom-duration-input" value={customDuration}
                    min={5} max={60} onChange={e => setCustomDuration(e.target.value)} />
                  <span className="custom-duration-unit">min</span>
                </div>
              </div>
              <div className="custom-duration-hint">Between 5 and 60 minutes</div>
            </div>
          )}

          {!loading && (
            <div className="duration-summary">
              <span className="duration-summary-label">Selected:</span>
              <span className="duration-summary-val">{resolvedDuration}</span>
              <span className="duration-summary-note">· Voice interview · AI persona from JD</span>
            </div>
          )}
        </div>

        {/* RESUME UPLOAD */}
        <DropZone
          label="Resume PDF"
          file={resumeFile}
          onFile={setResumeFile}
          onRemove={() => setResumeFile(null)}
          inputId="resume-input"
          hint="Your resume in PDF format"
        />

        {/* JD UPLOAD — replaces the old textarea */}
        <DropZone
          label="Job Description PDF"
          file={jdFile}
          onFile={setJdFile}
          onRemove={() => setJdFile(null)}
          inputId="jd-input"
          hint="The job description in PDF format"
        />

        {error && <div className="setup-error">⚠️ {error}</div>}

        <button className="btn-primary setup-submit" onClick={handleStartClick} disabled={loading}>
          {loading
            ? <><span className="spinner" /> {INIT_STEPS[loadingStep]}</>
            : <>Start Interview Session →</>}
        </button>

        {loading && (
          <div className="setup-progress-dots">
            {INIT_STEPS.map((_, i) => (
              <span key={i} className={`loading-dot ${i <= loadingStep ? 'active' : ''}`} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}