import { useCallback } from 'react'
import { api } from '../../api/index.js'
import { useResource } from '../../hooks/useResource.js'

const LABELS = {
  ok: { text: 'Reachable', tone: 'badge-success' },
  not_configured: { text: 'Not configured', tone: 'badge-warning' },
  unavailable: { text: 'Unavailable', tone: 'badge-error' },
  timeout: { text: 'Timed out', tone: 'badge-error' },
}

/** Reads GET /voice-agent/status (the Backend's own check of the VoiceAgent service) and reports it as-is. */
export function useVoiceServiceStatus() {
  const fetcher = useCallback((signal) => api.voiceAgent.status({ signal }), [])
  return useResource(fetcher)
}

export function describeVoiceStatus({ data, error, loading }) {
  if (loading) return { text: 'Checking…', tone: '', detail: null, ok: false }
  if (error) return { text: 'Status unknown', tone: 'badge-warning', detail: error.message, ok: false }
  const entry = LABELS[data?.status] ?? { text: 'Status unknown', tone: 'badge-warning' }
  return { ...entry, detail: data?.detail ?? null, ok: data?.status === 'ok' }
}
