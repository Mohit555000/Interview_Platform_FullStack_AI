import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const startSession = async (resumeFile, jdText, mode) => {
  const form = new FormData()
  form.append('resume', resumeFile)
  form.append('jd_text', jdText)
  form.append('mode', mode)
  const { data } = await api.post('/session/start', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export const getCurrentQuestion = async (sessionId) => {
  const { data } = await api.get(`/session/${sessionId}/question`)
  return data
}

export const submitAnswer = async (sessionId, answer) => {
  const { data } = await api.post(`/session/${sessionId}/answer`, { answer })
  return data
}

export const getReport = async (sessionId) => {
  const { data } = await api.get(`/session/${sessionId}/report`)
  return data
}

export const endSession = async (sessionId) => {
  await api.delete(`/session/${sessionId}`)
}
