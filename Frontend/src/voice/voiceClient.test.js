import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import { CaptureError } from './audioCapture.js'
import { VoiceClient } from './voiceClient.js'
import { blobBytes, FakeWebSocket, frameOf, makeCaptureHarness, makePlayerHarness, tick } from './testHarness.js'

const URL = 'ws://127.0.0.1:8001/voice/stream'

beforeEach(() => {
  FakeWebSocket.instances = []
})

function setup({ capture = makeCaptureHarness(), url = URL } = {}) {
  const player = makePlayerHarness()
  const timers = { callbacks: [], cleared: 0 }
  const states = []
  const client = new VoiceClient({
    url,
    onChange: (state) => states.push(state),
    deps: {
      WebSocket: FakeWebSocket,
      startCapture: (options) => capture.startCapture(options),
      createPlayer: player.createPlayer,
      setTimeout: (callback) => { timers.callbacks.push(callback); return timers.callbacks.length },
      clearTimeout: () => { timers.cleared++ },
      origin: 'http://localhost:5173',
    },
  })
  return { client, capture, player, timers, states, ws: () => FakeWebSocket.instances.at(-1) }
}

/** Start a spoken turn and complete the handshake. */
async function connected(ctx, language = 'hinglish') {
  await ctx.client.start({ language })
  ctx.ws().open()
  ctx.ws().receive({ type: 'ready', request_id: 'req-1', session_id: 'sess-1', language, sample_rate: 16000 })
  return ctx.ws()
}

const audioSegment = (ws, index, bytes, complete = true) => {
  ws.receive({ type: 'audio_start', index, content_type: 'audio/mpeg' })
  for (const chunk of bytes) ws.receiveRaw(Uint8Array.from(chunk).buffer)
  ws.receive({ type: 'audio_end', index, complete, bytes: bytes.flat().length })
}

test('a full spoken turn: permission, config, raw PCM frames, end, transcripts, reply, ordered speech, done', async () => {
  const ctx = setup()
  const { client, capture, player } = ctx
  const phases = []
  client.onChange = (state) => phases.push(state.phase)

  await client.start({ language: 'hinglish' })
  assert.equal(capture.started, 1)
  assert.equal(FakeWebSocket.instances.length, 1)
  const ws = ctx.ws()
  assert.equal(ws.url, URL)
  assert.equal(ws.binaryType, 'arraybuffer')

  capture.frame(frameOf(1)) // the microphone is already delivering while the socket connects
  ws.open()
  assert.deepEqual(ws.jsonSent, [{ type: 'config', language: 'hinglish', sample_rate: 16000 }]) // exactly the server's config
  assert.equal(ws.binarySent.length, 0, 'no audio before the server says ready')

  ws.receive({ type: 'ready', request_id: 'req-1', session_id: 'sess-1', language: 'hinglish', sample_rate: 16000 })
  assert.equal(ws.binarySent.length, 1, 'frames held while connecting are sent once ready, in order')
  capture.frame(frameOf(2))
  capture.frame(frameOf(3))
  for (const frame of ws.binarySent) {
    assert.ok(frame instanceof ArrayBuffer)
    assert.equal(frame.byteLength % 2, 0)
    assert.notEqual(new TextDecoder().decode(frame.slice(0, 4)), 'RIFF')
  }
  assert.deepEqual(ws.binarySent.map((f) => new Int16Array(f)[0]), [1, 2, 3])

  capture.rest = frameOf(9, 100)
  await client.stop()
  assert.equal(capture.stops, 1, 'the microphone is released when Stop is pressed')
  assert.deepEqual(ws.binarySent.map((f) => new Int16Array(f)[0]), [1, 2, 3, 9], 'the final partial frame is flushed')
  assert.deepEqual(ws.jsonSent.at(-1), { type: 'end' })
  assert.equal(ws.jsonSent.filter((m) => m.type === 'end').length, 1)
  capture.frame(frameOf(4)) // late frames after Stop are dropped
  assert.equal(ws.binarySent.length, 4)
  assert.equal(client.state.phase, 'processing')

  ws.receive({ type: 'partial', seq: 1, text: 'namaste' })
  assert.equal(client.state.partial, 'namaste')
  ws.receive({ type: 'final', seq: 2, text: 'namaste duniya', start: 0, duration: 1, speech_final: true, confidence: 0.9 })
  ws.receive({ type: 'reply_text', text: 'Namaste! ' })
  audioSegment(ws, 0, [[1, 2], [3]])
  ws.receive({ type: 'reply_text', text: 'Kaise ho?' })
  audioSegment(ws, 1, [[4, 5]])
  assert.deepEqual(client.state.finals, ['namaste duniya'])
  assert.equal(client.state.partial, '')
  assert.equal(client.state.replyText, 'Namaste! Kaise ho?')
  assert.equal(player.players.length, 1, 'speech starts with the first complete sentence, before the turn is done')
  assert.deepEqual(await blobBytes(player.players[0].blob), [1, 2, 3])

  ws.receive({ type: 'done', request_id: 'req-1', session_id: 'sess-1', model: 'm', audio_complete: true, sentences: 2, audio_bytes: 5, first_text_ms: 100, first_audio_ms: 200, transcript_ms: 50, total_ms: 400 })
  assert.equal(client.state.phase, 'done')
  assert.equal(client.state.metrics.firstAudioMs, 200)
  assert.equal(ws.closedWith, 1000, 'the socket is closed after done')
  assert.equal(client.busy, false)

  player.players[0].finish() // sentence 1 ends -> sentence 2 starts, never overlapping
  await tick()
  assert.equal(player.players.length, 2)
  assert.deepEqual(await blobBytes(player.players[1].blob), [4, 5])
  player.players[1].finish()
  await tick()
  assert.equal(player.maxConcurrent, 1)
  assert.deepEqual(client.state.segments, { 0: 'played', 1: 'played' })
  assert.ok(phases.includes('requesting-mic') && phases.includes('connecting') && phases.includes('listening') && phases.includes('processing'))
})

