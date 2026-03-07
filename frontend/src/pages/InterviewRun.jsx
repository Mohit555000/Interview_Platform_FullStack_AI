import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getCurrentQuestion, submitAnswer, endInterview } from '../api/client'
import './InterviewRun.css'

const fmt = (s) => {
  const m = Math.floor(Math.abs(s) / 60)
  const sec = Math.abs(s) % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

const getTimerWarning = (elapsed, total) => {
  const pct = elapsed / total
  if (pct >= 0.95) return 'critical'
  if (pct >= 0.80) return 'warning'
  return null
}

export default function InterviewRun() {
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [question, setQuestion] = useState(null)
  const [answer, setAnswer] = useState('')
  const [evaluation, setEvaluation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState('')
  const [qaHistory, setQaHistory] = useState([])
  const [showConfirm, setShowConfirm] = useState(false)
  const [showEndConfirm, setShowEndConfirm] = useState(false)
  const [pendingAnswer, setPendingAnswer] = useState('')

  const [elapsed, setElapsed] = useState(0)
  const [totalSecs, setTotalSecs] = useState(0)
  const [timerExpired, setTimerExpired] = useState(false)
  const [warningShown, setWarningShown] = useState(null)
  const timerRef = useRef(null)
  const textareaRef = useRef(null)

  const startTimer = useCallback((durationMinutes) => {
    const total = durationMinutes * 60
    setTotalSecs(total)
    setElapsed(0)
    timerRef.current = setInterval(() => {
      setElapsed(prev => {
        const next = prev + 1
        if (next >= total) {
          clearInterval(timerRef.current)
          setTimerExpired(true)
          return total
        }
        return next
      })
    }, 1000)
  }, [])

  useEffect(() => {
    const raw = sessionStorage.getItem('interviewSession')
    if (!raw) { navigate('/interview'); return }
    const sess = JSON.parse(raw)
    setSession(sess)
    fetchQuestion(sess.session_id)
    startTimer(sess.duration)
    return () => clearInterval(timerRef.current)
  }, [])

  useEffect(() => {
    if (!totalSecs) return
    const level = getTimerWarning(elapsed, totalSecs)
    if (level === 'critical' && warningShown !== 'critical') setWarningShown('critical')
    else if (level === 'warning' && warningShown === null) setWarningShown('warning')
  }, [elapsed, totalSecs])

  const fetchQuestion = async (sessionId) => {
    setLoading(true)
    try {
      const q = await getCurrentQuestion(sessionId)
      setQuestion(q)
      setEvaluation(null)
      setAnswer('')
      setTimeout(() => textareaRef.current?.focus(), 100)
    } catch (err) {
      setError('Failed to load question.')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitClick = (overrideAnswer) => {
    const finalAnswer = overrideAnswer ?? answer.trim()
    if (!finalAnswer) { textareaRef.current?.focus(); return }
    setPendingAnswer(finalAnswer)
    setShowConfirm(true)
  }

  const handleConfirm = async () => {
    setShowConfirm(false)
    setSubmitting(true)
    setError('')
    try {
      const result = await submitAnswer(session.session_id, pendingAnswer)
      setEvaluation(result)
      const newEntry = { question: question.question, answer: pendingAnswer, ...result }
      const updated = [...qaHistory, newEntry]
      setQaHistory(updated)
      if (timerExpired) {
        sessionStorage.setItem('qaHistory', JSON.stringify(updated))
        clearInterval(timerRef.current)
        await endInterview(session.session_id)
        setTimeout(() => navigate('/interview/report'), 1200)
      }
    } catch (err) {
      setError('Failed to submit answer. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleModify = () => {
    setShowConfirm(false)
    setTimeout(() => {
      textareaRef.current?.focus()
      const len = textareaRef.current?.value?.length || 0
      textareaRef.current?.setSelectionRange(len, len)
    }, 50)
  }

  const handleEndInterview = async () => {
    setShowEndConfirm(false)
    setEnding(true)
    clearInterval(timerRef.current)
    try {
      await endInterview(session.session_id)
      navigate('/interview/report')
    } catch (err) {
      setError('Failed to end interview. Please try again.')
      setEnding(false)
    }
  }

  const handleDontKnow = () => handleSubmitClick("I don't know")

  const handleNext = () => {
    if (timerExpired) { navigate('/interview/report'); return }
    setEvaluation(null)
    fetchQuestion(session.session_id)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmitClick()
  }

  const remaining = Math.max(totalSecs - elapsed, 0)
  const progressPct = totalSecs ? Math.min((elapsed / totalSecs) * 100, 100) : 0
  const avgScore = qaHistory.length
    ? (qaHistory.reduce((a, b) => a + b.overall_score, 0) / qaHistory.length).toFixed(1)
    : null
  const scoreColor = (s) => s >= 4 ? 'var(--green)' : s >= 3 ? 'var(--accent)' : 'var(--red)'
  const timerColor = warningShown === 'critical' ? 'var(--red)' : warningShown === 'warning' ? '#f59e0b' : 'var(--text)'

  return (
    <div className="run-page">

      {showConfirm && (
        <div className="confirm-overlay">
          <div className="confirm-modal">
            <div className="confirm-icon">📝</div>
            <div className="confirm-title">Ready to submit?</div>
            <div className="confirm-subtitle">Review your answer before it's evaluated.</div>
            <div className="confirm-answer-preview">
              {pendingAnswer === "I don't know"
                ? <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>I don't know</span>
                : pendingAnswer}
            </div>
            <div className="confirm-actions">
              <button className="btn-ghost confirm-modify" onClick={handleModify}>✏ Modify Answer</button>
              <button className="btn-primary confirm-submit" onClick={handleConfirm}>Submit Answer →</button>
            </div>
          </div>
        </div>
      )}

      {showEndConfirm && (
        <div className="confirm-overlay">
          <div className="confirm-modal">
            <div className="confirm-icon">🏁</div>
            <div className="confirm-title">End interview?</div>
            <div className="confirm-subtitle">
              You've answered {qaHistory.length} question{qaHistory.length !== 1 ? 's' : ''}.
              Your report will be generated from answers so far.
            </div>
            <div className="confirm-actions">
              <button className="btn-ghost confirm-modify" onClick={() => setShowEndConfirm(false)}>Keep Going</button>
              <button className="btn-primary confirm-submit" onClick={handleEndInterview}
                style={{ background: 'var(--red)', borderColor: 'var(--red)' }}>
                End & Get Report →
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="run-header">
        <div className="run-header-left">
          <div className="run-mode-badge">{session?.mode?.toUpperCase()} MODE</div>
          <span className="run-persona">Interviewer: {session?.persona}</span>
        </div>

        <div className="run-timer-wrap">
          <div className="run-timer-block">
            <div className="run-timer-label">Elapsed</div>
            <div className="run-timer-val" style={{ color: 'var(--text-muted)' }}>{fmt(elapsed)}</div>
          </div>
          <div className="run-timer-track-wrap">
            <div className="run-timer-track">
              <div className={`run-timer-fill ${warningShown || ''}`} style={{ width: `${progressPct}%` }} />
            </div>
            {timerExpired && <div className="run-timer-expired-label">Time's up — finish your answer</div>}
          </div>
          <div className="run-timer-block">
            <div className="run-timer-label">Remaining</div>
            <div className="run-timer-val" style={{ color: timerColor }}>{fmt(remaining)}</div>
          </div>
        </div>

        <button className="run-end-btn" onClick={() => setShowEndConfirm(true)} disabled={ending || submitting}>
          {ending ? 'Ending…' : 'End Interview'}
        </button>
      </div>

      {warningShown === 'critical' && !timerExpired && (
        <div className="timer-banner critical">
          🔴 Final stage — complete your current answer, the interview is about to end.
        </div>
      )}
      {warningShown === 'warning' && warningShown !== 'critical' && !timerExpired && (
        <div className="timer-banner warning">
          ⚠️ Interview entering final stage — {fmt(remaining)} remaining.
        </div>
      )}
      {timerExpired && (
        <div className="timer-banner expired">
          ⏱ Time's up! Complete your current answer to generate your report.
        </div>
      )}

      <div className="run-body">
        <div className="run-main">
          {loading ? (
            <div className="run-loading">
              <span className="spinner" style={{ width: 24, height: 24, borderColor: 'rgba(232,168,56,0.2)', borderTopColor: 'var(--accent)' }} />
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text-dim)', marginLeft: 12 }}>Loading next question…</span>
            </div>
          ) : (
            <>
              <div className="question-meta">
                Question
                <span className="qm-sep">·</span>
                <span className="qm-id">#{question?.question_id}</span>
                {timerExpired && <span className="qm-final-badge">Final Question</span>}
              </div>

              <div className="question-text">{question?.question}</div>

              {!evaluation && (
                <div className="answer-area">
                  <div className="answer-label">Your Answer</div>
                  <textarea
                    ref={textareaRef}
                    className="answer-input"
                    placeholder="Type your answer here… (Ctrl+Enter to submit)"
                    value={answer}
                    onChange={e => setAnswer(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={6}
                  />
                  <div className="answer-footer">
                    <button className="dont-know-btn" onClick={handleDontKnow} disabled={submitting}>I don't know →</button>
                    <button className="submit-btn" onClick={() => handleSubmitClick()} disabled={submitting || !answer.trim()}>
                      {submitting ? <><span className="spinner" /> Evaluating…</> : <>Submit Answer ↵</>}
                    </button>
                  </div>
                </div>
              )}

              {evaluation && (
                <div className="eval-panel">
                  <div className="eval-header">
                    <div className="eval-title">{evaluation.is_dont_know ? '📝 Knowledge Gap Recorded' : '✅ Answer Evaluated'}</div>
                    <div className="eval-score" style={{ color: scoreColor(evaluation.overall_score) }}>
                      {evaluation.overall_score.toFixed(1)}<span className="eval-score-max">/5.0</span>
                    </div>
                  </div>
                  {!evaluation.is_dont_know && (
                    <div className="eval-scores-row">
                      {[['Technical', evaluation.technical_score], ['Clarity', evaluation.clarity_score], ['Confidence', evaluation.confidence_score]].map(([label, score]) => (
                        <div className="eval-score-item" key={label}>
                          <div className="eval-score-label">{label}</div>
                          <div className="eval-score-track">
                            <div className="eval-score-fill" style={{ width: `${(score/5)*100}%`, background: scoreColor(score) }} />
                          </div>
                          <div className="eval-score-val" style={{ color: scoreColor(score) }}>{score.toFixed(1)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="eval-feedback">{evaluation.feedback}</div>
                  {timerExpired ? (
                    <div className="eval-done">
                      <span className="spinner" style={{ width: 16, height: 16, borderColor: 'rgba(232,168,56,0.3)', borderTopColor: 'var(--accent)' }} />
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text-dim)', marginLeft: 10 }}>Time up — preparing your report…</span>
                    </div>
                  ) : (
                    <button className="btn-primary" style={{ fontSize: 12, padding: '10px 24px', marginTop: 4 }} onClick={handleNext}>
                      Next Question →
                    </button>
                  )}
                </div>
              )}

              {error && <div className="run-error">⚠️ {error}</div>}
            </>
          )}
        </div>

        <div className="run-sidebar">
          <div className="sidebar-card">
            <div className="sidebar-label">Session</div>
            <div className="sidebar-session-id">{session?.session_id}</div>
          </div>
          <div className="sidebar-card">
            <div className="sidebar-label">Questions Answered</div>
            <div className="sidebar-big-score" style={{ color: 'var(--accent)' }}>
              {qaHistory.length}
              <span style={{ fontSize: 14, color: 'var(--text-muted)', fontFamily: 'var(--mono)', fontWeight: 300, marginLeft: 4 }}>answered</span>
            </div>
          </div>
          {avgScore && (
            <div className="sidebar-card">
              <div className="sidebar-label">Running Average</div>
              <div className="sidebar-big-score" style={{ color: scoreColor(parseFloat(avgScore)) }}>
                {avgScore}<span style={{ fontSize: 16, color: 'var(--text-muted)', fontFamily: 'var(--sans)', fontWeight: 300 }}>/5.0</span>
              </div>
            </div>
          )}
          {session?.resume_summary?.skills && (
            <div className="sidebar-card">
              <div className="sidebar-label">Candidate Skills</div>
              <div className="topic-chips">
                {session.resume_summary.skills.slice(0, 10).map(s => <span className="chip" key={s}>{s}</span>)}
              </div>
            </div>
          )}
          {session?.jd_summary?.required_skills && (
            <div className="sidebar-card">
              <div className="sidebar-label">JD Requirements</div>
              <div className="topic-chips">
                {session.jd_summary.required_skills.slice(0, 8).map(s => <span className="chip active" key={s}>{s}</span>)}
              </div>
            </div>
          )}
          {qaHistory.length > 0 && (
            <div className="sidebar-card">
              <div className="sidebar-label">Question History</div>
              <div className="history-list">
                {qaHistory.map((qa, i) => (
                  <div className="history-item" key={i}>
                    <div className="history-q">Q{qa.question_id}: {qa.question.slice(0, 60)}…</div>
                    <div className="history-score" style={{ color: scoreColor(qa.overall_score) }}>{qa.overall_score.toFixed(1)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}