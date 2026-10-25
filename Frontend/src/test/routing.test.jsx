import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { session } from '../auth/session.js'
import { APP_NAV } from '../components/layout/navigation.js'
import { renderApp, resetApi } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

const h1 = (name) => screen.findByRole('heading', { level: 1, name })

describe('public routes', () => {
  it('shows the landing page with working account links', async () => {
    renderApp('/', { signedIn: false })
    expect(await screen.findByRole('heading', { level: 1, name: 'Build voice agents your way.' })).toBeTruthy()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/login')
    expect(within(nav).getByRole('link', { name: 'Get Started' }).getAttribute('href')).toBe('/register')
    expect(screen.getByRole('link', { name: 'Explore the Demo' }).getAttribute('href')).toBe('/voice-test')
  })

  it('every landing navigation link points at a section that exists', async () => {
    renderApp('/', { signedIn: false })
    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    for (const link of within(nav).getAllByRole('link')) {
      const href = link.getAttribute('href')
      if (!href.includes('#')) continue
      expect(document.getElementById(href.split('#')[1]), href).not.toBeNull()
    }
  })

  it('the mobile menu opens, closes with the button and with Escape', async () => {
    const user = userEvent.setup()
    renderApp('/', { signedIn: false })
    const toggle = await screen.findByRole('button', { name: 'Open menu' })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'Close menu' }).getAttribute('aria-expanded')).toBe('true')
    expect(document.getElementById('site-nav').className).toContain('is-open')
    await user.keyboard('{Escape}')
    expect(document.getElementById('site-nav').className).not.toContain('is-open')
  })

  it('shows a 404 page for unknown routes', async () => {
    renderApp('/definitely/not/here', { signedIn: false })
    expect(await screen.findByText('Page not found')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Go to the home page' }).getAttribute('href')).toBe('/')
  })
})

describe('protected routes', () => {
  it('sends anonymous visitors to the login page', async () => {
    renderApp('/agents', { signedIn: false })
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy()
  })

  it('returns to the page the visitor asked for after signing in', async () => {
    const user = userEvent.setup()
    renderApp('/agents', { signedIn: false })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await h1('Agents')).toBeTruthy()
  })

  it('keeps signed-in users away from the login page', async () => {
    renderApp('/login')
    expect(await h1('Home')).toBeTruthy()
  })

  it('an expired session (HTTP 401) returns the user to login with an explanation', async () => {
    renderApp('/dashboard')
    await h1('Home')
    act(() => session.expire())
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy()
    expect(screen.getByText(/session expired/i)).toBeTruthy()
  })

  it('signing out from the profile menu clears the session and shows login', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: /Account menu/ }))
    await user.click(screen.getByRole('menuitem', { name: /Sign out/ }))
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy()
    expect(session.getToken()).toBeNull()
  })
})

