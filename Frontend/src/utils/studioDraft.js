// If a save fails because the sign-in expired (or the network dropped), the user's edits must not be lost with the
// redirect to the login page. The unsaved form values are kept for this browser tab only (sessionStorage, gone when
// the tab closes) and offered back after signing in. They are agent text the user typed, never a token or secret.

const PREFIX = 'awaaz.studioDraft.'

function defaultStorage() {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    return null
  }
}

/** Returns true if the draft was kept. */
export function saveStudioDraft(agentId, form, storage = defaultStorage()) {
  try {
    if (!storage) return false
    storage.setItem(PREFIX + agentId, JSON.stringify({ form, savedAt: new Date().toISOString() }))
    return true
  } catch {
    return false
  }
}

/** The kept form values for an agent, or null. A corrupt entry is discarded. */
export function loadStudioDraft(agentId, storage = defaultStorage()) {
  try {
    const raw = storage?.getItem(PREFIX + agentId)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.form === 'object' && parsed.form !== null && typeof parsed.form.name === 'string') return parsed
    storage.removeItem(PREFIX + agentId)
    return null
  } catch {
    return null
  }
}

export function clearStudioDraft(agentId, storage = defaultStorage()) {
  try {
    storage?.removeItem(PREFIX + agentId)
  } catch {
    // nothing to clear
  }
}
