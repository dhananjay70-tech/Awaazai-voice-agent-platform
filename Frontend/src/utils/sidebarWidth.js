// Width rules for the resizable sidebar. Pure functions, so they are easy to test; the component only wires them to events.

export const SIDEBAR_MIN = 180
export const SIDEBAR_MAX = 320
export const SIDEBAR_DEFAULT = 240
export const KEY_STEP = 16
export const KEY_STEP_LARGE = 48
export const SIDEBAR_WIDTH_KEY = 'awaaz.sidebarWidth' // a layout preference only, never a credential

export function clampSidebarWidth(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return SIDEBAR_DEFAULT
  return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(number)))
}

/** The stored value if it is a sane number, otherwise the default. */
export function readStoredWidth(storage = defaultStorage()) {
  try {
    const raw = storage?.getItem(SIDEBAR_WIDTH_KEY)
    return raw == null ? SIDEBAR_DEFAULT : clampSidebarWidth(raw)
  } catch {
    return SIDEBAR_DEFAULT
  }
}

export function storeWidth(width, storage = defaultStorage()) {
  try {
    storage?.setItem(SIDEBAR_WIDTH_KEY, String(clampSidebarWidth(width)))
  } catch {
    // storage unavailable: the width just won't be remembered
  }
}

function defaultStorage() {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

/** Width while dragging: where the pointer started, how far it has moved, kept within the limits. */
export function widthFromDrag(startWidth, startX, currentX) {
  return clampSidebarWidth(startWidth + (currentX - startX))
}

/** The new width for a key on the resize separator, or null if the key does nothing. */
export function widthFromKey(width, key, { shift = false } = {}) {
  const step = shift ? KEY_STEP_LARGE : KEY_STEP
  switch (key) {
    case 'ArrowLeft':
      return clampSidebarWidth(width - step)
    case 'ArrowRight':
      return clampSidebarWidth(width + step)
    case 'Home':
      return SIDEBAR_MIN
    case 'End':
      return SIDEBAR_MAX
    case 'Enter':
      return SIDEBAR_DEFAULT
    default:
      return null
  }
}
