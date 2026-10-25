import { Navigate, Outlet, useLocation } from 'react-router-dom'
import PageLoading from '../components/ui/PageLoading.jsx'
import { protectedDecision, safeRedirectTarget } from './guard.js'
import { useAuth } from './useAuth.js'

/** Wraps pages that need a signed-in user. Authorization is decided by the session, not by navigation state. */
export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  const decision = protectedDecision(status)
  if (decision === 'wait') return <PageLoading label="Checking your session…" />
  if (decision === 'login') {
    const from = `${location.pathname}${location.search}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  return <Outlet />
}

/** Login and register: signed-in users go straight to where they were headed (or the dashboard). */
export function RedirectIfAuthenticated() {
  const { status } = useAuth()
  const location = useLocation()
  // While the profile loads ("checking") the form stays mounted, so it keeps its values and can show a failure.
  if (status === 'authenticated') return <Navigate to={safeRedirectTarget(location.state?.from)} replace />
  return <Outlet />
}
