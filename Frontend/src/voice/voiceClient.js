// Orchestrates one voice session against WS /voice/stream: microphone -> PCM16 frames -> socket -> transcript, reply
// text and spoken sentences. One connection = one turn (the server's rule); the conversation continues across turns
// by reusing the `session_id` from `ready`.
//
// Everything external (WebSocket, microphone capture, audio playback, timers) is injected, so the whole flow is unit
// tested with fakes. The real implementations are the defaults used by the React hook.

import { startCapture as realStartCapture } from './audioCapture.js'
import { PlaybackQueue } from './playbackQueue.js'
import {
  buildConfigMessage,
  buildTextMessage,
  END_MESSAGE,
  MAX_RECORD_SECONDS,
  MAX_TEXT_CHARS,
  parseServerEvent,
  validateVoiceUrl,
} from './voiceProtocol.js'
import { beginTurn, failTurn, initialState, reduceEvent, setSegment, withPhase } from './voiceState.js'

const MAX_PENDING_FRAMES = 100 // about 5 s of audio held while the socket is still connecting; older frames are dropped

export class VoiceClient {
  /**
   * @param {object} options
   * @param {string} options.url                 ws://127.0.0.1:8001/voice/stream (validated: loopback only)
   * @param {(state: object) => void} options.onChange
   * @param {object} options.deps                { WebSocket, startCapture, createPlayer, setTimeout, clearTimeout, origin }
   */
  constructor({ url, onChange = () => {}, deps = {} }) {
    this.url = url
    this.onChange = onChange
    this.WebSocketCtor = deps.WebSocket ?? globalThis.WebSocket
    this.startCapture = deps.startCapture ?? realStartCapture
    this.setTimer = deps.setTimeout ?? globalThis.setTimeout?.bind(globalThis)
    this.clearTimer = deps.clearTimeout ?? globalThis.clearTimeout?.bind(globalThis)
    this.origin = deps.origin ?? globalThis.location?.origin ?? 'this page'
    this.state = initialState
    this.turn = null
    this.disposed = false
    this.queue = new PlaybackQueue({
      createPlayer: deps.createPlayer,
      onSegmentState: (index, status) => this.#set(setSegment(this.state, index, status)),
    })
  }

  get busy() {
    return this.turn !== null
  }

  // ------------------------------------------------------------------ public controls

  /** Start a spoken turn: ask for the microphone, connect, stream audio until stop() or cancel(). */
  async start({ language }) {
    if (this.turn || this.disposed) return
    const turn = this.#newTurn('audio', language)
    if (!this.#checkUrl(turn)) return
    this.#set(beginTurn(this.state, { language, phase: 'requesting-mic' }))

    let capture
    try {
      capture = await this.startCapture({
        onFrame: (frame) => this.#onFrame(turn, frame),
        onError: () => this.#fail(turn, 'capture_failed', 'The audio capture failed.'),
      })
    } catch (error) {
      if (this.turn === turn) this.#fail(turn, error.code ?? 'capture_failed', error.message)
      return
    }
    if (this.turn !== turn || turn.ended) {
      await capture.stop() // cancelled while the permission prompt was open: release the microphone again
      return
    }
    turn.capture = capture
    turn.sampleRate = capture.sampleRate
    this.#set(withPhase(this.state, 'connecting'))
    turn.timer = this.setTimer(() => this.stop(), MAX_RECORD_SECONDS * 1000) // the server stops listening after 120 s
    this.#connect(turn)
  }

  /** The user finished speaking: flush the last audio, send `end`, and keep listening for the answer. */
  async stop() {
    const turn = this.turn
    if (!turn || turn.mode !== 'audio' || turn.stopRequested || turn.ended) return
    if (!turn.capture) {
      this.cancel() // Stop while the permission prompt is still open: nothing was recorded, so abandon the turn
      return
    }
    turn.stopRequested = true
    this.clearTimer?.(turn.timer)
    const rest = await turn.capture.stop() // releases the microphone and returns the final partial frame
    turn.capture = null
    if (turn.ended) return
    if (rest) this.#onFrame(turn, rest, { afterStop: true })
    if (turn.framesQueued === 0) {
      this.#fail(turn, 'no_audio', 'No audio was captured. Press Start, then speak.')
      return
    }
    this.#set(withPhase(this.state, 'processing'))
    this.#sendEndIfReady(turn)
  }

  /** Send a typed message instead of speaking (handy for testing the reply and playback without a microphone). */
  sendText(text, { language }) {
    if (this.turn || this.disposed) return
    const turn = this.#newTurn('text', language)
    if (!this.#checkUrl(turn)) return
    const message = String(text ?? '').trim()
    if (!message || message.length > MAX_TEXT_CHARS) {
      this.#set(beginTurn(this.state, { language, phase: 'connecting' }))
      this.#fail(turn, 'invalid_text', `Type between 1 and ${MAX_TEXT_CHARS} characters.`)
      return
    }
    turn.text = message
    this.#set(beginTurn(this.state, { language, phase: 'connecting' }))
    this.#connect(turn)
  }

  /** Abort the turn: close the socket, release the microphone, stop any sound that is playing. */
  cancel() {
    const turn = this.turn
    this.queue.stop()
    if (turn) this.#teardown(turn)
    this.#set({ ...initialState, sessionId: this.state.sessionId })
  }

  /** Forget the conversation: the next turn starts a fresh server session. */
  newConversation() {
    this.cancel()
    this.#set({ ...initialState })
  }

  dispose() {
    this.disposed = true // first: nothing is reported to a component that is going away
    this.cancel()
  }

  // ------------------------------------------------------------------ connection

  #newTurn(mode, language) {
    const turn = {
      mode, language, ws: null, capture: null, sampleRate: null, timer: null, text: null,
      ready: false, ended: false, stopRequested: false, endSent: false, closedByUs: false,
      pending: [], framesQueued: 0,
    }
    this.turn = turn
    this.queue.stop()
    this.queue.reset()
    return turn
  }

  #checkUrl(turn) {
    const check = validateVoiceUrl(this.url)
    if (check.ok) return true
    this.#set(beginTurn(this.state, { language: turn.language, phase: 'connecting' }))
    this.#fail(turn, 'unsafe_url', check.reason)
    return false
  }