describe('application shell', () => {
  it('has every requested sidebar item and each one navigates to its own page', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    await h1('Home')
    expect(APP_NAV.map((item) => item.label)).toEqual([
      'Home',
      'Agents',
      'Playground',
      'Knowledge Base',
      'Tools',
      'Workflows',
      'Integrations',
      'Voices',
      'Conversations',
      'Users',
      'Tests',
      'Analytics',
      'Phone Numbers',
      'Deployment',
      'Settings',
      'Help',
    ])
    const sidebar = () => within(document.getElementById('app-sidebar'))
    const link = (label) => sidebar().getByRole('link', { name: new RegExp(`^${label}`) })
    const seenTitles = new Set()
    for (const item of APP_NAV) {
      await user.click(link(item.label))
      const title = item.label === 'Settings' ? 'Profile' : item.label // /settings opens its first page
      expect(await h1(title)).toBeTruthy()
      seenTitles.add(document.querySelector('main h2, main h3')?.textContent)
      await waitFor(() => expect(link(item.label).getAttribute('aria-current')).toBe('page'))
    }
    expect(seenTitles.size).toBeGreaterThan(10) // pages are not all the same placeholder
  })

  it('groups the sidebar into Main, Configure, Monitor and Deploy and the groups expand and collapse', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    for (const label of ['Configure', 'Monitor', 'Deploy']) expect(within(nav).getByRole('button', { name: label })).toBeTruthy()
    const configure = within(nav).getByRole('button', { name: 'Configure' })
    expect(configure.getAttribute('aria-expanded')).toBe('true')
    expect(within(nav).getByRole('link', { name: /^Tools/ })).toBeTruthy()
    await user.click(configure)
    expect(configure.getAttribute('aria-expanded')).toBe('false')
    expect(within(nav).queryByRole('link', { name: /^Tools/ })).toBeNull()
    await user.click(configure)
    expect(within(nav).getByRole('link', { name: /^Tools/ })).toBeTruthy()
  })

  it('labels sections that have no backend yet and leaves working ones unlabelled', async () => {
    renderApp('/dashboard')
    const sidebar = within(await screen.findByRole('navigation', { name: 'Main' }))
    for (const label of ['Knowledge Base', 'Tools', 'Workflows', 'Integrations', 'Conversations', 'Users', 'Tests', 'Analytics', 'Phone Numbers']) {
      const link = sidebar.getByRole('link', { name: new RegExp(`^${label}`) })
      expect(link.getAttribute('aria-label')).toBe(`${label} (coming soon)`)
      expect(link.textContent).toMatch(/Soon/)
    }
    for (const label of ['Home', 'Agents', 'Playground', 'Voices']) expect(sidebar.getByRole('link', { name: new RegExp(`^${label}`) }).textContent).not.toMatch(/Soon/)
  })

  it('a collapsed sidebar keeps accessible names and shows tooltips', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: 'Collapse sidebar' }))
    const agents = screen.getByRole('link', { name: 'Agents' })
    expect(agents).toBeTruthy()
    expect(within(agents.closest('.tooltip-host')).getByRole('tooltip').textContent).toBe('Agents')
  })

  it('has Settings, Help and a profile link at the bottom of the sidebar', async () => {
    renderApp('/dashboard')
    const secondary = await screen.findByRole('navigation', { name: 'Secondary' })
    expect(within(secondary).getByRole('link', { name: 'Settings' }).getAttribute('href')).toBe('/settings')
    expect(within(secondary).getByRole('link', { name: 'Help' }).getAttribute('href')).toBe('/help')
    expect(screen.getByRole('link', { name: /Your profile: ada@example.com/ }).getAttribute('href')).toBe('/settings/profile')
  })

  it('breadcrumbs use the agent name; the configure route lands in the studio', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1/configure')
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    await waitFor(() => expect(within(crumbs).getByText('Alpha').getAttribute('aria-current')).toBe('page'))
    expect(await screen.findByRole('tablist', { name: 'Agent studio' })).toBeTruthy()
    await user.click(within(crumbs).getByRole('link', { name: 'Agents' }))
    expect(await screen.findByRole('heading', { name: 'Your agents' })).toBeTruthy()
  })

  it('the studio talk route has its own breadcrumb trail back to the agent', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1/talk')
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    await waitFor(() => expect(within(crumbs).getByRole('link', { name: 'Alpha' })).toBeTruthy())
    expect(within(crumbs).getByText('Voice test').getAttribute('aria-current')).toBe('page')
    await user.click(within(crumbs).getByRole('link', { name: 'Alpha' }))
    expect(await screen.findByRole('tablist', { name: 'Agent studio' })).toBeTruthy()
  })

  it('/settings opens the profile page', async () => {
    renderApp('/settings')
    expect(await h1('Profile')).toBeTruthy()
  })

  it('the mobile drawer opens from the header and closes with Escape or after choosing a page', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: 'Open navigation' }))
    const sidebar = document.getElementById('app-sidebar')
    expect(sidebar.className).toContain('is-open')
    await user.keyboard('{Escape}')
    expect(sidebar.className).not.toContain('is-open')
    await user.click(screen.getByRole('button', { name: 'Open navigation' }))
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Agents/ }))
    expect(sidebar.className).not.toContain('is-open')
  })

  it('the sidebar can be collapsed and expanded', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    await user.click(await screen.findByRole('button', { name: 'Collapse sidebar' }))
    expect(document.getElementById('app-sidebar').className).toContain('is-collapsed')
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(document.getElementById('app-sidebar').className).not.toContain('is-collapsed')
  })
})
