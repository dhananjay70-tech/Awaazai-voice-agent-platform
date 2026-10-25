// Agent form state <-> Backend payloads (Backend/app/schemas/agent.py).

export const MAX_NAME = 100
export const MAX_DESCRIPTION = 500
export const MAX_SYSTEM_PROMPT = 10_000
export const MIN_SPEED = 0.5
export const MAX_SPEED = 2.0
export const MAX_PROVIDER = 50
export const MAX_VOICE_ID = 100
const LANGUAGE_PATTERN = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/

export function emptyAgentForm() {
  return {
    name: '',
    description: '',
    systemPrompt: '',
    language: 'en',
    isActive: true,
    voiceProvider: '',
    voiceId: '',
    speed: 1,
  }
}

/** Server agent -> form values. */
export function agentToForm(agent) {
  return {
    name: agent.name,
    description: agent.description ?? '',
    systemPrompt: agent.system_prompt,
    language: agent.language,
    isActive: agent.is_active,
    voiceProvider: agent.voice_config?.provider ?? '',
    voiceId: agent.voice_config?.voice_id ?? '',
    speed: agent.voice_config?.speed ?? 1,
  }
}

function voiceConfigOf(form) {
  return {
    provider: form.voiceProvider.trim() || null,
    voice_id: form.voiceId.trim() || null,
    speed: Number(form.speed),
  }
}

/** Form values -> POST /agents body. */
export function formToCreatePayload(form) {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    system_prompt: form.systemPrompt.trim(),
    language: form.language,
    voice_config: voiceConfigOf(form),
    is_active: form.isActive,
  }
}

/** Only the fields that differ from the saved agent, for PATCH (the backend leaves omitted fields untouched). */
export function formToPatch(form, saved) {
  const next = formToCreatePayload(form)
  const before = formToCreatePayload(agentToForm(saved))
  const patch = {}
  for (const key of ['name', 'description', 'system_prompt', 'language', 'is_active']) {
    if (next[key] !== before[key]) patch[key] = next[key]
  }
  const a = next.voice_config
  const b = before.voice_config
  if (a.provider !== b.provider || a.voice_id !== b.voice_id || a.speed !== b.speed) patch.voice_config = a
  return patch
}

/**
 * True when saving would change something. It compares what would actually be sent (trimmed text, null for blanks,
 * numeric speed), so an edit the server could never see, such as a trailing space, is not an "unsaved change".
 */
export function isDirty(form, baseline) {
  return JSON.stringify(formToCreatePayload(form)) !== JSON.stringify(formToCreatePayload(baseline))
}

const FIELD_LABELS = {
  name: 'name',
  description: 'description',
  system_prompt: 'system prompt',
  language: 'language',
  is_active: 'active status',
  voice_config: 'voice settings',
}

/** Human names of the fields in a PATCH body ("name", "voice settings"). */
export function fieldLabels(patchOrKeys) {
  const keys = Array.isArray(patchOrKeys) ? patchOrKeys : Object.keys(patchOrKeys)
  return keys.map((key) => FIELD_LABELS[key] ?? key)
}

/** Which fields differ between two server agents (e.g. the copy we loaded and the copy now on the server). */
export function changedFields(a, b) {
  const left = formToCreatePayload(agentToForm(a))
  const right = formToCreatePayload(agentToForm(b))
  return Object.keys(left).filter((key) => JSON.stringify(left[key]) !== JSON.stringify(right[key]))
}

/**
 * After a save, compare what we sent with the agent read back from the server. Returns the keys of the fields the
 * server did NOT store as sent (an empty list means the save is confirmed).
 */
export function unsavedKeys(patch, stored) {
  const actual = formToCreatePayload(agentToForm(stored))
  return Object.keys(patch).filter((key) => JSON.stringify(patch[key]) !== JSON.stringify(actual[key]))
}

/** Returns { fieldName: message }. */
export function validateAgentForm(form) {
  const errors = {}
  const name = form.name.trim()
  if (!name) errors.name = 'Give your agent a name.'
  else if (name.length > MAX_NAME) errors.name = `Name must be at most ${MAX_NAME} characters.`
  if (form.description.trim().length > MAX_DESCRIPTION) {
    errors.description = `Description must be at most ${MAX_DESCRIPTION} characters.`
  }
  if (!form.systemPrompt.trim()) errors.systemPrompt = 'Write instructions for the agent.'
  else if (form.systemPrompt.length > MAX_SYSTEM_PROMPT) {
    errors.systemPrompt = `Instructions must be at most ${MAX_SYSTEM_PROMPT.toLocaleString('en-US')} characters.`
  }
  if (!LANGUAGE_PATTERN.test(form.language)) errors.language = 'Choose a language.'
  if (form.voiceProvider.trim().length > MAX_PROVIDER) errors.voiceProvider = `Provider must be at most ${MAX_PROVIDER} characters.`
  if (form.voiceId.trim().length > MAX_VOICE_ID) errors.voiceId = `Voice ID must be at most ${MAX_VOICE_ID} characters.`
  const speed = Number(form.speed)
  if (form.speed === '' || Number.isNaN(speed) || speed < MIN_SPEED || speed > MAX_SPEED) {
    errors.speed = `Speed must be between ${MIN_SPEED} and ${MAX_SPEED}.`
  }
  return errors
}

const BACKEND_FIELD_TO_FORM = {
  name: 'name',
  description: 'description',
  system_prompt: 'systemPrompt',
  language: 'language',
  is_active: 'isActive',
  'voice_config.provider': 'voiceProvider',
  'voice_config.voice_id': 'voiceId',
  'voice_config.speed': 'speed',
}

/** Translate backend field names ({ system_prompt: msg }) to form field names ({ systemPrompt: msg }). */
export function backendFieldsToForm(fieldErrors) {
  const mapped = {}
  for (const [field, message] of Object.entries(fieldErrors)) {
    const key = BACKEND_FIELD_TO_FORM[field]
    if (key) mapped[key] = message
  }
  return mapped
}

/** Which Agent Studio tab holds a form field: all of them live on the Agent tab. */
export const FIELD_TAB = {
  name: 'agent',
  description: 'agent',
  isActive: 'agent',
  systemPrompt: 'agent',
  language: 'agent',
  voiceProvider: 'agent',
  voiceId: 'agent',
  speed: 'agent',
}