  #connect(turn) {
    let ws
    try {
      ws = new this.WebSocketCtor(this.url)
    } catch {
      this.#fail(turn, 'connection_failed', this.#connectMessage())
      return
    }
    ws.binaryType = 'arraybuffer'
    turn.ws = ws
    ws.onopen = () => {
      if (turn.ended) return
      const config = buildConfigMessage({
        language: turn.language,
        sessionId: this.state.sessionId,
        sampleRate: turn.mode === 'audio' ? turn.sampleRate : null,
      })
      this.#send(turn, JSON.stringify(config))
      if (turn.mode === 'text') this.#send(turn, JSON.stringify(buildTextMessage(turn.text)))
    }
    ws.onmessage = (event) => this.#onMessage(turn, event.data)
    ws.onerror = () => {} // the close event that follows carries the outcome
    ws.onclose = () => this.#onClose(turn)
  }

  #connectMessage() {
    return `Could not connect to the voice service at ${this.url}. Check that VoiceAgent is running and that this page's origin (${this.origin}) is listed in STT_ALLOWED_ORIGINS.`
  }

  #onClose(turn) {
    if (turn.ended || turn.closedByUs) return
    if (!turn.ready) {
      this.#fail(turn, 'connection_failed', this.#connectMessage())
    } else {
      this.queue.finish() // sentences that arrived completely can still be heard
      this.#fail(turn, 'connection_lost', 'The connection to the voice service was lost before the turn finished.')
    }
  }

  // ------------------------------------------------------------------ incoming

  #onMessage(turn, data) {
    if (turn.ended) return
    if (typeof data !== 'string') {
      this.queue.appendFrame(data) // a binary frame: MP3 bytes of the most recent audio_start
      return
    }
    const event = parseServerEvent(data)
    if (!event) return
    switch (event.type) {
      case 'ready':
        turn.ready = true
        this.#set(reduceEvent(this.state, event))
        if (turn.mode === 'text') this.#set(withPhase(this.state, 'processing')) // the typed message was already sent
        this.#flushPending(turn)
        this.#sendEndIfReady(turn)
        return
      case 'audio_start':
        this.queue.startSegment(event.index, event.content_type)
        return
      case 'audio_end':
        this.queue.endSegment(event.index, event.complete)
        return
      default:
        this.#set(reduceEvent(this.state, event))
    }
    if (event.type === 'done' || (event.type === 'error' && event.fatal)) {
      this.queue.finish() // play whatever completed, in order
      this.#teardown(turn)
    }
  }

  // ------------------------------------------------------------------ outgoing audio

  #onFrame(turn, frame, { afterStop = false } = {}) {
    if (turn.ended || (turn.stopRequested && !afterStop)) return
    turn.framesQueued++
    if (turn.ready && turn.ws?.readyState === 1) {
      this.#send(turn, frame)
      return
    }
    turn.pending.push(frame)
    if (turn.pending.length > MAX_PENDING_FRAMES) turn.pending.shift()
  }

  #flushPending(turn) {
    for (const frame of turn.pending.splice(0)) this.#send(turn, frame)
  }

  #sendEndIfReady(turn) {
    if (turn.mode !== 'audio' || !turn.stopRequested || turn.capture || turn.endSent || !turn.ready || turn.ended) return
    turn.endSent = true
    this.#send(turn, JSON.stringify(END_MESSAGE))
  }

  #send(turn, payload) {
    if (turn.ended || !turn.ws || turn.ws.readyState !== 1) return
    try {
      turn.ws.send(payload)
    } catch {
      this.#fail(turn, 'connection_lost', 'The connection to the voice service was lost.')
    }
  }

  // ------------------------------------------------------------------ ending a turn

  #fail(turn, code, message) {
    if (turn.ended) return
    this.#set(failTurn(this.state, { code, message }))
    this.#teardown(turn)
  }

  /** Release everything a turn holds: timer, microphone, socket. Idempotent. Playback is handled by the caller. */
  #teardown(turn) {
    if (turn.ended) return
    turn.ended = true
    turn.closedByUs = true
    if (turn.timer) this.clearTimer?.(turn.timer)
    if (turn.capture) {
      const capture = turn.capture
      turn.capture = null
      capture.stop().catch(() => {})
    }
    const ws = turn.ws
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) {
      try {
        ws.close(1000)
      } catch {
        /* already closing */
      }
    }
    if (this.turn === turn) this.turn = null
  }

  #set(next) {
    if (next === this.state || this.disposed) return
    this.state = next
    this.onChange(next)
  }
}
