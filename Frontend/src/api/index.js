import { session } from '../auth/session.js'
import { authApi } from './auth.js'
import { agentsApi } from './agents.js'
import { createClient, DEFAULT_API_BASE_URL } from './client.js'
import { usersApi } from './users.js'
import { voiceAgentApi } from './voiceAgent.js'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL

export const client = createClient({
  baseUrl: API_BASE_URL,
  getToken: session.getToken,
  onUnauthorized: () => session.expire(),
})

export const api = {
  auth: authApi(client),
  users: usersApi(client),
  agents: agentsApi(client),
  voiceAgent: voiceAgentApi(client),
}

export { ApiError, fieldErrorsFrom, isAbortError } from './client.js'
