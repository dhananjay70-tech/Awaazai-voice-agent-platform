// In-memory session store. The bearer token lives only here: it is never written to localStorage, sessionStorage
// or cookies, so reloading the page ends the session (the backend has no refresh tokens and tokens last 30 minutes).

export function createSessionStore() {
  let state = { status: 'anonymous', token: null, user: null, notice: null }
  const listeners = new Set()

  function set(next) {
    state = { ...state, ...next }
    listeners.forEach((listener) => listener())
  }

  return {
    getState: () => state,
    getToken: () => state.token,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    /** A token was issued; the user profile is still being loaded. */
    startChecking(token) {
      set({ status: 'checking', token, user: null, notice: null })
    },
    authenticate(user) {
      if (state.status !== 'checking' && state.status !== 'authenticated') return // signed out meanwhile
      set({ status: 'authenticated', user, notice: null })
    },
    signOut(notice = null) {
      set({ status: 'anonymous', token: null, user: null, notice })
    },
    /** A protected request was refused (HTTP 401): forget the session and say why. */
    expire() {
      if (state.status === 'anonymous') return
      set({ status: 'anonymous', token: null, user: null, notice: 'Your session expired. Please sign in again.' })
    },
    clearNotice() {
      if (state.notice) set({ notice: null })
    },
  }
}

export const session = createSessionStore()