test('the conversation continues: the next turn sends the session_id the server issued', async () => {
  const ctx = setup()
  let ws = await connected(ctx)
  ws.receive({ type: 'done', session_id: 'sess-1', audio_complete: true })
  await ctx.client.start({ language: 'english' })
  ws = ctx.ws()
  ws.open()
  assert.deepEqual(ws.jsonSent[0], { type: 'config', language: 'english', session_id: 'sess-1', sample_rate: 16000 })
  assert.equal(FakeWebSocket.instances.length, 2)
  ctx.client.newConversation()
  await ctx.client.start({ language: 'english' })
  ctx.ws().open()
  assert.equal('session_id' in ctx.ws().jsonSent[0], false, 'a new conversation starts a fresh session')
})

test('microphone permission denied: a clear error, no connection, nothing left running', async () => {
  const denied = new CaptureError('permission_denied', 'Microphone permission was denied. Allow it and try again.')
  const ctx = setup({ capture: makeCaptureHarness({ rejectWith: denied }) })
  await ctx.client.start({ language: 'hinglish' })
  assert.equal(ctx.client.state.phase, 'error')
  assert.equal(ctx.client.state.error.code, 'permission_denied')
  assert.match(ctx.client.state.error.message, /permission was denied/i)
  assert.equal(FakeWebSocket.instances.length, 0)
  assert.equal(ctx.client.busy, false)
  await ctx.client.start({ language: 'hinglish' }) // can try again
  assert.equal(ctx.capture.started, 2)
})

test('connection failure before ready explains what to check and releases the microphone', async () => {
  const ctx = setup()
  await ctx.client.start({ language: 'hinglish' })
  ctx.ws().drop() // refused: server down, or the origin is not allowed (the browser cannot tell which)
  assert.equal(ctx.client.state.phase, 'error')
  assert.equal(ctx.client.state.error.code, 'connection_failed')
  assert.match(ctx.client.state.error.message, /127\.0\.0\.1:8001/)
  assert.match(ctx.client.state.error.message, /http:\/\/localhost:5173/)
  assert.match(ctx.client.state.error.message, /STT_ALLOWED_ORIGINS/)
  assert.equal(ctx.capture.stops, 1)
  assert.equal(ctx.client.busy, false)
})

test('losing the connection mid-turn is an error, and cleans up the microphone and the socket', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  audioSegment(ws, 0, [[1]])
  ws.drop()
  assert.equal(ctx.client.state.error.code, 'connection_lost')
  assert.equal(ctx.capture.stops, 1)
  assert.equal(ctx.client.busy, false)
  assert.equal(ctx.player.players.length, 1, 'a sentence that arrived completely can still be heard')
})

