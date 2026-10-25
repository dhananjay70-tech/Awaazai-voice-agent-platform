import assert from 'node:assert/strict'
import { test } from 'node:test'
import { beginTurn, failTurn, initialState, reduceEvent, setSegment, withPhase } from './voiceState.js'

const apply = (events, state = beginTurn(initialState, { language: 'hinglish', phase: 'connecting' })) =>
  events.reduce((s, e) => reduceEvent(s, e), state)

test('ready moves connecting to listening and records the session', () => {
  const state = apply([{ type: 'ready', session_id: 'sess-1', request_id: 'req-1', language: 'hinglish', sample_rate: 16000 }])
  assert.equal(state.phase, 'listening')
  assert.equal(state.sessionId, 'sess-1')
  assert.equal(state.requestId, 'req-1')
})

test('ready does not pull a turn that is already processing back to listening', () => {
  const state = reduceEvent(withPhase(beginTurn(initialState, { language: 'hindi', phase: 'connecting' }), 'processing'), { type: 'ready', session_id: 's' })
  assert.equal(state.phase, 'processing')
})

test('partial text is replaced by newer partials and cleared by the final', () => {
  let state = apply([{ type: 'partial', seq: 1, text: 'namaste' }])
  assert.equal(state.partial, 'namaste')
  state = reduceEvent(state, { type: 'partial', seq: 2, text: 'namaste duniya' })
  assert.equal(state.partial, 'namaste duniya')
  state = reduceEvent(state, { type: 'final', seq: 3, text: 'namaste duniya', speech_final: true })
  assert.deepEqual([state.partial, state.finals], ['', ['namaste duniya']])
  state = reduceEvent(state, { type: 'final', seq: 4, text: 'kaise ho' })
  assert.deepEqual(state.finals, ['namaste duniya', 'kaise ho'])
})

test('reply_text pieces are concatenated exactly as received, in Devanagari, Roman and mixed script', () => {
  const state = apply([
    { type: 'reply_text', text: 'नमस्ते! ' },
    { type: 'reply_text', text: 'Main aapki ' },
    { type: 'reply_text', text: 'help kar sakta hoon.' },
  ])
  assert.equal(state.replyText, 'नमस्ते! Main aapki help kar sakta hoon.')
})

test('done ends the turn with metrics and remembers the session', () => {
  const state = apply([
    { type: 'ready', session_id: 's1', request_id: 'r' },
    { type: 'done', session_id: 's1', model: 'gemini-x', audio_complete: true, sentences: 3, audio_bytes: 900, first_text_ms: 1200, first_audio_ms: 2500, transcript_ms: 800, total_ms: 5000 },
  ])
  assert.equal(state.phase, 'done')
  assert.equal(state.audioComplete, true)
  assert.deepEqual(state.metrics, { model: 'gemini-x', sentences: 3, audioBytes: 900, firstTextMs: 1200, firstAudioMs: 2500, transcriptMs: 800, totalMs: 5000 })
})

test('a non-fatal tts error is a warning: the turn continues and still ends with done audio_complete=false', () => {
  let state = apply([
    { type: 'ready', session_id: 's' },
    { type: 'reply_text', text: 'Jawab. ' },
    { type: 'error', stage: 'tts', code: 'tts_unavailable', message: 'speech failed', request_id: 'r', fatal: false },
    { type: 'reply_text', text: 'Aur jawab.' },
  ])
  assert.equal(state.error, null)
  assert.equal(state.phase, 'listening')
  assert.equal(state.warnings.length, 1)
  assert.equal(state.warnings[0].stage, 'tts')
  state = reduceEvent(state, { type: 'done', session_id: 's', audio_complete: false, sentences: 2 })
  assert.deepEqual([state.phase, state.audioComplete, state.replyText], ['done', false, 'Jawab. Aur jawab.'])
})

test('a fatal error ends the turn in the error phase', () => {
  const state = apply([{ type: 'error', stage: 'llm', code: 'llm_authentication_failed', message: 'rejected', request_id: 'r', fatal: true }])
  assert.equal(state.phase, 'error')
  assert.deepEqual(state.error, { stage: 'llm', code: 'llm_authentication_failed', message: 'rejected', requestId: 'r', fatal: true })
})

test('there is never a second terminal event: done and fatal error do not overwrite each other', () => {
  const failed = apply([{ type: 'error', stage: 'stt', code: 'voice_no_speech', message: 'none', fatal: true }, { type: 'done', session_id: 's' }])
  assert.equal(failed.phase, 'error')
  assert.equal(failed.metrics, null)
  const finished = apply([{ type: 'done', session_id: 's', audio_complete: true }, { type: 'error', stage: 'server', code: 'x', message: 'late', fatal: true }])
  assert.equal(finished.phase, 'done')
  assert.equal(finished.error, null)
})

test('failTurn records a client-side error once and never replaces a terminal state', () => {
  const state = failTurn(beginTurn(initialState, { language: 'english', phase: 'requesting-mic' }), { code: 'permission_denied', message: 'denied' })
  assert.equal(state.phase, 'error')
  assert.equal(state.error.stage, 'client')
  assert.equal(failTurn(state, { code: 'other', message: 'later' }), state)
  const done = apply([{ type: 'done', session_id: 's' }])
  assert.equal(failTurn(done, { code: 'connection_lost', message: 'x' }), done)
})

test('a new turn keeps the conversation but clears the previous turn', () => {
  const finished = apply([{ type: 'ready', session_id: 'keep-me' }, { type: 'reply_text', text: 'old' }, { type: 'done', session_id: 'keep-me' }])
  const next = beginTurn(finished, { language: 'english', phase: 'requesting-mic' })
  assert.deepEqual([next.sessionId, next.replyText, next.finals, next.metrics, next.phase, next.language], ['keep-me', '', [], null, 'requesting-mic', 'english'])
})

test('segment status is owned by setSegment, not by the audio events', () => {
  let state = apply([{ type: 'audio_start', index: 0 }, { type: 'audio_end', index: 0, complete: true }])
  assert.deepEqual(state.segments, {})
  state = setSegment(state, 0, 'playing')
  assert.equal(setSegment(state, 0, 'playing'), state)
  assert.equal(setSegment(state, 0, 'played').segments[0], 'played')
})

test('unknown event types are ignored so a newer server never breaks the page', () => {
  const before = apply([])
  assert.equal(reduceEvent(before, { type: 'something_new', x: 1 }), before)
})
