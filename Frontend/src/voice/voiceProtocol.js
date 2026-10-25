// The client side of VoiceAgent's WS /voice/stream protocol (documented in VoiceAgent/app/voice/protocol.py).

export const DEFAULT_VOICE_URL = 'ws://127.0.0.1:8001/voice/stream'
export const LANGUAGES = ['hinglish', 'hindi', 'english']
export const MAX_TEXT_CHARS = 2000 // server limit for a typed message
export const MAX_RECORD_SECONDS = 100 // the server stops accepting audio after 120 s: end the turn before that

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

/**
 * VoiceAgent has no authentication yet, so this page may only talk to a service on this machine. Anything else is
 * refused here, whatever the environment variable says. Returns { ok, url } or { ok: false, reason }.
 */
export function validateVoiceUrl(value) {
  let url
  try {
    url = new URL(value)
  } catch {
    return { ok: false, reason: 'The voice service URL is not a valid URL.' }
  }
  if (url.protocol !== 'ws:' && url.protocol !== 'wss:') {
    return { ok: false, reason: 'The voice service URL must start with ws:// (or wss://).' }
  }
  if (!LOOPBACK_HOSTS.has(url.hostname)) {
    return {
      ok: false,
      reason:
        'Refusing to connect: the voice service has no authentication yet, so this page only connects to localhost or 127.0.0.1.',
    }
  }
  return { ok: true, url: url.toString() }
}

export function buildConfigMessage({ language, sampleRate = null, sessionId = null }) {
  const message = { type: 'config', language }
  if (sessionId) message.session_id = sessionId
  if (sampleRate) message.sample_rate = sampleRate
  return message
}

export const END_MESSAGE = Object.freeze({ type: 'end' })

export function buildTextMessage(text) {
  return { type: 'text', text }
}

/** Parse a TEXT frame from the server. Returns the event object, or null if it is not a well-formed event. */
export function parseServerEvent(raw) {
  if (typeof raw !== 'string') return null
  let event
  try {
    event = JSON.parse(raw)
  } catch {
    return null
  }
  return event && typeof event === 'object' && typeof event.type === 'string' ? event : null
}