test('a fatal server error ends the turn once; a later done cannot overwrite it', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  ws.receive({ type: 'error', stage: 'llm', code: 'llm_authentication_failed', message: 'The AI provider rejected this service\'s credentials.', request_id: 'req-1', fatal: true })
  assert.equal(ctx.client.state.phase, 'error')
  assert.equal(ctx.client.state.error.stage, 'llm')
  assert.equal(ctx.capture.stops, 1)
  assert.equal(ws.closedWith, 1000)
  ws.receive({ type: 'done', session_id: 'sess-1' })
  assert.equal(ctx.client.state.phase, 'error')
})

test('a non-fatal tts error is shown as a warning; text keeps flowing and done reports audio_complete=false', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  ws.receive({ type: 'reply_text', text: 'Pehla. ' })
  ws.receive({ type: 'error', stage: 'tts', code: 'tts_unavailable', message: 'speech failed', request_id: 'r', fatal: false })
  ws.receive({ type: 'reply_text', text: 'Doosra.' })
  assert.notEqual(ctx.client.state.phase, 'error')
  assert.equal(ctx.client.state.warnings.length, 1)
  ws.receive({ type: 'done', session_id: 'sess-1', audio_complete: false, sentences: 2 })
  assert.deepEqual([ctx.client.state.phase, ctx.client.state.audioComplete, ctx.client.state.replyText], ['done', false, 'Pehla. Doosra.'])
})

test('cancel closes the socket, releases the microphone, silences playback, and ignores late events', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  audioSegment(ws, 0, [[1]])
  assert.equal(ctx.player.players.length, 1)
  const sentBefore = ws.sent.length
  ctx.client.cancel()
  assert.equal(ws.closedWith, 1000)
  assert.equal(ctx.capture.stops, 1)
  assert.equal(ctx.player.players[0].stopped, true)
  assert.equal(ctx.client.state.phase, 'idle')
  assert.equal(ctx.client.state.sessionId, 'sess-1', 'cancelling keeps the conversation')
  assert.equal(ctx.client.busy, false)

  ws.receive({ type: 'reply_text', text: 'late' })
  ws.receive({ type: 'done', session_id: 'sess-1' })
  ws.drop()
  ctx.capture.frame(frameOf(1))
  assert.equal(ctx.client.state.replyText, '')
  assert.equal(ctx.client.state.phase, 'idle')
  assert.equal(ws.sent.length, sentBefore, 'nothing is sent after cancel')
  await tick()
  assert.equal(ctx.player.players.length, 1)
})

test('cancelling while the permission prompt is open still releases the microphone once it is granted', async () => {
  const capture = makeCaptureHarness({ hold: true })
  const ctx = setup({ capture })
  const starting = ctx.client.start({ language: 'hinglish' })
  await tick()
  ctx.client.cancel()
  capture.release() // the user grants permission after cancelling
  await starting
  assert.equal(capture.stops, 1, 'the microphone is stopped, not left recording')
  assert.equal(FakeWebSocket.instances.length, 0)
  assert.equal(ctx.client.state.phase, 'idle')
})

test('Stop while the permission prompt is still open abandons the turn', async () => {
  const capture = makeCaptureHarness({ hold: true })
  const ctx = setup({ capture })
  const starting = ctx.client.start({ language: 'hinglish' })
  await tick()
  await ctx.client.stop()
  capture.release()
  await starting
  assert.equal(capture.stops, 1)
  assert.equal(FakeWebSocket.instances.length, 0)
})

test('Stop before any audio was captured is a clear error, and the connection is closed', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  await ctx.client.stop()
  assert.equal(ctx.client.state.error.code, 'no_audio')
  assert.equal(ws.closedWith, 1000)
  assert.ok(!ws.jsonSent.some((m) => m.type === 'end'))
})

test('Stop pressed while still connecting sends `end` only after the server is ready', async () => {
  const ctx = setup()
  await ctx.client.start({ language: 'hinglish' })
  ctx.capture.frame(frameOf(1))
  await ctx.client.stop()
  ctx.ws().open()
  assert.ok(!ctx.ws().jsonSent.some((m) => m.type === 'end'))
  ctx.ws().receive({ type: 'ready', request_id: 'r', session_id: 's' })
  assert.equal(ctx.ws().binarySent.length, 1)
  assert.deepEqual(ctx.ws().jsonSent.at(-1), { type: 'end' })
})

