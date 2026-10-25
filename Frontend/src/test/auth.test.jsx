import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/index.js'
import { session } from '../auth/session.js'
import { renderApp, resetApi, USER } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

function apiError(status, code, message, details) {
  return new ApiError({ status, code, message, details, requestId: 'req-1' })
}

describe('login', () => {
  it('labels its fields and validates before sending anything', async () => {
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    await user.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(screen.getByText('Enter your email address.')).toBeTruthy()
    expect(screen.getByText('Enter your password.')).toBeTruthy()
    expect(screen.getByLabelText('Email').getAttribute('aria-invalid')).toBe('true')
    expect(api.auth.login).not.toHaveBeenCalled()
  })

  it('shows the backend message and request id when sign-in fails, and stays on the page', async () => {
    vi.mocked(api.auth.login).mockRejectedValue(apiError(401, 'invalid_credentials', 'Invalid email or password'))
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-pass')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Invalid email or password')).toBeTruthy()
    expect(screen.getByText('Request ID: req-1')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeTruthy()
    expect(session.getToken()).toBeNull()
  })

  it('disables the form while signing in and sends only one request', async () => {
    let finish
    vi.mocked(api.auth.login).mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    const submit = screen.getByRole('button', { name: 'Sign in' })
    await user.click(submit)
    const busy = await screen.findByRole('button', { name: /Signing in/ })
    expect(busy.hasAttribute('disabled')).toBe(true)
    await user.click(busy)
    await user.keyboard('{Enter}')
    finish({ access_token: 'tok', token_type: 'bearer', expires_in: 1800 })
    await screen.findByRole('heading', { level: 1, name: 'Home' })
    expect(api.auth.login).toHaveBeenCalledTimes(1)
  })

  it('keeps the token in memory and loads the profile after a successful sign-in', async () => {
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { level: 1, name: 'Home' })
    expect(api.auth.login).toHaveBeenCalledWith({ email: 'ada@example.com', password: 'secret-pass' })
    expect(api.users.me).toHaveBeenCalled()
    expect(session.getToken()).toBe('tok')
    expect(session.getState().user).toEqual(USER)
  })

  it('signs the user out again if the profile cannot be loaded, and says why', async () => {
    vi.mocked(api.users.me).mockRejectedValue(apiError(503, 'database_unavailable', 'The database is not available'))
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('The database is not available')).toBeTruthy()
    expect(session.getToken()).toBeNull()
    expect((screen.getByLabelText('Email')).value).toBe('ada@example.com') // the form kept what was typed
  })

  it('toggles password visibility', async () => {
    const user = userEvent.setup()
    renderApp('/login', { signedIn: false })
    const password = await screen.findByLabelText('Password')
    expect(password.getAttribute('type')).toBe('password')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(password.getAttribute('type')).toBe('text')
    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(password.getAttribute('type')).toBe('password')
  })
})

describe('registration', () => {
  async function fill(user, { name = 'Ada', email = 'ada@example.com', password = 'longenough', confirm = 'longenough' } = {}) {
    await user.type(await screen.findByLabelText(/Full name/), name)
    await user.type(screen.getByLabelText('Email'), email)
    await user.type(screen.getByLabelText('Password'), password)
    await user.type(screen.getByLabelText('Confirm password'), confirm)
  }

  it('checks password length and confirmation on the client', async () => {
    const user = userEvent.setup()
    renderApp('/register', { signedIn: false })
    await fill(user, { password: 'short', confirm: 'different' })
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Use at least 8 characters.')).toBeTruthy()
    expect(api.auth.register).not.toHaveBeenCalled()
    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), 'longenough')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('Passwords do not match.')).toBeTruthy()
  })

  it('creates the account, signs in and lands on the dashboard', async () => {
    const user = userEvent.setup()
    renderApp('/register', { signedIn: false })
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await screen.findByRole('heading', { level: 1, name: 'Home' })
    expect(api.auth.register).toHaveBeenCalledWith({ fullName: 'Ada', email: 'ada@example.com', password: 'longenough' })
    expect(api.auth.login).toHaveBeenCalledTimes(1)
  })

  it('shows a duplicate email on the email field', async () => {
    vi.mocked(api.auth.register).mockRejectedValue(apiError(409, 'email_already_registered', 'An account with this email already exists'))
    const user = userEvent.setup()
    renderApp('/register', { signedIn: false })
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => expect(screen.getByLabelText('Email').getAttribute('aria-invalid')).toBe('true'))
    expect(screen.getAllByText('An account with this email already exists.').length).toBeGreaterThan(0)
    expect(api.auth.login).not.toHaveBeenCalled()
  })

  it('maps server validation details onto fields', async () => {
    vi.mocked(api.auth.register).mockRejectedValue(
      apiError(422, 'validation_error', 'Request validation failed', [{ field: 'email', message: 'value is not a valid email address' }]),
    )
    const user = userEvent.setup()
    renderApp('/register', { signedIn: false })
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('value is not a valid email address')).toBeTruthy()
  })
})
