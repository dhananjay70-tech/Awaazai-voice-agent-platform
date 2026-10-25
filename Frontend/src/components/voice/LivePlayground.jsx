import { Eraser, Mic, Play, RotateCcw, Send, Square, StopCircle, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMicrophonePermission } from '../../hooks/useMicrophonePermission.js'
import { PLAYGROUND_STATES, playgroundStateKey, turnToEntry } from '../../voice/playgroundState.js'
import { useVoiceClient } from '../../voice/useVoiceClient.js'
import { MAX_TEXT_CHARS } from '../../voice/voiceProtocol.js'
import Alert from '../ui/Alert.jsx'
import Button from '../ui/Button.jsx'
import ConfirmDialog from '../ui/ConfirmDialog.jsx'
import Tooltip from '../ui/Tooltip.jsx'

const SEGMENT_LABELS = { receiving: 'receiving', ready: 'queued', playing: 'playing', played: 'played', skipped: 'skipped' }
const MIC_LABELS = {
  granted: { text: 'Mic allowed', tone: 'badge-success' },
  denied: { text: 'Mic blocked', tone: 'badge-error' },
  prompt: { text: 'Mic: will ask', tone: 'badge-info' },
  unknown: { text: 'Mic: checked on start', tone: '' },
}

function formatMs(value) {
  return value == null ? '-' : `${Math.round(value)} ms`
}

/**
 * Live voice test: session controls, state, transcript history and the text fallback, around the existing VoiceClient.
 * `url` must already have passed validateVoiceUrl. A session is opened explicitly (never on page load); the voice client
 * connects for each turn and closes afterwards.
 */
