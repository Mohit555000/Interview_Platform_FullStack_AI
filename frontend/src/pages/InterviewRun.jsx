import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { getCurrentQuestion, submitAnswer, endInterview, transcribeAudio, speakText } from '../api/client'
import './InterviewRun.css'

const fmt = (s) => {
  const m = Math.floor(Math.abs(s) / 60)
  const sec = Math.abs(s) % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

const TRANSITIONS = [
  "Okay, let's move to the next question.",
  "Got it. Here's the next one.",
  "Thank you. Moving on.",
  "Alright, next question.",
  "Good. Let's continue.",
]

// ── Modern animated indicators (no emojis) ────────────────────────
function OrbIndicator({ state }) {
  return (
    <div className={`voice-orb ${state}`}>
      {/* Listening: pulse rings */}
      {state === 'listening' && (
        <div className="orb-listening">
          <div className="pulse-ring r1" />
          <div className="pulse-ring r2" />
          <div className="pulse-ring r3" />
          <div className="mic-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/>
              <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
          </div>
        </div>
      )}

      {/* Speaking: sound wave bars */}
      {state === 'speaking' && (
        <div className="orb-speaking">
          {[1,2,3,4,5].map(i => (
            <div key={i} className={`wave-bar b${i}`} />
          ))}
        </div>
      )}

      {/* Thinking: rotating arc */}
      {state === 'thinking' && (
        <div className="orb-thinking">
          <svg viewBox="0 0 50 50" className="think-spinner">
            <circle cx="25" cy="25" r="20" fill="none" stroke="currentColor" strokeWidth="3"
              strokeLinecap="round" strokeDasharray="80 40" />
          </svg>
        </div>
      )}

      {/* Idle: static circle */}
      {state === 'idle' && (
        <div className="orb-idle">
          <div className="idle-dot" />
        </div>
      )}
    </div>
  )
}

export default function InterviewRun() {
  const navigate = useNavigate()
  const [session, setSession]         = useState(null)
  const [transcript, setTranscript]   = useState('')
  const [aiState, setAiState]         = useState('idle')
  const [qaHistory, setQaHistory]     = useState([])
  const [error, setError]             = useState('')
  const [questionNum, setQuestionNum] = useState(0)

  // Timer
  const [elapsed, setElapsed]           = useState(0)
  const [totalSecs, setTotalSecs]       = useState(0)
  const [warningLevel, setWarningLevel] = useState(null)

  // Refs
  const timerRef            = useRef(null)
  const mediaRecorderRef    = useRef(null)
  const audioChunksRef      = useRef([])
  const analyserRef         = useRef(null)
  const animFrameRef        = useRef(null)
  const streamRef           = useRef(null)
  const warningSpokenRef    = useRef({ warning: false, critical: false })
  const timerExpiredRef     = useRef(false)
  const sessionRef          = useRef(null)
  const questionRef         = useRef(null)
  const qaHistoryRef        = useRef([])
  const aiStateRef          = useRef('idle')
  const isRecordingRef      = useRef(false)
  const hasBootedRef        = useRef(false)
  // ── Fix 1: track if currently in the middle of answering ─────────
  const isAnsweringRef      = useRef(false)
  const lastWarningLevelRef = useRef(null)

  const setAiStateSynced = useCallback((s) => {
    aiStateRef.current = s
    setAiState(s)
  }, [])

  // ── TTS ──────────────────────────────────────────────────────────
  const speak = useCallback(async (text) => {
    setAiStateSynced('speaking')
    try {
      const audioBlob = await speakText(text)
      const url = URL.createObjectURL(audioBlob)
      await new Promise((resolve) => {
        const audio = new Audio(url)
        audio.onended = () => { URL.revokeObjectURL(url); resolve() }
        audio.onerror = () => { URL.revokeObjectURL(url); resolve() }
        audio.play().catch(resolve)
      })
    } catch (err) {
      console.error('TTS error:', err)
    }
  }, [setAiStateSynced])

  // ── Silence detection ────────────────────────────────────────────
  const startSilenceDetection = useCallback((stream, onSilence) => {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    const source   = audioCtx.createMediaStreamSource(stream)
    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 512
    source.connect(analyser)
    analyserRef.current = analyser

    const data = new Uint8Array(analyser.frequencyBinCount)
    let silenceStart = null
    const SILENCE_THRESHOLD = 10
    const SILENCE_DURATION  = 5000

    const check = () => {
      if (!isRecordingRef.current) return
      analyser.getByteTimeDomainData(data)
      const rms = Math.sqrt(data.reduce((s, v) => s + (v - 128) ** 2, 0) / data.length)
      if (rms < SILENCE_THRESHOLD) {
        if (!silenceStart) silenceStart = Date.now()
        else if (Date.now() - silenceStart >= SILENCE_DURATION) {
          isRecordingRef.current = false
          audioCtx.close()
          onSilence()
          return
        }
      } else {
        silenceStart = null
      }
      animFrameRef.current = requestAnimationFrame(check)
    }
    animFrameRef.current = requestAnimationFrame(check)
  }, [])

  // ── Submit answer ────────────────────────────────────────────────
  const handleVoiceSubmit = useCallback(async (text) => {
    isAnsweringRef.current = false   // done answering
    setAiStateSynced('thinking')
    try {
      const sess = sessionRef.current
      const result = await submitAnswer(sess.session_id, text)
      const newEntry = { question: questionRef.current?.question, answer: text, ...result }
      const updated  = [...qaHistoryRef.current, newEntry]
      qaHistoryRef.current = updated
      setQaHistory(updated)

      // ── Fix 1: check timer AFTER submitting answer ────────────────
      // If timer expired while user was answering, wrap up now
      if (timerExpiredRef.current) {
        await speak("Thank you for your time. I'll now generate your interview report.")
        await endInterview(sess.session_id)
        navigate('/interview/report')
        return
      }

      // ── Speak warning between questions (not mid-answer) ──────────
      if (lastWarningLevelRef.current === 'critical' && !warningSpokenRef.current.criticalSpoken) {
        warningSpokenRef.current.criticalSpoken = true
        await speak("We're in the final stage. This will be our last question.")
      }

      const transition = TRANSITIONS[Math.floor(Math.random() * TRANSITIONS.length)]
      await speak(transition)
      await loadAndSpeakNextQuestion()

    } catch (err) {
      console.error('Submit error:', err)
      setError('Something went wrong. Listening again...')
      await new Promise(r => setTimeout(r, 2000))
      setError('')
      isAnsweringRef.current = true
      await startListening()
    }
  }, [speak, navigate, setAiStateSynced])

  // ── Start listening ──────────────────────────────────────────────
  const startListening = useCallback(async () => {
    setTranscript('')
    audioChunksRef.current = []
    setAiStateSynced('listening')
    isAnsweringRef.current = true   // user is now answering

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      isRecordingRef.current = true

      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data)
      }

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        try {
          const sess = sessionRef.current
          const result = await transcribeAudio(sess.session_id, blob)
          const text = result.transcript?.trim()
          if (!text) {
            await speak("I didn't catch that. Could you please repeat your answer?")
            isAnsweringRef.current = true
            await startListening()
            return
          }
          setTranscript(text)
          await handleVoiceSubmit(text)
        } catch (err) {
          console.error('Transcription error:', err)
          setError('Having trouble hearing you. Please speak again.')
          await speak("Sorry, I had trouble hearing that. Please try again.")
          setError('')
          isAnsweringRef.current = true
          await startListening()
        }
      }

      mediaRecorder.start(100)
      startSilenceDetection(stream, () => {
        if (mediaRecorder.state !== 'inactive') mediaRecorder.stop()
      })

    } catch (err) {
      setError('Microphone access denied. Please allow microphone and refresh.')
      setAiStateSynced('idle')
    }
  }, [setAiStateSynced, speak, startSilenceDetection, handleVoiceSubmit])

  // ── Load + speak next question ───────────────────────────────────
  const loadAndSpeakNextQuestion = useCallback(async () => {
    try {
      const sess = sessionRef.current
      const q = await getCurrentQuestion(sess.session_id)
      questionRef.current = q
      setQuestionNum(q.question_id)
      setTranscript('')
      await speak(q.question)
      await startListening()
    } catch (err) {
      setError('Failed to load next question.')
    }
  }, [speak, startListening])

  // ── Timer ─────────────────────────────────────────────────────────
  const startTimer = useCallback((durationMinutes) => {
    const total = durationMinutes * 60
    setTotalSecs(total)
    timerRef.current = setInterval(() => {
      setElapsed(prev => {
        const next = prev + 1
        if (next >= total) {
          clearInterval(timerRef.current)
          timerExpiredRef.current = true
          return total
        }
        return next
      })
    }, 1000)
  }, [])

  // ── Warning thresholds — Fix 1: never interrupt mid-answer ───────
  useEffect(() => {
    if (!totalSecs) return
    const pct = elapsed / totalSecs

    if (pct >= 0.95 && !warningSpokenRef.current.critical) {
      warningSpokenRef.current.critical = true
      lastWarningLevelRef.current = 'critical'
      setWarningLevel('critical')
      // Only interrupt if NOT currently answering
      // If answering, warning will be spoken after the answer is submitted
      if (!isAnsweringRef.current && aiStateRef.current !== 'thinking') {
        speak("We're almost out of time. This will be our last question.").then(() => {
          loadAndSpeakNextQuestion()
        })
      }
    } else if (pct >= 0.80 && !warningSpokenRef.current.warning) {
      warningSpokenRef.current.warning = true
      lastWarningLevelRef.current = 'warning'
      setWarningLevel('warning')
    }
  }, [elapsed, totalSecs])

  // ── Boot ──────────────────────────────────────────────────────────
  useEffect(() => {
    const raw = sessionStorage.getItem('interviewSession')
    if (!raw) { navigate('/interview'); return }
    const sess = JSON.parse(raw)
    setSession(sess)
    sessionRef.current = sess
    startTimer(sess.duration)

    const boot = async () => {
      if (hasBootedRef.current) return
      hasBootedRef.current = true
      const persona = sess.persona || 'your interviewer'
      await speak(`Hello! I'm your ${persona} today. Let's begin the interview.`)
      await loadAndSpeakNextQuestion()
    }
    boot()

    return () => {
      clearInterval(timerRef.current)
      cancelAnimationFrame(animFrameRef.current)
      isRecordingRef.current = false
      streamRef.current?.getTracks().forEach(t => t.stop())
    }
  }, [])

  // ── Derived ───────────────────────────────────────────────────────
  const remaining   = Math.max(totalSecs - elapsed, 0)
  const progressPct = totalSecs ? Math.min((elapsed / totalSecs) * 100, 100) : 0
  const timerColor  = warningLevel === 'critical' ? 'var(--red)'
    : warningLevel === 'warning' ? '#f59e0b' : 'var(--text)'

  const stateLabel = {
    speaking:  'AI Speaking',
    listening: 'Listening',
    thinking:  'Analyzing',
    idle:      'Starting',
  }[aiState] || 'Starting'

  const avgScore   = qaHistory.length
    ? (qaHistory.reduce((a, b) => a + b.overall_score, 0) / qaHistory.length).toFixed(1)
    : null
  const scoreColor = (s) => s >= 4 ? 'var(--green)' : s >= 3 ? 'var(--accent)' : 'var(--red)'

  return (
    <div className="run-page voice-mode">

      {/* HEADER */}
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
              <div className={`run-timer-fill ${warningLevel || ''}`} style={{ width: `${progressPct}%` }} />
            </div>
          </div>
          <div className="run-timer-block">
            <div className="run-timer-label">Remaining</div>
            <div className="run-timer-val" style={{ color: timerColor }}>{fmt(remaining)}</div>
          </div>
        </div>
        <div className={`voice-state-badge ${aiState}`}>
          <span className="vsb-dot" />
          {stateLabel}
        </div>
      </div>

      {/* WARNING BANNERS */}
      {warningLevel === 'critical' && (
        <div className="timer-banner critical">Final question — wrapping up soon.</div>
      )}
      {warningLevel === 'warning' && warningLevel !== 'critical' && (
        <div className="timer-banner warning">Interview entering final stage — {fmt(remaining)} remaining.</div>
      )}

      {/* VOICE STAGE — no question text on screen */}
      <div className="voice-stage">
        <div className="voice-center">
              {/* Question text */}
    {question && (
      <div className="voice-question-text">
        {question.question}
      </div>
    )}

          <OrbIndicator state={aiState} />

          <div className={`voice-state-label ${aiState}`}>{stateLabel}</div>

          {/* Live transcript */}
          {transcript && (
            <div className="voice-transcript">
              <div className="voice-transcript-label">Your answer</div>
              <div className="voice-transcript-text">{transcript}</div>
            </div>
          )}

          {questionNum > 0 && (
            <div className="voice-qnum">Question {questionNum}</div>
          )}

          {error && (
            <div className="run-error" style={{ maxWidth: 480, textAlign: 'center' }}>⚠️ {error}</div>
          )}
        </div>
      </div>

      {/* SCORE STRIP */}
      {qaHistory.length > 0 && (
        <div className="voice-score-strip">
          <span className="voice-score-label">Questions answered: {qaHistory.length}</span>
          {avgScore && (
            <span className="voice-score-avg" style={{ color: scoreColor(parseFloat(avgScore)) }}>
              Avg: {avgScore}/5.0
            </span>
          )}
          <div className="voice-score-dots">
            {qaHistory.slice(-8).map((qa, i) => (
              <div key={i} className="voice-score-dot"
                style={{ background: scoreColor(qa.overall_score) }}
                title={`Q${qa.question_id}: ${qa.overall_score}/5`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}