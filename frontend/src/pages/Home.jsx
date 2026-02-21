import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import './Home.css'

const FEATURES = [
  { icon: '🧠', title: 'LangGraph State Machine', desc: 'Interview flow orchestrated via a directed graph with conditional edges — adapting dynamically based on performance at each step.', tag: 'LangGraph' },
  { icon: '📄', title: 'LLM Resume & JD Parsing', desc: 'Automatically extracts structured data from unstructured resume PDFs and job descriptions using GPT-4o-mini with JSON output parsing.', tag: 'OpenAI · PyPDF2' },
  { icon: '🎯', title: 'Adaptive Difficulty', desc: "When a candidate scores below 3.0, the engine generates a follow-up question on the same topic at lower difficulty — building confidence progressively.", tag: 'Adaptive AI' },
  { icon: '🛑', title: "Don't-Know Detection", desc: "Lexical matching catches 'I don't know', 'not sure', 'pass' — skipping re-prompts and logging a 1.0/5.0 score without penalizing the flow.", tag: 'NLP · Pattern Matching' },
  { icon: '🕸️', title: 'Graph Database Tracking', desc: 'Neo4j maps skills, weaknesses, and improvements as a graph. Every Q&A creates nodes and relationships for nuanced final report generation.', tag: 'Neo4j' },
  { icon: '🔍', title: 'Semantic Search Context', desc: 'Qdrant vector store indexes resume skills, JD requirements, and past Q&As. Semantic search ensures relevant topics are covered without repetition.', tag: 'Qdrant · Embeddings' },
]

const TECH = ['Python 3.11','LangChain','LangGraph','OpenAI GPT-4o-mini','text-embedding-3-small','Qdrant Vector DB','Neo4j Graph DB','PyPDF2','Pydantic v2','FastAPI','React + Vite','Docker']

