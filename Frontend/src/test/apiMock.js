import { vi } from 'vitest'

/** Replaces the real `api` object (src/api/index.js) with mock functions; everything else in the module is kept. */
export function createApiModule(actual) {
  return {
    ...actual,
    api: {
      auth: { login: vi.fn(), register: vi.fn() },
      users: { me: vi.fn() },
      agents: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
      voiceAgent: { status: vi.fn() },
    },
  }
}
