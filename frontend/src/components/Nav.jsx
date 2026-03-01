import { useNavigate, useLocation } from 'react-router-dom'
import './Nav.css'

export default function Nav() {
  const navigate = useNavigate()
  const location = useLocation()
  const isHome = location.pathname === '/'
  const handleHome = () => {
  const activeSession = sessionStorage.getItem('interviewSession')
  if (activeSession && location.pathname !== '/') {
    const confirmed = window.confirm(
      'Going home will end your current session and clear all data. Are you sure?'
    )
    if (!confirmed) return
    
    // Trigger cleanup before leaving
    const sess = JSON.parse(activeSession)
    fetch(`/api/session/${sess.session_id}`, { method: 'DELETE' })
      .finally(() => {
        sessionStorage.removeItem('interviewSession')
        navigate('/')
      })
  } else {
    navigate('/')
  }
}

  return (
    <nav className="nav">
      <div className="nav-logo" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
        <span className="dot" />
        InterviewAI
      </div>
      {isHome && (
        <ul className="nav-links">
          <li><a href="#how">How It Works</a></li>
          <li><a href="#features">Features</a></li>
          <li><a href="#start">Start</a></li>
        </ul>
      )}
      <button className="nav-cta" onClick={isHome
  ? () => document.getElementById('start')?.scrollIntoView({ behavior: 'smooth' })
  : handleHome
}>
  {isHome ? 'Start Interview' : '← Home'}
</button>
    </nav>
  )
}
