const dateTime = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' })
const dateOnly = new Intl.DateTimeFormat('en', { dateStyle: 'medium' })

export function formatDateTime(value) {
  const date = value ? new Date(value) : null
  return date && !Number.isNaN(date.getTime()) ? dateTime.format(date) : '-'
}

export function formatDate(value) {
  const date = value ? new Date(value) : null
  return date && !Number.isNaN(date.getTime()) ? dateOnly.format(date) : '-'
}

/** "Priya Sharma" -> "PS"; falls back to the start of the email. */
export function initials(user) {
  const source = (user?.full_name || user?.email || '?').trim()
  const parts = source.split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : source.slice(0, 2)
  return letters.toUpperCase()
}

export function firstName(user) {
  return user?.full_name?.trim().split(/\s+/)[0] || null
}

/** The voice saved on an agent, as stored: "Default voice · speed 1" or "provider · voice id · speed 1.2". */
export function voiceSummary(agent) {
  const voice = agent.voice_config
  const name = voice.provider || voice.voice_id ? [voice.provider, voice.voice_id].filter(Boolean).join(' · ') : 'Default voice'
  return `${name} · speed ${voice.speed}`
}
