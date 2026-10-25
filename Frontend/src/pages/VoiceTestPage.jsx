import { useState } from 'react'
import '../voice/legacy.css'
import { DEFAULT_VOICE_URL, LANGUAGES, MAX_TEXT_CHARS, validateVoiceUrl } from '../voice/voiceProtocol.js'
import { useVoiceClient } from '../voice/useVoiceClient.js'

const VOICE_URL = import.meta.env.VITE_VOICE_AGENT_WS_URL || DEFAULT_VOICE_URL

const PHASE_LABELS = {
  idle: 'Ready',
  'requesting-mic': 'Waiting for microphone permission…',
  connecting: 'Connecting…',
  listening: 'Listening… press Stop when you finish speaking',
  processing: 'Thinking and speaking…',
  done: 'Done',
  error: 'Something went wrong',
}

const SEGMENT_LABELS = {
  receiving: 'receiving',
  ready: 'queued',
  playing: 'playing',
  played: 'played',
  skipped: 'skipped',
}

function formatMs(value) {
  return value == null ? '-' : `${Math.round(value)} ms`
}

export default function VoiceTestPage() {
  const urlCheck = validateVoiceUrl(VOICE_URL)
  const { state, busy, speaking, start, stop, cancel, sendText, newConversation } = useVoiceClient(urlCheck.ok ? urlCheck.url : '')
  const [language, setLanguage] = useState('hinglish')
  const [mode, setMode] = useState('speak') // 'speak' | 'text': what the last Start / Send was
  const [typed, setTyped] = useState('')

  const canStop = mode === 'speak' && (state.phase === 'listening' || state.phase === 'connecting')
  const segmentIndexes = Object.keys(state.segments).map(Number).sort((a, b) => a - b)
  const disabled = !urlCheck.ok

  function handleStart() {
    setMode('speak')
    start(language)
  }

  function handleSend(event) {
    event.preventDefault()
    if (!typed.trim()) return
    setMode('text')
    sendText(typed, language)
    setTyped('')
  }

  return (
    <div className="legacy-voice">
    <main className="page">
      <header className="page-header">
        <h1>AwaazAI voice test</h1>
        <p className="muted">
          Speak, and the assistant answers in text and voice. Local development page: it only connects to{' '}
          <code>{VOICE_URL}</code>.
        </p>
      </header>

      {!urlCheck.ok && (
        <p className="banner banner-error" role="alert">
          {urlCheck.reason}
        </p>
      )}

      <section className="controls" aria-label="Controls">
        <label className="field">
          <span>Language</span>
          <select value={language} onChange={(event) => setLanguage(event.target.value)} disabled={busy}>
            {LANGUAGES.map((name) => (
              <option key={name} value={name}>
                {name[0].toUpperCase() + name.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <div className="buttons">
          <button type="button" className="primary" onClick={handleStart} disabled={disabled || busy}>
            Start
          </button>
          <button type="button" onClick={stop} disabled={!canStop}>
            Stop
          </button>
          <button type="button" onClick={cancel} disabled={!busy && !speaking}>
            Cancel
          </button>
          <button type="button" className="subtle" onClick={newConversation} disabled={busy || (!state.sessionId && state.phase === 'idle')}>
            New conversation
          </button>
        </div>
        <p className={`status status-${state.phase}`} role="status" aria-live="polite">
          <span className="dot" aria-hidden="true" />
          {PHASE_LABELS[state.phase]}
          {speaking && state.phase !== 'processing' ? ' · playing reply' : ''}
        </p>
      </section>

      {state.error && (
        <p className="banner banner-error" role="alert">
          <strong>{state.error.stage === 'client' ? 'Error' : `Error in ${state.error.stage}`}:</strong> {state.error.message}{' '}
          <span className="muted">({state.error.code})</span>
        </p>
      )}
      {state.warnings.map((warning, index) => (
        <p className="banner banner-warn" role="status" key={index}>
          <strong>Warning ({warning.stage}):</strong> {warning.message} <span className="muted">({warning.code})</span>
        </p>
      ))}

      <form className="type-row" onSubmit={handleSend}>
        <label className="field grow">
          <span>Or type instead of speaking</span>
          <input
            type="text"
            value={typed}
            maxLength={MAX_TEXT_CHARS}
            placeholder="Namaste, kaise ho?"
            onChange={(event) => setTyped(event.target.value)}
            disabled={disabled || busy}
          />
        </label>
        <button type="submit" disabled={disabled || busy || !typed.trim()}>
          Send
        </button>
      </form>

      <div className="panels">
        <section className="panel" aria-labelledby="heard-title">
          <h2 id="heard-title">What you said</h2>
          <div className="text" aria-live="polite">
            {state.finals.map((text, index) => (
              <span key={index}>{text} </span>
            ))}
            {state.partial && <span className="partial">{state.partial}</span>}
            {state.finals.length === 0 && !state.partial && <span className="muted">Your words appear here as you speak.</span>}
          </div>
        </section>

        <section className="panel" aria-labelledby="reply-title">
          <h2 id="reply-title">Assistant reply</h2>
          <div className="text" aria-live="polite">
            {state.replyText || <span className="muted">The reply appears here as it is written.</span>}
          </div>
        </section>
      </div>

      <section className="panel" aria-labelledby="speech-title">
        <h2 id="speech-title">Speech</h2>
        {segmentIndexes.length === 0 ? (
          <p className="muted">Spoken sentences appear here and play in order, one at a time.</p>
        ) : (
          <ul className="segments">
            {segmentIndexes.map((index) => (
              <li key={index} className={`segment segment-${state.segments[index]}`}>
                Sentence {index + 1}: {SEGMENT_LABELS[state.segments[index]]}
              </li>
            ))}
          </ul>
        )}
        {state.phase === 'done' && state.audioComplete === false && (
          <p className="muted">Speech failed part-way for this reply; the text above is complete.</p>
        )}
        {state.metrics && (
          <dl className="metrics">
            <div><dt>First text</dt><dd>{formatMs(state.metrics.firstTextMs)}</dd></div>
            <div><dt>First audio</dt><dd>{formatMs(state.metrics.firstAudioMs)}</dd></div>
            <div><dt>Transcript</dt><dd>{formatMs(state.metrics.transcriptMs)}</dd></div>
            <div><dt>Total</dt><dd>{formatMs(state.metrics.totalMs)}</dd></div>
          </dl>
        )}
      </section>

      <footer className="muted small">
        The voice service has no authentication yet, so this page connects to localhost only and sends no credentials. The
        microphone is used only between Start and Stop.
      </footer>
    </main>
    </div>
  )
}