export default function Home() {
  const navigate = useNavigate()
  const revealRefs = useRef([])

  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target) } }),
      { threshold: 0.1 }
    )
    revealRefs.current.forEach(el => el && obs.observe(el))
    return () => obs.disconnect()
  }, [])

  const addRef = el => { if (el && !revealRefs.current.includes(el)) revealRefs.current.push(el) }

  return (
    <div className="home">
      {/* HERO */}
      <section className="hero">
        <div className="hero-grid" />
        <div className="hero-glow" />
        <div className="hero-content">
          <div className="hero-badge"><span className="dot" style={{width:6,height:6}} />AI-Powered Technical Interviewing</div>
          <h1 className="hero-title">Smarter interviews.<br /><em>Sharper insights.</em></h1>
          <p className="hero-sub">
            An intelligent interview platform that adapts to your candidate in real-time — parsing resumes, generating contextual questions, evaluating answers, and producing detailed performance reports.
          </p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => navigate('/interview')}>
              Run Interview <span>→</span>
            </button>
            <a href="#how" className="btn-ghost">See How It Works</a>
          </div>
        </div>
      </section>

      {/* STATS */}
      <div className="stats-strip">
        {[['4','Evaluation Dimensions'],['2','Interview Modes'],['∞','Adaptive Questions'],['1','Click to Start']].map(([n,l],i) => (
          <div className="stat-item reveal" ref={addRef} key={i} style={{ transitionDelay: `${i*0.1}s` }}>
            <span className="stat-num">{n}</span>
            <span className="stat-label">{l}</span>
          </div>
        ))}
      </div>

      {/* HOW IT WORKS */}
      <section id="how" className="how-section">
        <div className="reveal" ref={addRef}>
          <div className="section-label">Process</div>
          <h2 className="section-title">From resume to<br />report in minutes</h2>
        </div>
        <div className="how-grid">
          <div className="steps-list">
            {[
              { n:'01', title:'Upload Resume + Job Description', desc:'Drop your candidate\'s PDF resume and paste the job description. The system extracts skills, experience, and requirements using LLM parsing.' },
              { n:'02', title:'Adaptive Question Generation', desc:'LangGraph orchestrates a state machine that generates contextual questions tailored to the candidate\'s profile and JD requirements — covering gaps intelligently.' },
              { n:'03', title:'Real-time Answer Evaluation', desc:'Every answer is scored across Technical Accuracy, Clarity, Confidence, and Problem-Solving. "I don\'t know" responses are detected and handled gracefully.' },
              { n:'04', title:'Comprehensive Report', desc:'Neo4j tracks weaknesses, Qdrant indexes context. A final LLM-generated report details strengths, gaps, and concrete study recommendations.' },
            ].map((s, i) => (
              <div className="step" key={i}>
                <span className="step-num">{s.n}</span>
                <div className="step-content">
                  <h3>{s.title}</h3>
                  <p>{s.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="terminal">
            <div className="terminal-bar">
              <div className="terminal-dot td-red" /><div className="terminal-dot td-yellow" /><div className="terminal-dot td-green" />
              <span className="terminal-title">interview_platform.py</span>
            </div>
            <div className="terminal-body">
              <div className="t-line"><span className="t-prompt">$</span><span className="t-cmd"> python interview_platform.py --resume alex.pdf --jd job.txt</span></div>
              <br/>
              <div className="t-line"><span className="t-output">🤖 AI-POWERED INTERVIEW PLATFORM — V1.0</span></div>
              <br/>
              <div className="t-line"><span className="t-output">📄 Parsing resume...</span></div>
              <div className="t-line"><span className="t-success">✓ Found 14 skills, 4 years experience</span></div>
              <div className="t-line"><span className="t-output">📋 Analyzing job requirements...</span></div>
              <div className="t-line"><span className="t-success">✓ Identified 8 required skills</span></div>
              <br/>
              <div className="t-line"><span className="t-output">Q3: HashMap vs TreeMap differences?</span></div>
              <div className="t-line"><span className="t-output">Answer: I don't know.</span></div>
              <br/>
              <div className="t-line"><span className="t-output">📝 Noted — knowledge gap recorded.</span></div>
              <div className="t-line"><span className="t-score">✓ Score: 1.0/5.0</span></div>
              <br/>
              <div className="t-line"><span className="t-output">📊 Overall: <span className="t-score">3.7/5.0</span> · Report generated.</span></div>
              <div className="t-line"><span className="t-output">▌<span className="cursor" /></span></div>
            </div>
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section id="features" className="features-section">
        <div className="features-inner">
          <div className="features-header reveal" ref={addRef}>
            <div>
              <div className="section-label">Capabilities</div>
              <h2 className="section-title">Built for real<br />technical depth</h2>
            </div>
            <p className="section-desc">Every component was designed with a specific problem in mind — from off-topic detection to adaptive difficulty scaling.</p>
          </div>
          <div className="features-grid">
            {FEATURES.map((f, i) => (
              <div className="feature-card reveal" ref={addRef} key={i} style={{ transitionDelay: `${i*0.05}s` }}>
                <div className="feature-icon">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
                <span className="feature-tag">{f.tag}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* START CTA */}
      <section id="start" className="cta-section">
        <div className="cta-glow" />
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div className="section-label" style={{ justifyContent: 'center' }}>Get Started</div>
          <h2 className="section-title" style={{ textAlign: 'center', margin: '0 auto 20px' }}>Ready to run<br />your first interview?</h2>
          <p className="section-desc" style={{ textAlign: 'center', margin: '0 auto 40px' }}>Upload a resume and job description. The AI handles the rest — questions, evaluation, and a full performance report.</p>
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="btn-primary" onClick={() => navigate('/interview')}>Start Interview →</button>
          </div>
        </div>
      </section>

      {/* TECH STACK */}
      <section className="tech-section">
        <div className="reveal" ref={addRef}>
          <div className="section-label">Stack</div>
          <h2 className="section-title">Built on solid<br />foundations</h2>
        </div>
        <div className="tech-grid reveal" ref={addRef}>
          {TECH.map(t => <span className="tech-pill" key={t}>{t}</span>)}
        </div>
      </section>

      {/* FOOTER */}
      <footer className="footer">
        <span className="footer-logo">InterviewAI · v1.0</span>
        <span className="footer-copy">Built with LangGraph · Qdrant · Neo4j · FastAPI · React</span>
      </footer>
    </div>
  )
}
