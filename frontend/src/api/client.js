import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getLlmHeaders = (apiKey = null) => {
  const raw = sessionStorage.getItem('llmConfig')
  const config = raw ? JSON.parse(raw) : {}
  return {
    'X-LLM-Provider': config.provider || 'openai',
    'X-LLM-Model': config.model || '',
    ...(apiKey ? { 'X-LLM-API-Key': apiKey } : {}),
  }
}

/**
 * Start a new interview session.
 * llmConfig = { provider, model, apiKey } or null for platform default.
 * customDuration = number (minutes) or null for preset duration.
 */
export const startSession = async (resumeFile, jdText, mode, llmConfig = null, customDuration = null) => {
  const form = new FormData()
  form.append('resume', resumeFile)
  form.append('jd_text', jdText)
  form.append('mode', mode)

  // V2: pass custom duration if provided
  if (customDuration) {
    form.append('custom_duration', String(customDuration))
  }

  if (llmConfig) {
    form.append('llm_provider', llmConfig.provider)
    form.append('llm_model', llmConfig.model)
    form.append('llm_api_key', llmConfig.apiKey)
  }

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

/**
 * V2: End interview (timer expired or user clicked End).
 * Triggers report pre-generation on backend.
 */
export const endInterview = async (sessionId) => {
  const { data } = await api.post(`/session/${sessionId}/end`)
  return data
}

/** Delete session data from DB (called from Nav / Report cleanup) */
export const endSession = async (sessionId) => {
  const { data } = await api.delete(`/session/${sessionId}`)
  return data
}