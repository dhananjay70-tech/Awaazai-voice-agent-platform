import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, createClient, fieldErrorsFrom, parseErrorResponse } from './client.js'

function fakeFetch(responses) {
  const calls = []
  const impl = async (url, init) => {
    calls.push({ url, init })
    const next = typeof responses === 'function' ? responses(url, init) : responses
    if (next instanceof Error) throw next
    const { status = 200, body = '' } = next
    return { ok: status >= 200 && status < 300, status, text: async () => (typeof body === 'string' ? body : JSON.stringify(body)) }
  }
  return { impl, calls }
}

function setup(responses, { token = 'tok-123' } = {}) {
  const fetch = fakeFetch(responses)
  let unauthorized = 0
  const client = createClient({
    baseUrl: 'http://api.test/api/v1/',
    getToken: () => token,
    onUnauthorized: () => {
      unauthorized += 1
    },
    fetchImpl: fetch.impl,
  })
  return { client, calls: fetch.calls, unauthorizedCount: () => unauthorized }
}

test('a successful JSON response is parsed and the bearer token is sent', async () => {
  const { client, calls } = setup({ body: { id: '1' } })
  assert.deepEqual(await client.get('/users/me'), { id: '1' })
  assert.equal(calls[0].url, 'http://api.test/api/v1/users/me')
  assert.equal(calls[0].init.headers.Authorization, 'Bearer tok-123')
  assert.equal(calls[0].init.body, undefined)
})

test('JSON bodies get a content type; query values that are empty are dropped', async () => {
  const { client, calls } = setup({ status: 201, body: { ok: true } })
  await client.post('/agents', { name: 'A' })
  assert.equal(calls[0].init.headers['Content-Type'], 'application/json')
  assert.equal(calls[0].init.body, '{"name":"A"}')
  await client.get('/agents', { query: { limit: 50, offset: 0, q: '' } })
  assert.equal(calls[1].url, 'http://api.test/api/v1/agents?limit=50&offset=0')
})

test('an empty 204 body resolves to null', async () => {
  const { client } = setup({ status: 204, body: '' })
  assert.equal(await client.delete('/agents/1'), null)
})

test('requests without a token never reach the network and count as unauthorized', async () => {
  const { client, calls, unauthorizedCount } = setup({ body: {} }, { token: null })
  await assert.rejects(client.get('/agents'), (error) => error instanceof ApiError && error.status === 401 && error.code === 'not_authenticated')
  assert.equal(calls.length, 0)
  assert.equal(unauthorizedCount(), 1)
})

test('public requests (login) send no Authorization header and a 401 does not expire the session', async () => {
  const body = { error: { code: 'invalid_credentials', message: 'Invalid email or password', request_id: 'r1' } }
  const { client, calls, unauthorizedCount } = setup({ status: 401, body }, { token: 'stale' })
  await assert.rejects(client.post('/auth/login', {}, { auth: false }), (error) => error.code === 'invalid_credentials')
  assert.equal(calls[0].init.headers.Authorization, undefined)
  assert.equal(unauthorizedCount(), 0)
})

test('a 401 on a protected request calls onUnauthorized and still throws', async () => {
  const { client, unauthorizedCount } = setup({ status: 401, body: { error: { code: 'invalid_token', message: 'Could not validate credentials' } } })
  await assert.rejects(client.get('/users/me'), (error) => error.isUnauthorized && error.code === 'invalid_token')
  assert.equal(unauthorizedCount(), 1)
})

test('backend error shape is normalised, including request id and details', async () => {
  const body = {
    error: { code: 'validation_error', message: 'Request validation failed', request_id: 'req-9', details: [{ field: 'name', message: 'Must not be blank' }] },
  }
  const { client } = setup({ status: 422, body })
  await assert.rejects(client.post('/agents', {}), (error) => {
    assert.equal(error.status, 422)
    assert.equal(error.requestId, 'req-9')
    assert.equal(error.diagnostic, 'Request ID: req-9')
    assert.deepEqual(fieldErrorsFrom(error), { name: 'Must not be blank' })
    return true
  })
})

test('error responses without details or that are not JSON still produce a usable message', () => {
  const plain = parseErrorResponse(409, JSON.stringify({ error: { code: 'agent_name_conflict', message: 'You already have an agent with this name' } }))
  assert.equal(plain.details, null)
  assert.equal(plain.message, 'You already have an agent with this name')
  const html = parseErrorResponse(502, '<html>Bad gateway</html>')
  assert.equal(html.code, 'http_502')
  assert.match(html.message, /unavailable/i)
  assert.equal(parseErrorResponse(500, '').status, 500)
})

test('a network failure becomes a network ApiError', async () => {
  const { client } = setup(new TypeError('Failed to fetch'))
  await assert.rejects(client.get('/agents'), (error) => error.isNetworkError && error.code === 'network_error')
})

test('aborting a request rethrows the AbortError instead of reporting a network failure', async () => {
  const abort = new DOMException('aborted', 'AbortError')
  const { client } = setup(abort)
  await assert.rejects(client.get('/agents'), (error) => error.name === 'AbortError')
})

test('a successful response that is not JSON is reported, not returned', async () => {
  const { client } = setup({ body: 'not json' })
  await assert.rejects(client.get('/agents'), (error) => error.code === 'invalid_response')
})

test('fieldErrorsFrom ignores errors without field details', () => {
  assert.deepEqual(fieldErrorsFrom(new Error('x')), {})
  assert.deepEqual(fieldErrorsFrom(new ApiError({ status: 422, code: 'c', message: 'm', details: { foo: 1 } })), {})
})
