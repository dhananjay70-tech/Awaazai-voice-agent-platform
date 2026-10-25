import assert from 'node:assert/strict'
import { test } from 'node:test'
import { playgroundStateKey, PLAYGROUND_STATES, turnToEntry } from './playgroundState.js'
import { initialState } from './voiceState.js'

const base = { session: 'open', phase: 'idle', mode: 'speak', speaking: false, error: null }
const key = (overrides) => playgroundStateKey({ ...base, ...overrides })

test('nothing is "connected" before a session is opened', () => {
  assert.equal(key({ session: 'closed' }), 'idle')
  assert.equal(key({ session: 'closed', phase: 'listening' }), 'idle')
})

test('an open session waits as Ready, including after a finished turn', () => {
  assert.equal(key({}), 'ready')
  assert.equal(key({ phase: 'done' }), 'ready')
})

test('each phase of a turn has its own state', () => {
  assert.equal(key({ phase: 'requesting-mic' }), 'connecting')
  assert.equal(key({ phase: 'connecting' }), 'connecting')
  assert.equal(key({ phase: 'listening' }), 'listening')
  assert.equal(key({ phase: 'processing' }), 'processing')
  assert.equal(key({ phase: 'processing', speaking: true }), 'speaking')
  assert.equal(key({ phase: 'done', speaking: true }), 'speaking')
})

test('a typed message is never reported as "listening"', () => {
  assert.equal(key({ phase: 'listening', mode: 'text' }), 'processing')
})

test('failures are told apart', () => {
  assert.equal(key({ phase: 'error', error: { code: 'permission_denied' } }), 'permission-denied')
  assert.equal(key({ phase: 'error', error: { code: 'connection_lost' } }), 'disconnected')
  assert.equal(key({ phase: 'error', error: { code: 'connection_failed' } }), 'error')
  assert.equal(key({ phase: 'error', error: { code: 'no_audio' } }), 'error')
})

test('an ended session wins over everything else', () => {
  assert.equal(key({ session: 'ended', phase: 'listening' }), 'ended')
})

test('every state key has a label, tone and explanation', () => {
  for (const [name, entry] of Object.entries(PLAYGROUND_STATES)) {
    assert.ok(entry.label && typeof entry.tone === 'string' && entry.detail, name)
  }
})

test('a finished spoken turn becomes a transcript entry from the final transcripts and the reply', () => {
  const state = { ...initialState, finals: ['hello', 'there'], replyText: ' Hi! ', audioComplete: true }
  assert.deepEqual(turnToEntry(state, { mode: 'speak', typedText: '' }), { user: 'hello there', agent: 'Hi!', audioComplete: true, warnings: 0 })
})

test('a typed turn uses the typed text, and an empty turn produces no entry', () => {
  const state = { ...initialState, replyText: 'Sure.' }
  assert.equal(turnToEntry(state, { mode: 'text', typedText: ' book me ' }).user, 'book me')
  assert.equal(turnToEntry(initialState, { mode: 'speak', typedText: '' }), null)
})
