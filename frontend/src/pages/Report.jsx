import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getReport, endSession } from '../api/client'
import './Report.css'

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
      await endSession(sessionId)
      sessionStorage.removeItem('interviewSession')
      sessionStorage.removeItem('qaHistory')
    } catch (err) {
      setError('Failed to generate report. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const scoreColor = (s) => s >= 4 ? 'var(--green)' : s >= 3 ? 'var(--accent)' : 'var(--red)'
  const readiness = (s) => s >= 4.5 ? 'High' : s >= 3.5 ? 'Moderate–High' : s >= 2.5 ? 'Moderate' : 'Needs Improvement'

  if (loading) return (
    <div className="report-loading">
      <div className="report-loading-inner">
        <span className="spinner" style={{ width: 32, height: 32, borderColor: 'rgba(232,168,56,0.2)', borderTopColor: 'var(--accent)' }} />
        <div className="report-loading-text">
          <div style={{ fontFamily: 'var(--display)', fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Generating Report</div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
            Querying Neo4j · Analyzing performance · Writing recommendations…
          </div>
        </div>
      </div>
    </div>
  )

  if (error) return (
    <div className="report-loading">
      <div style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--red)', border: '1px solid rgba(248,113,113,0.3)', padding: '20px 28px' }}>
        ⚠️ {error}
      </div>
    </div>
  )

  return (
    <div className="report-page">
      <div className="report-container">
        {/* HEADER */}
        <div className="report-top">
          <div>
            <div className="section-label">Performance Report</div>
            <h1 className="section-title" style={{ marginBottom: 8 }}>Interview Complete</h1>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
              {report?.session_id} · {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
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
              <div className="score-card-val" style={{ color: scoreColor(score) }}>{score?.toFixed(1)}</div>
              <div className="score-card-max">/5.0</div>
              <div className="score-card-bar">
                <div className="score-card-fill" style={{ width: `${(score / 5) * 100}%`, background: scoreColor(score) }} />
              </div>
              <div className="score-card-sub">{sub}</div>
            </div>
          ))}
          <div className="score-card score-card-readiness">
            <div className="score-card-label">Interview Readiness</div>
            <div className="score-card-val" style={{ color: scoreColor(report?.overall_rating), fontSize: 28 }}>
              {readiness(report?.overall_rating)}
            </div>
            <div className="score-card-sub">{report?.performance_metrics?.total_questions} questions answered</div>
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

        {/* FULL REPORT */}
        <div className="report-section-card">
          <div className="rsc-label">Detailed Feedback Report</div>
          <div className="report-text">
            {report?.final_report?.split('\n').map((line, i) => (
              <p key={i} style={{ marginBottom: line.trim() ? 12 : 4, opacity: line.trim() ? 1 : 0.3 }}>
                {line || <br />}
              </p>
            ))}
          </div>
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
