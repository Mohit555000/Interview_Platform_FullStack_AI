import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Nav from './components/Nav'
import Home from './pages/Home'
import Setup from './pages/Setup'
import InterviewRun from './pages/InterviewRun'
import Report from './pages/Report'
import './index.css'
import './pages/Home.css'

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/interview" element={<Setup />} />
        <Route path="/interview/run" element={<InterviewRun />} />
        <Route path="/interview/report" element={<Report />} />
      </Routes>
    </BrowserRouter>
  )
}
