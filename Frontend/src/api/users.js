// GET /users/me -> { id, email, full_name, is_active, created_at }

export function usersApi(client) {
  return {
    me(options) {
      return client.get('/users/me', options)
    },
  }
}
