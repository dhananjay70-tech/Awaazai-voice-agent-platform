// POST /auth/register -> UserRead (201). POST /auth/login -> { access_token, token_type, expires_in }.
// There is no logout or refresh endpoint: signing out only clears the in-memory session.

export function authApi(client) {
  return {
    register({ email, password, fullName }, options) {
      const body = { email, password }
      if (fullName) body.full_name = fullName
      return client.post('/auth/register', body, { ...options, auth: false })
    },
    login({ email, password }, options) {
      return client.post('/auth/login', { email, password }, { ...options, auth: false })
    },
  }
}