test('the recording is ended automatically before the server limit', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  ctx.capture.frame(frameOf(1))
  assert.equal(ctx.timers.callbacks.length, 1)
  ctx.timers.callbacks[0]() // the safety timer fires
  await tick()
  assert.deepEqual(ws.jsonSent.at(-1), { type: 'end' })
  assert.equal(ctx.capture.stops, 1)
})

test('a typed message: config then text, no microphone involved', async () => {
  const ctx = setup()
  ctx.client.sendText('  Namaste, kaise ho?  ', { language: 'hindi' })
  assert.equal(ctx.capture.started, 0)
  ctx.ws().open()
  assert.deepEqual(ctx.ws().jsonSent, [{ type: 'config', language: 'hindi' }, { type: 'text', text: 'Namaste, kaise ho?' }])
  ctx.ws().receive({ type: 'ready', session_id: 's', request_id: 'r' })
  assert.equal(ctx.client.state.phase, 'processing')
  ctx.ws().receive({ type: 'reply_text', text: 'Theek hoon.' })
  audioSegment(ctx.ws(), 0, [[7]])
  ctx.ws().receive({ type: 'done', session_id: 's', audio_complete: true })
  assert.equal(ctx.client.state.replyText, 'Theek hoon.')
  assert.equal(ctx.player.players.length, 1)
})

test('empty or oversized typed messages are rejected locally without connecting', () => {
  const ctx = setup()
  ctx.client.sendText('   ', { language: 'english' })
  assert.equal(ctx.client.state.error.code, 'invalid_text')
  ctx.client.sendText('x'.repeat(2001), { language: 'english' })
  assert.equal(ctx.client.state.error.code, 'invalid_text')
  assert.equal(FakeWebSocket.instances.length, 0)
})

test('a non-local service URL is refused before the microphone or the network is touched', async () => {
  const ctx = setup({ url: 'wss://voice.example.com/voice/stream' })
  await ctx.client.start({ language: 'hinglish' })
  assert.equal(ctx.client.state.error.code, 'unsafe_url')
  assert.match(ctx.client.state.error.message, /no authentication/i)
  assert.equal(ctx.capture.started, 0)
  assert.equal(FakeWebSocket.instances.length, 0)
})

test('starting twice does not open a second connection', async () => {
  const ctx = setup()
  await connected(ctx)
  await ctx.client.start({ language: 'hinglish' })
  assert.equal(FakeWebSocket.instances.length, 1)
  assert.equal(ctx.capture.started, 1)
})

test('malformed server messages and stray binary frames are ignored without breaking the turn', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  ws.receiveRaw('not json')
  ws.receiveRaw('{"no":"type"}')
  ws.receiveRaw(Uint8Array.of(1, 2, 3).buffer) // binary before any audio_start
  ws.receive({ type: 'brand_new_event', x: 1 })
  ws.receive({ type: 'reply_text', text: 'still fine' })
  assert.equal(ctx.client.state.replyText, 'still fine')
  assert.equal(ctx.client.state.phase, 'listening')
  assert.equal(ctx.player.players.length, 0)
})

test('dispose releases everything, and nothing is reported to a component that is gone', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  audioSegment(ws, 0, [[1]])
  const calls = ctx.states.length
  ctx.client.dispose()
  assert.equal(ws.closedWith, 1000)
  assert.equal(ctx.capture.stops, 1)
  assert.equal(ctx.player.players[0].stopped, true)
  ws.receive({ type: 'reply_text', text: 'late' })
  ctx.client.dispose() // idempotent
  assert.equal(ctx.states.length, calls)
  await ctx.client.start({ language: 'hinglish' })
  assert.equal(FakeWebSocket.instances.length, 1, 'a disposed client does not start new turns')
})

test('a send failure is reported as a lost connection instead of throwing', async () => {
  const ctx = setup()
  const ws = await connected(ctx)
  ws.send = () => { throw new Error('socket closed') }
  ctx.capture.frame(frameOf(1))
  assert.equal(ctx.client.state.error.code, 'connection_lost')
  assert.equal(ctx.capture.stops, 1)
})
