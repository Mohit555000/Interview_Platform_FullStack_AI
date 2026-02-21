import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getCurrentQuestion, submitAnswer } from '../api/client'
import './InterviewRun.css'

export default function InterviewRun() {
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [question, setQuestion] = useState(null)
  const [answer, setAnswer] = useState('')
  const [evaluation, setEvaluation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [qaHistory, setQaHistory] = useState([])
  const textareaRef = useRef(null)

  useEffect(() => {
    const raw = sessionStorage.getItem('interviewSession')
    if (!raw) { navigate('/interview'); return }
    const sess = JSON.parse(raw)
    setSession(sess)
    fetchQuestion(sess.session_id)
  }, [])

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

  const handleSubmit = async (overrideAnswer) => {
    const finalAnswer = overrideAnswer ?? answer.trim()
    if (!finalAnswer) {
      textareaRef.current?.focus()
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const result = await submitAnswer(session.session_id, finalAnswer)
      setEvaluation(result)
      setQaHistory(prev => [...prev, {
        question: question.question,
        answer: finalAnswer,
        ...result,
      }])
      if (result.interview_complete) {
        sessionStorage.setItem('qaHistory', JSON.stringify([...qaHistory, { question: question.question, answer: finalAnswer, ...result }]))
        setTimeout(() => navigate('/interview/report'), 1200)
      }
    } catch (err) {
      setError('Failed to submit answer.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDontKnow = () => handleSubmit("I don't know")

  const handleNext = () => {
    setEvaluation(null)
    fetchQuestion(session.session_id)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  const progress = question ? (question.question_id / question.total_questions) * 100 : 0
  const avgScore = qaHistory.length
    ? (qaHistory.reduce((a, b) => a + b.overall_score, 0) / qaHistory.length).toFixed(1)
    : null

  const scoreColor = (s) => s >= 4 ? 'var(--green)' : s >= 3 ? 'var(--accent)' : 'var(--red)'

  return (
    <div className="run-page">
      {/* HEADER */}
      <div className="run-header">
        <div className="run-header-left">
          <div className="run-mode-badge">
            {session?.mode?.toUpperCase()} MODE
          </div>
          <span className="run-persona">Interviewer: {session?.persona}</span>
        </div>
        <div className="run-progress-wrap">
          <div className="run-progress-track">
            <div className="run-progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <span className="run-progress-label">
            {question ? `Q ${question.question_id} / ${question.total_questions}` : '…'}
          </span>
        </div>
      </div>

      <div className="run-body">
        {/* MAIN INTERVIEW PANEL */}
        <div className="run-main">
          {loading ? (
            <div className="run-loading">
              <span className="spinner" style={{ width: 24, height: 24, borderColor: 'rgba(232,168,56,0.2)', borderTopColor: 'var(--accent)' }} />
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text-dim)', marginLeft: 12 }}>Generating question…</span>
            </div>
          ) : (
            <>
              <div className="question-meta">
                Technical Question
                <span className="qm-sep">·</span>
                <span className="qm-id">#{question?.question_id}</span>
              </div>

              <div className="question-text">
                {question?.question}
              </div>

              {/* ANSWER AREA */}
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
                    <button className="dont-know-btn" onClick={handleDontKnow} disabled={submitting}>
                      I don't know →
                    </button>
                    <button className="submit-btn" onClick={() => handleSubmit()} disabled={submitting || !answer.trim()}>
                      {submitting
                        ? <><span className="spinner" /> Evaluating…</>
                        : <>Submit Answer ↵</>
                      }
                    </button>
                  </div>
                </div>
              )}

              {/* EVALUATION RESULT */}
              {evaluation && (
                <div className="eval-panel">
                  <div className="eval-header">
                    <div className="eval-title">
                      {evaluation.is_dont_know ? '📝 Knowledge Gap Recorded' : '✅ Answer Evaluated'}
                    </div>
                    <div className="eval-score" style={{ color: scoreColor(evaluation.overall_score) }}>
                      {evaluation.overall_score.toFixed(1)}<span className="eval-score-max">/5.0</span>
                    </div>
                  </div>

                  {!evaluation.is_dont_know && (
                    <div className="eval-scores-row">
                      {[
                        ['Technical', evaluation.technical_score],
                        ['Clarity', evaluation.clarity_score],
                        ['Confidence', evaluation.confidence_score],
                      ].map(([label, score]) => (
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

                  {evaluation.interview_complete ? (
                    <div className="eval-done">
                      <span className="spinner" style={{ width: 16, height: 16, borderColor: 'rgba(232,168,56,0.3)', borderTopColor: 'var(--accent)' }} />
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text-dim)', marginLeft: 10 }}>
                        Interview complete — generating your report…
                      </span>
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

        {/* SIDEBAR */}
        <div className="run-sidebar">
          {/* Session Info */}
          <div className="sidebar-card">
            <div className="sidebar-label">Session</div>
            <div className="sidebar-session-id">{session?.session_id}</div>
          </div>

          {/* Running Average */}
          {avgScore && (
            <div className="sidebar-card">
              <div className="sidebar-label">Running Average</div>
              <div className="sidebar-big-score" style={{ color: scoreColor(parseFloat(avgScore)) }}>
                {avgScore}
                <span style={{ fontSize: 16, color: 'var(--text-muted)', fontFamily: 'var(--sans)', fontWeight: 300 }}>/5.0</span>
              </div>
            </div>
          )}

          {/* Candidate Skills */}
          {session?.resume_summary?.skills && (
            <div className="sidebar-card">
              <div className="sidebar-label">Candidate Skills</div>
              <div className="topic-chips">
                {session.resume_summary.skills.slice(0, 10).map(s => (
                  <span className="chip" key={s}>{s}</span>
                ))}
              </div>
            </div>
          )}

          {/* JD Required Skills */}
          {session?.jd_summary?.required_skills && (
            <div className="sidebar-card">
              <div className="sidebar-label">JD Requirements</div>
              <div className="topic-chips">
                {session.jd_summary.required_skills.slice(0, 8).map(s => (
                  <span className="chip active" key={s}>{s}</span>
                ))}
              </div>
            </div>
          )}

          {/* Q&A History */}
          {qaHistory.length > 0 && (
            <div className="sidebar-card">
              <div className="sidebar-label">Question History</div>
              <div className="history-list">
                {qaHistory.map((qa, i) => (
                  <div className="history-item" key={i}>
                    <div className="history-q">Q{qa.question_id}: {qa.question.slice(0, 60)}…</div>
                    <div className="history-score" style={{ color: scoreColor(qa.overall_score) }}>
                      {qa.overall_score.toFixed(1)}
                    </div>
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
