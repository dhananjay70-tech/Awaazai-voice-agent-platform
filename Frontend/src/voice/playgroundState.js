// What the live playground shows, derived from the voice client's state (voiceState.js) plus the playground's own
// notion of a "session" (open / ended). A session is a UI concept: the voice client opens a WebSocket for each turn and
// closes it afterwards, so "Ready" means "the session is open and waiting for you", not "a socket is held open".
//
// keys: idle | ready | connecting | listening | processing | speaking | disconnected | permission-denied | error | ended

export const PLAYGROUND_STATES = {
  idle: { label: 'Idle', tone: '', detail: 'Start a session to talk to the voice service.' },
  ready: { label: 'Ready', tone: 'badge-success', detail: 'Press Talk or type a message.' },
  connecting: { label: 'Connecting', tone: 'badge-info', detail: 'Connecting to the voice service…' },
  listening: { label: 'Listening', tone: 'badge-accent', detail: 'Speak now, then press Stop.' },
  processing: { label: 'Processing', tone: 'badge-info', detail: 'Transcribing and writing a reply…' },
  speaking: { label: 'Speaking', tone: 'badge-success', detail: 'Playing the reply.' },
  disconnected: { label: 'Disconnected', tone: 'badge-warning', detail: 'Press Retry to reconnect.' },
  'permission-denied': { label: 'Microphone blocked', tone: 'badge-error', detail: 'Allow microphone access for this site, or type instead.' },
  error: { label: 'Error', tone: 'badge-error', detail: 'Something went wrong.' },
  ended: { label: 'Conversation ended', tone: '', detail: 'The session was ended. Start a new one to continue.' },
}

/**
 * @param {{ session: 'closed'|'open'|'ended', phase: string, mode: 'speak'|'text', speaking: boolean, error: {code?: string}|null }} input
 */
export function playgroundStateKey({ session, phase, mode, speaking, error }) {
  if (session === 'ended') return 'ended'
  if (session !== 'open') return 'idle'
  if (error || phase === 'error') {
    if (error?.code === 'permission_denied') return 'permission-denied'
    if (error?.code === 'connection_lost') return 'disconnected'
    return 'error'
  }
  if (speaking) return 'speaking'
  switch (phase) {
    case 'requesting-mic':
    case 'connecting':
      return 'connecting'
    case 'listening':
      return mode === 'text' ? 'processing' : 'listening' // a typed message is already sent once the socket is ready
    case 'processing':
      return 'processing'
    default:
      return 'ready' // idle, or a finished turn
  }
}

/** One finished turn as a transcript entry; null when there is nothing worth showing. */
export function turnToEntry(state, { mode, typedText }) {
  const user = mode === 'text' ? typedText.trim() : state.finals.join(' ').trim()
  const agent = state.replyText.trim()
  if (!user && !agent) return null
  return { user, agent, audioComplete: state.audioComplete, warnings: state.warnings.length }
}
