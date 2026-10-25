// UI state for one voice session, as a pure reducer over the server's events (no DOM, no network: easy to test).
//
// phase: idle | requesting-mic | connecting | listening | processing | done | error
//   idle            nothing running
//   requesting-mic  waiting for the browser's microphone permission
//   connecting      opening the WebSocket / waiting for `ready`
//   listening       `ready` received and audio is being streamed (or the typed message was sent)
//   processing      the user finished speaking: transcript, reply text and speech are arriving
//   done            the turn ended with `done`
//   error           the turn ended with a fatal error (state.error) or the connection failed

export const initialState = Object.freeze({
  phase: 'idle',
  sessionId: null,
  requestId: null,
  language: null,
  partial: '', // the current interim hypothesis
  finals: [], // stable transcript segments, in order
  replyText: '', // Gemini's reply so far
  segments: {}, // index -> 'receiving' | 'ready' | 'playing' | 'played' | 'skipped'
  warnings: [], // non-fatal errors (a failed speech sentence)
  error: null, // fatal: { stage, code, message, requestId, fatal: true } | { stage: 'client', ... }
  metrics: null, // from `done`
  audioComplete: null,
})

/** A new turn: keep the conversation (session id) but clear everything else. */
export function beginTurn(state, { language, phase }) {
  return { ...initialState, phase, sessionId: state.sessionId, language }
}

export function withPhase(state, phase) {
  return state.phase === phase ? state : { ...state, phase }
}

/** A client-side failure (permission denied, connection lost...): ends the turn as an error. */
export function failTurn(state, { code, message }) {
  if (state.phase === 'done' || state.phase === 'error') return state // exactly one terminal state per turn
  return { ...state, phase: 'error', error: { stage: 'client', code, message, requestId: state.requestId, fatal: true } }
}

export function setSegment(state, index, status) {
  if (state.segments[index] === status) return state
  return { ...state, segments: { ...state.segments, [index]: status } }
}

/** Apply one server event (already parsed JSON). Unknown event types are ignored so new server events never break the page. */
export function reduceEvent(state, event) {
  switch (event.type) {
    case 'ready':
      return {
        ...state,
        sessionId: event.session_id ?? state.sessionId,
        requestId: event.request_id ?? state.requestId,
        phase: state.phase === 'connecting' ? 'listening' : state.phase,
      }
    case 'partial':
      return { ...state, partial: event.text }
    case 'final':
      return { ...state, partial: '', finals: [...state.finals, event.text] }
    case 'reply_text':
      return { ...state, replyText: state.replyText + event.text }
    // audio_start / audio_end are NOT reduced here: the PlaybackQueue owns segment status (receiving -> ready ->
    // playing -> played, or skipped) and reports it through setSegment(), so the two can never disagree.
    case 'error': {
      const error = {
        stage: event.stage,
        code: event.code,
        message: event.message,
        requestId: event.request_id,
        fatal: Boolean(event.fatal),
      }
      if (!error.fatal) return { ...state, warnings: [...state.warnings, error] }
      if (state.phase === 'done' || state.phase === 'error') return state // never a second terminal event
      return { ...state, phase: 'error', error }
    }
    case 'done':
      if (state.phase === 'done' || state.phase === 'error') return state
      return {
        ...state,
        phase: 'done',
        partial: '',
        sessionId: event.session_id ?? state.sessionId,
        audioComplete: event.audio_complete,
        metrics: {
          model: event.model,
          sentences: event.sentences,
          audioBytes: event.audio_bytes,
          firstTextMs: event.first_text_ms,
          firstAudioMs: event.first_audio_ms,
          transcriptMs: event.transcript_ms,
          totalMs: event.total_ms,
        },
      }
    default:
      return state
  }
}
