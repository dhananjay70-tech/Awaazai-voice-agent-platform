import { useCallback, useMemo, useSyncExternalStore } from 'react'
import { api } from '../api/index.js'
import { AuthContext } from './AuthContext.js'
import { session } from './session.js'

export default function AuthProvider({ children }) {
  const state = useSyncExternalStore(session.subscribe, session.getState)

  const login = useCallback(async ({ email, password }) => {
    const { access_token: token } = await api.auth.login({ email, password })
    session.startChecking(token)
    try {
      session.authenticate(await api.users.me())
    } catch (error) {
      session.signOut()
      throw error
    }
  }, [])

  const register = useCallback(
    async ({ fullName, email, password }) => {
      await api.auth.register({ fullName, email, password })
      await login({ email, password })
    },
    [login],
  )

  // There is no logout endpoint: signing out only forgets the in-memory token.
  const signOut = useCallback(() => session.signOut(), [])

  const value = useMemo(
    () => ({
      status: state.status,
      user: state.user,
      notice: state.notice,
      isAuthenticated: state.status === 'authenticated',
      login,
      register,
      signOut,
      clearNotice: session.clearNotice,
    }),
    [state, login, register, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
