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
 * Start session — now accepts jdFile (PDF) instead of jdText string.
 * customDuration = number (minutes) or null for preset.
 */
export const startSession = async (resumeFile, jdFile, mode, llmConfig = null, customDuration = null) => {
  const form = new FormData()
  form.append('resume', resumeFile)
  form.append('jd_file', jdFile)          // ← PDF file now
  form.append('mode', mode)
  if (customDuration) form.append('custom_duration', String(customDuration))
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

export const endInterview = async (sessionId) => {
  const { data } = await api.post(`/session/${sessionId}/end`)
  return data
}

export const endSession = async (sessionId) => {
  const { data } = await api.delete(`/session/${sessionId}`)
  return data
}

/**
 * STT: send audio blob → backend transcribes with Google Speech Recognition
 */
export const transcribeAudio = async (sessionId, audioBlob) => {
  const form = new FormData()
  form.append('audio', audioBlob, 'recording.webm')
  const { data } = await api.post(`/session/${sessionId}/transcribe`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data  // { transcript: string }
}

/**
 * TTS: send text → backend returns MP3 audio blob (OpenAI fable voice)
 */
export const speakText = async (text, sessionId) => {
  const response = await api.post('/tts', { text, session_id: sessionId }, { responseType: 'blob' })
  return response.data  // audio/mpeg blob
}