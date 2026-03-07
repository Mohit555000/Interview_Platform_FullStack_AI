import { useState } from 'react'
import './ApiKeyDialog.css'

const PROVIDERS = [
  {
    id: 'openai',
    name: 'OpenAI',
    models: ['gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    placeholder: 'sk-...',
    hint: 'Find your key at platform.openai.com/api-keys',
    color: '#10a37f',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    models: ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5-20251001'],
    placeholder: 'sk-ant-...',
    hint: 'Find your key at console.anthropic.com/settings/keys',
    color: '#d4622a',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    models: ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash'],
    placeholder: 'AIza...',
    hint: 'Find your key at aistudio.google.com/app/apikey',
    color: '#4285f4',
  },
]

export default function ApiKeyDialog({ onConfirm, onSkip }) {
  const [selectedProvider, setSelectedProvider] = useState('openai')
  const [selectedModel, setSelectedModel] = useState(PROVIDERS[0].models[0])
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState('')

  const provider = PROVIDERS.find(p => p.id === selectedProvider)

  const handleProviderChange = (id) => {
    setSelectedProvider(id)
    setSelectedModel(PROVIDERS.find(p => p.id === id).models[0])
    setApiKey('')
    setError('')
  }

  const handleConfirm = () => {
    if (!apiKey.trim()) {
      setError('Please enter your API key.')
      return
    }
    if (selectedProvider === 'openai' && !apiKey.startsWith('sk-')) {
      setError('OpenAI keys start with sk-')
      return
    }
    if (selectedProvider === 'anthropic' && !apiKey.startsWith('sk-ant-')) {
      setError('Anthropic keys start with sk-ant-')
      return
    }
    if (selectedProvider === 'gemini' && !apiKey.startsWith('AIza')) {
      setError('Gemini keys start with AIza')
      return
    }
    onConfirm({ provider: selectedProvider, model: selectedModel, apiKey })
  }

  return (
    <div className="akd-overlay">
      <div className="akd-modal">

        {/* HEADER */}
        <div className="akd-header">
          <div className="akd-icon">🔑</div>
          <div>
            <div className="akd-title">Connect Your LLM</div>
            <div className="akd-subtitle">
              Your key is used only for this session and never stored.
            </div>
          </div>
        </div>

        {/* PROVIDER SELECTOR */}
        <div className="akd-section-label">Provider</div>
        <div className="akd-providers">
          {PROVIDERS.map(p => (
            <button
              key={p.id}
              className={`akd-provider-btn ${selectedProvider === p.id ? 'active' : ''}`}
              style={{ '--provider-color': p.color }}
              onClick={() => handleProviderChange(p.id)}
            >
              <span className="akd-provider-dot" />
              {p.name}
            </button>
          ))}
        </div>

        {/* MODEL SELECTOR */}
        <div className="akd-section-label">Model</div>
        <div className="akd-model-grid">
          {provider.models.map(m => (
            <button
              key={m}
              className={`akd-model-btn ${selectedModel === m ? 'active' : ''}`}
              onClick={() => setSelectedModel(m)}
            >
              {m}
            </button>
          ))}
        </div>

        {/* API KEY INPUT */}
        <div className="akd-section-label">API Key</div>
        <div className="akd-key-wrap">
          <input
            className="akd-key-input"
            type={showKey ? 'text' : 'password'}
            placeholder={provider.placeholder}
            value={apiKey}
            onChange={e => { setApiKey(e.target.value); setError('') }}
            onKeyDown={e => e.key === 'Enter' && handleConfirm()}
            autoComplete="off"
            spellCheck={false}
          />
          <button className="akd-toggle-visibility" onClick={() => setShowKey(v => !v)}>
            {showKey ? '🙈' : '👁'}
          </button>
        </div>
        <div className="akd-hint">{provider.hint}</div>

        {error && <div className="akd-error">⚠ {error}</div>}

        {/* SECURITY NOTE */}
        <div className="akd-security">
          <span className="akd-security-icon">🔒</span>
          <span>
            Your key is held in memory only for this session.
            It is never logged, stored, or sent anywhere except directly to {provider.name}'s API.
          </span>
        </div>

        {/* ACTIONS */}
        <div className="akd-actions">
          <button className="akd-skip" onClick={onSkip}>
            Use platform default
          </button>
          <button className="akd-confirm btn-primary" onClick={handleConfirm}>
            Connect & Continue →
          </button>
        </div>

      </div>
    </div>
  )
}