export default function LivePlayground({ url, voiceLanguage, agentName, languageText, compact = false }) {
  const [session, setSession] = useState('closed') // closed | open | ended
  const [mode, setMode] = useState('speak')
  const [typed, setTyped] = useState('')
  const [lastText, setLastText] = useState('')
  const [history, setHistory] = useState([])
  const [confirmClear, setConfirmClear] = useState(false)
  const modeRef = useRef('speak')
  const lastTextRef = useRef('')
  const nextId = useRef(1)
  const logRef = useRef(null)

  const { state, busy, speaking, start, stop, cancel, sendText, newConversation } = useVoiceClient(url, {
    onTurnComplete: (finished) => {
      const entry = turnToEntry(finished, { mode: modeRef.current, typedText: lastTextRef.current })
      if (entry) setHistory((current) => [...current, { id: nextId.current++, ...entry }])
    },
  })
  const micPermission = useMicrophonePermission()

  const key = playgroundStateKey({ session, phase: state.phase, mode, speaking, error: state.error })
  const info = PLAYGROUND_STATES[key]
  const mic = MIC_LABELS[micPermission]
  const recording = session === 'open' && mode === 'speak' && (state.phase === 'listening' || state.phase === 'connecting')
  const open = session === 'open'
  const segmentIndexes = Object.keys(state.segments).map(Number).sort((a, b) => a - b)
  const inProgress = busy && state.phase !== 'done'

  // Keep the newest message in view.
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTop = log.scrollHeight
  }, [history, state.replyText, state.partial, state.finals])

  function startSession() {
    if (session === 'ended') setHistory([]) // a new session starts with a clean transcript
    newConversation()
    setSession('open')
  }

  function endSession() {
    newConversation() // stops any turn and sound, and forgets the server-side conversation
    setSession('ended')
  }

  function talk() {
    modeRef.current = 'speak'
    setMode('speak')
    start(voiceLanguage)
  }

  function submitText(text) {
    modeRef.current = 'text'
    setMode('text')
    lastTextRef.current = text
    setLastText(text)
    sendText(text, voiceLanguage)
  }

  function handleSend(event) {
    event.preventDefault()
    if (!typed.trim() || busy) return
    submitText(typed)
    setTyped('')
  }

  function retry() {
    if (mode === 'text' && lastText) submitText(lastText)
    else talk()
  }

  function clearTranscript() {
    setHistory([])
    setConfirmClear(false)
    newConversation()
    if (session === 'ended') setSession('closed')
  }

  const permissionDenied = key === 'permission-denied'
  const liveUser = mode === 'text' ? lastText : [...state.finals, state.partial].filter(Boolean).join(' ')

  return (
    <section className={`playground${compact ? ' is-compact' : ''}`} aria-label="Live voice playground">
      <header className="playground-head">
        <div className="playground-title">
          <strong>{agentName}</strong>
          <span className="muted">{languageText}</span>
        </div>
        <div className="playground-badges">
          <span className={`badge ${info.tone}`} role="status" aria-live="polite">
            <span className="dot" aria-hidden="true" />
            <span className="sr-only">Session state: </span>
            {info.label}
          </span>
          <span className={`badge ${mic.tone}`}>{mic.text}</span>
        </div>
      </header>

      <div className="playground-log" ref={logRef} role="log" aria-label="Conversation transcript" aria-live="polite">
        {history.length === 0 && !inProgress && <p className="muted playground-empty">{open ? 'Your conversation will appear here.' : info.detail}</p>}
        {history.map((entry) => (
          <div className="turn" key={entry.id}>
            {entry.user && (
              <div className="bubble bubble-user">
                <small>You</small>
                {entry.user}
              </div>
            )}
            {entry.agent && (
              <div className="bubble bubble-agent">
                <small>Agent</small>
                {entry.agent}
                {entry.audioComplete === false && <em className="bubble-note">Speech failed part-way; the text is complete.</em>}
              </div>
            )}
          </div>
        ))}
        {inProgress && (
          <div className="turn" aria-label="Current turn">
            {liveUser && (
              <div className="bubble bubble-user bubble-partial">
                <small>You</small>
                {liveUser}
              </div>
            )}
            {state.replyText && (
              <div className="bubble bubble-agent">
                <small>Agent</small>
                {state.replyText}
              </div>
            )}
          </div>
        )}
        {key === 'ended' && <p className="muted playground-empty">Conversation ended. The transcript above is kept until you clear it.</p>}
      </div>

      <div className="playground-footer">
        <p className="playground-detail" aria-live="polite">
          {info.detail}
        </p>

        {permissionDenied && (
          <Alert tone="error" title="Microphone access is blocked">
            Allow the microphone for this site in your browser’s address-bar settings, then press Talk again. You can still type a message.
          </Alert>
        )}
        {state.error && state.error.code !== 'permission_denied' && (
          <Alert
            tone="error"
            title={key === 'disconnected' ? 'Disconnected' : state.error.stage === 'client' ? 'Connection problem' : `Error in ${state.error.stage}`}
            meta={`${state.error.code}${state.error.requestId ? ` · Request ID: ${state.error.requestId}` : ''}`}
          >
            {state.error.message}
          </Alert>
        )}
        {state.warnings.map((warning, index) => (
          <Alert key={index} tone="warning" title={`Warning (${warning.stage})`} meta={warning.code}>
            {warning.message}
          </Alert>
        ))}

        {!open ? (
          <div className="playground-actions">
            <Button variant="primary" icon={Play} onClick={startSession}>
              {session === 'ended' ? 'Start new session' : 'Start session'}
            </Button>
            {history.length > 0 && (
              <Button variant="ghost" icon={Eraser} onClick={() => setConfirmClear(true)}>
                Clear transcript
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="playground-actions">
              {recording ? (
                <button type="button" className="mic-button is-recording" onClick={stop}>
                  <Square size={16} aria-hidden="true" /> Stop
                </button>
              ) : (
                <button type="button" className="mic-button" onClick={talk} disabled={busy}>
                  <Mic size={16} aria-hidden="true" /> Talk
                </button>
              )}
              {(state.error || state.phase === 'error') && (
                <Button icon={RotateCcw} onClick={retry}>
                  Retry
                </Button>
              )}
              <Button icon={X} onClick={cancel} disabled={!busy && !speaking}>
                Cancel turn
              </Button>
              <Tooltip text="Clear transcript" side="bottom">
                <Button variant="ghost" icon={Eraser} aria-label="Clear transcript" onClick={() => setConfirmClear(true)} disabled={history.length === 0 && !busy} />
              </Tooltip>
              <Button variant="ghost" icon={StopCircle} onClick={endSession}>
                End session
              </Button>
            </div>
            <form className="text-form" onSubmit={handleSend}>
              <div className="field">
                <label className="field-label" htmlFor={`typed-${compact ? 'c' : 'f'}`}>
                  Or type a message
                </label>
                <input
                  id={`typed-${compact ? 'c' : 'f'}`}
                  className="input"
                  value={typed}
                  maxLength={MAX_TEXT_CHARS}
                  onChange={(event) => setTyped(event.target.value)}
                  disabled={busy}
                  autoComplete="off"
                />
              </div>
              <Button type="submit" icon={Send} disabled={busy || !typed.trim()}>
                Send
              </Button>
            </form>
          </>
        )}

        {segmentIndexes.length > 0 && (
          <ul className="segments" aria-label="Spoken sentences">
            {segmentIndexes.map((index) => (
              <li key={index} className={`badge ${state.segments[index] === 'playing' ? 'badge-accent' : state.segments[index] === 'played' ? 'badge-success' : ''}`}>
                Sentence {index + 1}: {SEGMENT_LABELS[state.segments[index]]}
              </li>
            ))}
          </ul>
        )}
        {state.metrics && !compact && (
          <dl className="metric-grid" aria-label="Timings for the last turn">
            <div>
              <dt>First text</dt>
              <dd>{formatMs(state.metrics.firstTextMs)}</dd>
            </div>
            <div>
              <dt>First audio</dt>
              <dd>{formatMs(state.metrics.firstAudioMs)}</dd>
            </div>
            <div>
              <dt>Transcript</dt>
              <dd>{formatMs(state.metrics.transcriptMs)}</dd>
            </div>
            <div>
              <dt>Total</dt>
              <dd>{formatMs(state.metrics.totalMs)}</dd>
            </div>
          </dl>
        )}
      </div>

      <ConfirmDialog open={confirmClear} title="Clear this conversation?" confirmLabel="Clear" onConfirm={clearTranscript} onCancel={() => setConfirmClear(false)}>
        The transcript is removed from this screen and the next turn starts a fresh conversation. Nothing is saved anywhere.
      </ConfirmDialog>
    </section>
  )
}
