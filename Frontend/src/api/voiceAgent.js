// GET /voice-agent/status -> { configured: bool, status: 'ok'|'not_configured'|'unavailable'|'timeout', detail|null }
// Always HTTP 200 when authenticated; the body carries the result.

export function voiceAgentApi(client) {
  return {
    status(options) {
      return client.get('/voice-agent/status', options)
    },
  }
}
