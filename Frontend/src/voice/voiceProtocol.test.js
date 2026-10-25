import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  buildConfigMessage,
  buildTextMessage,
  DEFAULT_VOICE_URL,
  END_MESSAGE,
  LANGUAGES,
  MAX_RECORD_SECONDS,
  parseServerEvent,
  validateVoiceUrl,
} from './voiceProtocol.js'

test('the default URL is the local VoiceAgent and is accepted', () => {
  assert.equal(DEFAULT_VOICE_URL, 'ws://127.0.0.1:8001/voice/stream')
  assert.deepEqual(validateVoiceUrl(DEFAULT_VOICE_URL), { ok: true, url: 'ws://127.0.0.1:8001/voice/stream' })
})

test('loopback hosts are accepted', () => {
  for (const url of ['ws://localhost:8001/voice/stream', 'ws://127.0.0.1:8001/voice/stream', 'ws://[::1]:8001/voice/stream', 'wss://localhost:8443/voice/stream']) {
    assert.equal(validateVoiceUrl(url).ok, true, url)
  }
})

test('any non-loopback host is refused, because the endpoint has no authentication', () => {
  for (const url of ['ws://example.com/voice/stream', 'wss://api.awaazai.com/voice/stream', 'ws://192.168.1.20:8001/voice/stream', 'ws://0.0.0.0:8001/voice/stream', 'ws://localhost.evil.com/voice/stream', 'ws://127.0.0.1.evil.com/voice/stream']) {
    const result = validateVoiceUrl(url)
    assert.equal(result.ok, false, url)
    assert.match(result.reason, /localhost|127\.0\.0\.1/)
  }
})

test('malformed URLs and non-WebSocket schemes are refused', () => {
  for (const url of ['', 'not a url', 'http://localhost:8001/voice/stream', 'https://localhost/voice/stream', 'file:///etc/passwd']) {
    assert.equal(validateVoiceUrl(url).ok, false, url)
  }
})

test('the config message matches VoiceAgent: type, language, optional session_id and sample_rate', () => {
  assert.deepEqual(buildConfigMessage({ language: 'hinglish' }), { type: 'config', language: 'hinglish' })
  assert.deepEqual(buildConfigMessage({ language: 'hindi', sampleRate: 16000, sessionId: 'abc-1' }), {
    type: 'config', language: 'hindi', session_id: 'abc-1', sample_rate: 16000,
  })
  assert.deepEqual(LANGUAGES.toSorted(), ['english', 'hindi', 'hinglish'])
})

test('end and text messages match the protocol; recording stops before the server limit of 120 s', () => {
  assert.deepEqual(END_MESSAGE, { type: 'end' })
  assert.deepEqual(buildTextMessage('Namaste'), { type: 'text', text: 'Namaste' })
  assert.ok(MAX_RECORD_SECONDS < 120)
})

test('parseServerEvent accepts JSON events and rejects everything else', () => {
  assert.deepEqual(parseServerEvent('{"type":"ready","session_id":"s"}'), { type: 'ready', session_id: 's' })
  for (const bad of ['', 'nope', '[]', '{}', '{"type":5}', 'null', new ArrayBuffer(4), undefined]) assert.equal(parseServerEvent(bad), null)
})
