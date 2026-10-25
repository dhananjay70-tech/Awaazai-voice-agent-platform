// The backend agent schema has no "first message" field, so a greeting cannot be saved to the server or sent to the voice
// service. Until it can, the draft is kept in THIS browser only (one entry per agent id) so it is not lost on reload.
// The UI must say so: this is a local draft, not persisted agent configuration.

const PREFIX = 'awaaz.firstMessageDraft.'
export const MAX_FIRST_MESSAGE = 500

function defaultStorage() {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null // storage blocked (private mode, policy)
  }
}

export function loadFirstMessageDraft(agentId, storage = defaultStorage()) {
  try {
    return storage?.getItem(PREFIX + agentId) ?? ''
  } catch {
    return ''
  }
}

/** Returns true if the draft was stored in this browser. */
export function saveFirstMessageDraft(agentId, text, storage = defaultStorage()) {
  try {
    if (!storage) return false
    if (text) storage.setItem(PREFIX + agentId, text)
    else storage.removeItem(PREFIX + agentId)
    return true
  } catch {
    return false
  }
}

export function clearFirstMessageDraft(agentId, storage = defaultStorage()) {
  saveFirstMessageDraft(agentId, '', storage)
}
