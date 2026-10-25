import assert from 'node:assert/strict'
import { test } from 'node:test'
import { protectedDecision, safeRedirectTarget } from './guard.js'
import { createSessionStore } from './session.js'

test('a new session is anonymous with no token', () => {
  const store = createSessionStore()
  assert.equal(store.getState().status, 'anonymous')
  assert.equal(store.getToken(), null)
})

test('login flow: checking while the profile loads, then authenticated', () => {
  const store = createSessionStore()
  store.startChecking('tok')
  assert.equal(store.getState().status, 'checking')
  assert.equal(store.getToken(), 'tok')
  store.authenticate({ id: 'u1', email: 'a@b.co' })
  assert.equal(store.getState().status, 'authenticated')
  assert.equal(store.getState().user.email, 'a@b.co')
})

test('signOut clears the token and user', () => {
  const store = createSessionStore()
  store.startChecking('tok')
  store.authenticate({ id: 'u1' })
  store.signOut()
  assert.deepEqual([store.getState().status, store.getToken(), store.getState().user], ['anonymous', null, null])
})

test('expire (HTTP 401) clears everything and leaves a notice; repeated 401s are harmless', () => {
  const store = createSessionStore()
  let changes = 0
  store.subscribe(() => {
    changes += 1
  })
  store.startChecking('tok')
  store.authenticate({ id: 'u1' })
  const before = changes
  store.expire()
  store.expire()
  assert.equal(changes, before + 1)
  assert.equal(store.getToken(), null)
  assert.match(store.getState().notice, /expired/i)
  store.clearNotice()
  assert.equal(store.getState().notice, null)
})

test('a profile that arrives after sign-out does not resurrect the session', () => {
  const store = createSessionStore()
  store.startChecking('tok')
  store.signOut()
  store.authenticate({ id: 'u1' })
  assert.equal(store.getState().status, 'anonymous')
})

test('the token is never written to browser storage', () => {
  const writes = []
  globalThis.localStorage = { setItem: (...args) => writes.push(args) }
  globalThis.sessionStorage = { setItem: (...args) => writes.push(args) }
  try {
    const store = createSessionStore()
    store.startChecking('secret-token')
    store.authenticate({ id: 'u1' })
  } finally {
    delete globalThis.localStorage
    delete globalThis.sessionStorage
  }
  assert.deepEqual(writes, [])
})

test('protected pages wait while checking, allow when authenticated and otherwise send to login', () => {
  assert.equal(protectedDecision('authenticated'), 'allow')
  assert.equal(protectedDecision('checking'), 'wait')
  assert.equal(protectedDecision('anonymous'), 'login')
})

test('only in-app paths are honoured after login, and never the auth pages (no redirect loop)', () => {
  assert.equal(safeRedirectTarget('/agents/abc'), '/agents/abc')
  assert.equal(safeRedirectTarget('https://evil.example'), '/dashboard')
  assert.equal(safeRedirectTarget('//evil.example'), '/dashboard')
  assert.equal(safeRedirectTarget('/login'), '/dashboard')
  assert.equal(safeRedirectTarget(undefined), '/dashboard')
})
