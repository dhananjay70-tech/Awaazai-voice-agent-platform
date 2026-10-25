import { act, render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { vi } from 'vitest'
import { api, ApiError } from '../api/index.js'
import { routes } from '../app/router.jsx'
import AuthProvider from '../auth/AuthProvider.jsx'
import { session } from '../auth/session.js'
import ToastProvider from '../components/ui/Toasts.jsx'

export const USER = { id: 'u1', email: 'ada@example.com', full_name: 'Ada Lovelace', is_active: true, created_at: '2026-01-01T00:00:00Z' }

export function makeAgent(overrides = {}) {
  return {
    id: 'a1',
    owner_id: 'u1',
    name: 'Alpha',
    description: 'Books appointments',
    system_prompt: 'You are a friendly receptionist.',
    language: 'en',
    voice_config: { provider: null, voice_id: null, speed: 1 },
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

export const AGENTS = [
  makeAgent(),
  makeAgent({ id: 'a2', name: 'Beta', description: null, language: 'hi', is_active: false }),
  makeAgent({ id: 'a3', name: 'Gamma', description: 'Sales calls', language: 'hi-Latn' }),
]

const clone = (value) => JSON.parse(JSON.stringify(value))

/**
 * A stand-in for the Backend's agent endpoints that behaves like the real one: it keeps agents between calls, applies
 * a PATCH only to the fields sent, bumps updated_at, and answers a later GET with what was actually stored. Tests can
 * change a stored agent "from another tab" with changeElsewhere(), or make the server ignore fields with server.ignore.
 */
export const server = { agents: new Map(), clock: 0, ignore: [], created: 0 }

const stamp = () => `2026-02-01T00:00:${String(++server.clock).padStart(2, '0')}Z`
const notFound = () => new ApiError({ status: 404, code: 'not_found', message: 'Agent not found' })

export function changeElsewhere(id, patch) {
  Object.assign(server.agents.get(id), clone(patch), { updated_at: stamp() })
}

function resetServer() {
  server.agents = new Map(AGENTS.map((agent) => [agent.id, clone(agent)]))
  server.clock = 0
  server.ignore = []
  server.created = 0
}

/** Fresh, working defaults for every API call; a test overrides only what it cares about. */
export function resetApi() {
  resetServer()
  vi.mocked(api.auth.login).mockReset().mockResolvedValue({ access_token: 'tok', token_type: 'bearer', expires_in: 1800 })
  vi.mocked(api.auth.register).mockReset().mockResolvedValue(USER)
  vi.mocked(api.users.me).mockReset().mockResolvedValue(USER)
  vi.mocked(api.agents.list).mockReset().mockImplementation(async () => [...server.agents.values()].map(clone))
  vi.mocked(api.agents.get).mockReset().mockImplementation(async (id) => {
    if (!server.agents.has(id)) throw notFound()
    return clone(server.agents.get(id))
  })
  vi.mocked(api.agents.create).mockReset().mockImplementation(async (payload) => {
    const agent = makeAgent({ ...payload, id: `new-${++server.created}`, created_at: stamp(), updated_at: stamp() })
    server.agents.set(agent.id, agent)
    return clone(agent)
  })
  vi.mocked(api.agents.update).mockReset().mockImplementation(async (id, patch) => {
    const agent = server.agents.get(id)
    if (!agent) throw notFound()
    for (const [key, value] of Object.entries(patch)) if (!server.ignore.includes(key)) agent[key] = clone(value)
    agent.updated_at = stamp()
    return clone(agent)
  })
  vi.mocked(api.agents.remove).mockReset().mockImplementation(async (id) => {
    if (!server.agents.delete(id)) throw notFound()
    return null
  })
  vi.mocked(api.voiceAgent.status).mockReset().mockResolvedValue({ configured: true, status: 'ok', detail: null })
}

export function signIn() {
  act(() => {
    session.startChecking('test-token')
    session.authenticate(USER)
  })
}

/** Render the real route table at `path`. Signed in by default. */
export function renderApp(path = '/', { signedIn = true } = {}) {
  if (signedIn) signIn()
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const utils = render(
    <AuthProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </AuthProvider>,
  )
  return { router, ...utils }
}
