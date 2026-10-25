import assert from 'node:assert/strict'
import { test } from 'node:test'
import { agentsApi } from './agents.js'
import { authApi } from './auth.js'
import { usersApi } from './users.js'
import { voiceAgentApi } from './voiceAgent.js'

// A recording stand-in for the client: endpoint modules only decide method, path, body and options.
function recorder() {
  const calls = []
  const record = (method) => (...args) => {
    calls.push({ method, args })
    return Promise.resolve(null)
  }
  return { calls, client: { get: record('get'), post: record('post'), patch: record('patch'), delete: record('delete') } }
}

test('login and register are public and use the documented bodies', async () => {
  const { client, calls } = recorder()
  const auth = authApi(client)
  await auth.login({ email: 'a@b.co', password: 'secret' })
  await auth.register({ email: 'a@b.co', password: 'secret123', fullName: 'Ada' })
  await auth.register({ email: 'a@b.co', password: 'secret123', fullName: '' })
  assert.deepEqual(calls[0].args, ['/auth/login', { email: 'a@b.co', password: 'secret' }, { auth: false }])
  assert.deepEqual(calls[1].args[1], { email: 'a@b.co', password: 'secret123', full_name: 'Ada' })
  assert.equal(calls[1].args[2].auth, false)
  assert.deepEqual(calls[2].args[1], { email: 'a@b.co', password: 'secret123' }) // blank name is omitted
})

test('users.me and voice status use the protected paths', async () => {
  const { client, calls } = recorder()
  await usersApi(client).me()
  await voiceAgentApi(client).status()
  assert.equal(calls[0].args[0], '/users/me')
  assert.equal(calls[1].args[0], '/voice-agent/status')
})

test('agents API targets the owner-scoped endpoints', async () => {
  const { client, calls } = recorder()
  const agents = agentsApi(client)
  await agents.list({ limit: 10, offset: 20 })
  await agents.get('abc')
  await agents.create({ name: 'A' })
  await agents.update('abc', { name: 'B' })
  await agents.remove('abc')
  assert.deepEqual(calls.map((c) => [c.method, c.args[0]]), [
    ['get', '/agents'],
    ['get', '/agents/abc'],
    ['post', '/agents'],
    ['patch', '/agents/abc'],
    ['delete', '/agents/abc'],
  ])
  assert.deepEqual(calls[0].args[1].query, { limit: 10, offset: 20 })
  assert.deepEqual(calls[3].args[1], { name: 'B' })
})

test('agent ids are encoded so they cannot alter the path', async () => {
  const { client, calls } = recorder()
  await agentsApi(client).get('../users/me')
  assert.equal(calls[0].args[0], '/agents/..%2Fusers%2Fme')
})
