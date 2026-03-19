import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getReport, endSession } from '../api/client'
import './Report.css'

// ── Renders **bold** inline markdown ──────────────────────────────
function renderInline(text) {
  if (!text) return null
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={i} style={{ color: 'var(--text)', fontWeight: 600 }}>{part.slice(2, -2)}</strong>
      : part
  )
}

// ── Parses the LLM markdown report into structured React nodes ────
function ReportText({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  return (
    <div className="report-text">
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (!trimmed) return <div key={i} style={{ height: 10 }} />
        if (trimmed.startsWith('### ')) {
          return <div key={i} className="report-h1">{trimmed.replace(/^###\s+/, '')}</div>
        }
        if (trimmed.startsWith('#### ')) {
          return <div key={i} className="report-h2">{trimmed.replace(/^####\s+/, '')}</div>
        }
        if (trimmed === '---') return <hr key={i} className="report-divider" />
        if (/^\d+\.\s/.test(trimmed)) {
          const num = trimmed.match(/^\d+/)[0]
          const content = trimmed.replace(/^\d+\.\s+/, '')
          return (
            <div key={i} className="report-list-item">
              <span className="report-list-num">{num}</span>
              <span>{renderInline(content)}</span>
            </div>
          )
        }
        if (trimmed.startsWith('- ')) {
          return (
            <div key={i} className="report-bullet">
              <span className="report-bullet-dot">›</span>
              <span>{renderInline(trimmed.slice(2))}</span>
            </div>
          )
        }
        return <p key={i} className="report-para">{renderInline(trimmed)}</p>
      })}
    </div>
  )
}

// ── Friendly loading steps shown to the user (no technical details) ──
const LOADING_STEPS = [
  'Reviewing your answers…',
  'Calculating your scores…',
  'Identifying strengths…',
  'Building improvement plan…',
  'Writing your report…',
]

function LoadingReport() {
  const [stepIndex, setStepIndex] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      setStepIndex(i => Math.min(i + 1, LOADING_STEPS.length - 1))
    }, 2200)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="report-loading">
      <div className="report-loading-inner">
        <div className="report-loading-ring">
          <span className="spinner" style={{
            width: 40, height: 40,
            borderColor: 'rgba(232,168,56,0.15)',
            borderTopColor: 'var(--accent)',
            borderWidth: 3,
          }} />
        </div>
        <div className="report-loading-text">
          <div style={{ fontFamily: 'var(--display)', fontSize: 26, fontWeight: 700, marginBottom: 12 }}>
            Generating Your Report
          </div>
          <div className="report-loading-step">
            {LOADING_STEPS[stepIndex]}
          </div>
          <div className="report-loading-dots">
            {LOADING_STEPS.map((_, i) => (
              <span key={i} className={`loading-dot ${i <= stepIndex ? 'active' : ''}`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Report Page ──────────────────────────────────────────────
export default function Report() {
  const navigate = useNavigate()
  const [report, setReport] = useState(null)
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const raw = sessionStorage.getItem('interviewSession')
    if (!raw) { navigate('/interview'); return }
    const sess = JSON.parse(raw)
    setSession(sess)
    fetchReport(sess.session_id)
  }, [])

  const fetchReport = async (sessionId) => {
    try {
      const data = await getReport(sessionId)
      setReport(data)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Something went wrong while generating your report. Please try again.')
    } finally {
      // ── Always clean up — regardless of success or failure ────────
      endSession(sessionId).catch(e => console.warn('[cleanup] endSession warning:', e))
      sessionStorage.removeItem('interviewSession')
      sessionStorage.removeItem('qaHistory')
      setLoading(false)
    }
  }

  const scoreColor = (s) => {
    if (!s && s !== 0) return 'var(--text-muted)'
    return s >= 4 ? 'var(--green)' : s >= 3 ? 'var(--accent)' : 'var(--red)'
  }

  const readiness = (s) => {
    if (!s) return '—'
    if (s >= 4.5) return 'High'
    if (s >= 3.5) return 'Moderate–High'
    if (s >= 2.5) return 'Moderate'
    return 'Needs Improvement'
  }

  if (loading) return <LoadingReport />

  if (error) {
    return (
      <div className="report-loading">
        <div className="report-error-box">
          <div className="report-error-icon">⚠</div>
          <div className="report-error-title">Report generation failed</div>
          <div className="report-error-msg">{error}</div>
        </div>
        <button className="btn-primary" style={{ marginTop: 24 }} onClick={() => navigate('/interview')}>
          Start New Interview →
        </button>
      </div>
    )
  }

  return (
    <div className="report-page">
      <div className="report-container">

        {/* HEADER */}
        <div className="report-top">
          <div>
            <div className="section-label">Performance Report</div>
            <h1 className="section-title" style={{ marginBottom: 8 }}>Interview Complete</h1>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
              {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
            </div>
          </div>
          <div className="overall-badge">
            <div className="overall-score" style={{ color: scoreColor(report?.overall_rating) }}>
              {report?.overall_rating?.toFixed(1)}
            </div>
            <div className="overall-label">Overall Score /5.0</div>
          </div>
        </div>

        {/* SCORE CARDS */}
        <div className="score-cards">
          {[
            ['Technical Accuracy', report?.individual_ratings?.technical, '40% weight'],
            ['Clarity', report?.individual_ratings?.clarity, '30% weight'],
            ['Confidence', report?.individual_ratings?.confidence, '20% weight'],
          ].map(([label, score, sub]) => (
            <div className="score-card" key={label}>
              <div className="score-card-label">{label}</div>
              <div className="score-card-val" style={{ color: scoreColor(score) }}>
                {score?.toFixed(1) ?? '—'}
              </div>
              <div className="score-card-max">/5.0</div>
              <div className="score-card-bar">
                <div className="score-card-fill" style={{ width: `${((score ?? 0) / 5) * 100}%`, background: scoreColor(score) }} />
              </div>
              <div className="score-card-sub">{sub}</div>
            </div>
          ))}
          <div className="score-card score-card-readiness">
            <div className="score-card-label">Interview Readiness</div>
            <div className="score-card-val" style={{ color: scoreColor(report?.overall_rating), fontSize: 22 }}>
              {readiness(report?.overall_rating)}
            </div>
            <div className="score-card-sub">{report?.performance_metrics?.total_questions ?? 0} questions answered</div>
          </div>
        </div>

        {/* WEAKNESSES */}
        {report?.weaknesses?.length > 0 && (
          <div className="report-section-card">
            <div className="rsc-label">Identified Weaknesses & Improvements</div>
            <div className="weakness-list">
              {report.weaknesses.map((w, i) => (
                <div className="weakness-row" key={i}>
                  <div className="weakness-left">
                    <span className={`severity-badge ${w.severity}`}>{w.severity}</span>
                    <span className="weakness-text">{w.weakness}</span>
                  </div>
                  <div className="weakness-improvement">↳ {w.improvement}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* DETAILED REPORT */}
        <div className="report-section-card">
          <div className="rsc-label">Detailed Feedback Report</div>
          <ReportText text={report?.final_report} />
        </div>

        {/* ACTIONS */}
        <div className="report-actions">
          <button className="btn-primary" onClick={() => navigate('/interview')}>
            Start New Interview →
          </button>
          <button className="btn-ghost" onClick={() => window.print()}>
            Print Report
          </button>
        </div>

      </div>
    </div>
  )
}