import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { startSession } from '../api/client'
import './Setup.css'

export default function Setup() {
  const navigate = useNavigate()
  const [mode, setMode] = useState('standard')
  const [resumeFile, setResumeFile] = useState(null)
  const [jdText, setJdText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)

  const handleFileDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file?.type === 'application/pdf') setResumeFile(file)
    else setError('Please upload a PDF file.')
  }

  const handleSubmit = async () => {
    if (!resumeFile) { setError('Please upload a resume PDF.'); return }
    if (!jdText.trim()) { setError('Please enter a job description.'); return }
    setError('')
    setLoading(true)
    try {
      const session = await startSession(resumeFile, jdText, mode)
      // Store session info for the interview page
      sessionStorage.setItem('interviewSession', JSON.stringify(session))
      navigate('/interview/run')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start session. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="setup-page">
      <div className="setup-container">
        <div className="setup-header">
          <div className="section-label">New Interview</div>
          <h1 className="section-title">Configure your<br />interview session</h1>
          <p className="section-desc">Upload a resume and job description. The AI will parse both and generate a tailored question set.</p>
        </div>

        {/* MODE SELECTOR */}
        <div className="setup-card">
          <div className="card-label">Interview Mode</div>
          <div className="mode-grid">
            {[
              { id: 'quick', label: 'Quick', duration: '10 min', questions: '7 Questions', persona: 'Senior Software Engineer', desc: 'Fast-paced screening round. Core concepts and fundamentals.' },
              { id: 'standard', label: 'Standard', duration: '20 min', questions: '12 Questions', persona: 'Technical Lead', desc: 'Full technical deep-dive. Architecture, design patterns, problem-solving.' },
            ].map(m => (
              <div
                key={m.id}
                className={`mode-card ${mode === m.id ? 'active' : ''}`}
                onClick={() => setMode(m.id)}
              >
                <div className="mode-top">
                  <div className="mode-name">{m.label}</div>
                  <div className="mode-radio">{mode === m.id && <span className="mode-radio-dot" />}</div>
                </div>
                <div className="mode-stats">
                  <span className="mode-stat">{m.duration}</span>
                  <span className="mode-stat">{m.questions}</span>
                </div>
                <div className="mode-persona">Persona: {m.persona}</div>
                <div className="mode-desc">{m.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* RESUME UPLOAD */}
        <div className="setup-card">
          <div className="card-label">Resume PDF</div>
          <div
            className={`drop-zone ${dragOver ? 'drag-over' : ''} ${resumeFile ? 'has-file' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
            onClick={() => document.getElementById('resume-input').click()}
          >
            <input
              id="resume-input"
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={e => {
                const f = e.target.files[0]
                if (f) setResumeFile(f)
              }}
            />
            {resumeFile ? (
              <div className="drop-file-info">
                <span className="drop-icon">📄</span>
                <div>
                  <div className="drop-filename">{resumeFile.name}</div>
                  <div className="drop-filesize">{(resumeFile.size / 1024).toFixed(1)} KB · PDF</div>
                </div>
                <button className="drop-remove" onClick={e => { e.stopPropagation(); setResumeFile(null) }}>✕</button>
              </div>
            ) : (
              <div className="drop-placeholder">
                <span className="drop-icon">⬆</span>
                <div className="drop-title">Drop PDF here or click to upload</div>
                <div className="drop-hint">Supports .pdf files only</div>
              </div>
            )}
          </div>
        </div>

        {/* JD TEXT */}
        <div className="setup-card">
          <div className="card-label">Job Description</div>
          <textarea
            className="jd-textarea"
            placeholder="Paste the full job description here — role summary, required skills, responsibilities, experience level…"
            value={jdText}
            onChange={e => setJdText(e.target.value)}
            rows={10}
          />
          <div className="jd-counter">{jdText.length} characters</div>
        </div>

        {/* ERROR */}
        {error && <div className="setup-error">⚠️ {error}</div>}

        {/* SUBMIT */}
        <button className="btn-primary setup-submit" onClick={handleSubmit} disabled={loading}>
          {loading ? (
            <>
              <span className="spinner" />
              Initializing Interview…
            </>
          ) : (
            <>Start Interview Session →</>
          )}
        </button>

        {loading && (
          <div className="setup-loading-info">
            <div className="t-line"><span className="t-success">▸</span><span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text-dim)' }}>Connecting to backend · Parsing resume · Building question plan…</span></div>
          </div>
        )}
      </div>
    </div>
  )
}
