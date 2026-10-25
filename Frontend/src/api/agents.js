// Owner-scoped agent CRUD. The server decides ownership; other users' agents simply answer 404.
//
// Agent: { id, owner_id, name, description|null, system_prompt, language, voice_config, is_active, created_at, updated_at }
// voice_config: { provider|null, voice_id|null, speed (0.5-2.0) }
// GET /agents is a plain array (no total): ?limit=1..100 (default 50) and ?offset>=0.

export const AGENTS_PAGE_SIZE = 50

export function agentsApi(client) {
  return {
    list({ limit = AGENTS_PAGE_SIZE, offset = 0 } = {}, options) {
      return client.get('/agents', { ...options, query: { limit, offset } })
    },
    get(id, options) {
      return client.get(`/agents/${encodeURIComponent(id)}`, options)
    },
    create(payload, options) {
      return client.post('/agents', payload, options)
    },
    update(id, changes, options) {
      return client.patch(`/agents/${encodeURIComponent(id)}`, changes, options)
    },
    remove(id, options) {
      return client.delete(`/agents/${encodeURIComponent(id)}`, options)
    },
  }
}
