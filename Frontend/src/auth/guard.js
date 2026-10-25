// Route-guard decisions as pure functions (the React components only act on them).

/** What a protected page should do for the current session status: 'wait' | 'allow' | 'login'. */
export function protectedDecision(status) {
  if (status === 'authenticated') return 'allow'
  if (status === 'checking') return 'wait'
  return 'login'
}

/** Only same-app paths are honoured after login, so a crafted link cannot send the user elsewhere. */
export function safeRedirectTarget(from, fallback = '/dashboard') {
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//')) return fallback
  if (from === '/login' || from === '/register') return fallback
  return from
}
