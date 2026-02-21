import { useNavigate, useLocation } from 'react-router-dom'
import './Nav.css'

export default function Nav() {
  const navigate = useNavigate()
  const location = useLocation()
  const isHome = location.pathname === '/'

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
      <button className="nav-cta" onClick={() => {
        if (isHome) {
          document.getElementById('start')?.scrollIntoView({ behavior: 'smooth' })
        } else {
          navigate('/')
        }
      }}>
        {isHome ? 'Start Interview' : '← Home'}
      </button>
    </nav>
  )
}
