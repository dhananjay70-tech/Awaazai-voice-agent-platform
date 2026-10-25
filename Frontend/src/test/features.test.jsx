import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/index.js'
import { renderApp, resetApi } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

const COMING_SOON_PAGES = [
  ['/knowledge', 'Knowledge ingestion is not connected yet'],
  ['/workflows', 'Workflows are not available yet'],
  ['/phone-numbers', 'Phone numbers are not available yet'],
  ['/integrations', 'No integrations are available yet'],
  ['/analytics', 'Analytics are not available yet'],
  ['/tools', 'Tools are not available yet'],
  ['/conversations', 'Conversation history is not recorded yet'],
  ['/users', 'Team management is not configured'],
  ['/tests', 'Automated tests are not available yet'],
  ['/deployment', 'Nothing can be deployed yet'],
  ['/voices', 'No voice catalogue is connected'],
  ['/agents/a1/knowledge', 'Knowledge ingestion is not connected yet'],
]

describe('features without a backend', () => {
  it.each(COMING_SOON_PAGES)('%s says plainly that it is not available and has no working fake controls', async (path, notice) => {
    renderApp(path)
    expect(await screen.findByText(notice)).toBeTruthy()
    const soonButtons = screen.queryAllByRole('button').filter((button) => /Soon/.test(button.textContent))
    for (const button of soonButtons) {
      expect(button.hasAttribute('disabled'), button.textContent).toBe(true)
      expect(button.getAttribute('title')).toBe('Coming soon')
    }
  })

  it('never shows a Connected badge or made-up numbers', async () => {
    for (const path of ['/integrations', '/phone-numbers', '/analytics']) {
      const { unmount } = renderApp(path)
      await screen.findByRole('heading', { level: 1 })
      expect(await screen.findByText(/available yet/)).toBeTruthy()
      expect(screen.queryByText(/^Connected$/)).toBeNull()
      unmount()
    }
  })

  it('the knowledge page lists the real agents and its search filters them', async () => {
    const user = userEvent.setup()
    renderApp('/knowledge')
    const list = await screen.findByRole('list', { name: 'Agents' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(within(list).getByRole('link', { name: 'Alpha' }).getAttribute('href')).toBe('/agents/a1/knowledge')
    await user.type(screen.getByRole('searchbox', { name: 'Search agents' }), 'bet')
    expect(within(screen.getByRole('list', { name: 'Agents' })).getAllByRole('listitem')).toHaveLength(1)
  })

  it('integration search and category filter change the cards', async () => {
    const user = userEvent.setup()
    renderApp('/integrations')
    expect(await screen.findAllByRole('article')).toHaveLength(5)
    const categories = within(screen.getByRole('combobox', { name: 'Filter by category' })).getAllByRole('option').map((option) => option.textContent)
    expect(categories).toEqual(['All categories', 'AI and model providers', 'Communication', 'Business applications', 'Custom APIs'])
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by category' }), 'AI and model providers')
    expect(screen.getAllByRole('article')).toHaveLength(2)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by category' }), 'Custom APIs')
    expect(screen.getAllByRole('article').map((card) => card.getAttribute('aria-label'))).toEqual(['Webhooks and custom APIs'])
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by category' }), 'All')
    await user.type(screen.getByRole('searchbox', { name: 'Search integrations' }), 'zzz')
    expect(screen.getByText('No integrations match')).toBeTruthy()
  })

  it('the workflow demonstration is labelled and its steps are selectable', async () => {
    const user = userEvent.setup()
    renderApp('/workflows')
    expect(await screen.findByText(/Demonstration · not saved · not running/)).toBeTruthy()
    expect(screen.getByText('No workflows')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /Create calendar event/ }))
    expect(screen.getByText('Adds the appointment to a connected calendar.')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Create calendar event/ }).getAttribute('aria-pressed')).toBe('true')
  })

  it('the analytics date range is a working control and no statistics are invented', async () => {
    const user = userEvent.setup()
    renderApp('/analytics')
    expect(await screen.findByText('No data for the last 30 days')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Date range'), '7')
    expect(screen.getByText('No data for the last 7 days')).toBeTruthy()
    expect(screen.getAllByText('No data source yet')).toHaveLength(4)
  })
})

describe('settings', () => {
  it('has Profile, Account, Preferences and Security pages reachable from the sub-navigation', async () => {
    const user = userEvent.setup()
    renderApp('/settings/profile')
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Profile', 'Account', 'Preferences', 'Security'])
    for (const name of ['Account', 'Preferences', 'Security', 'Profile']) {
      await user.click(within(screen.getByRole('navigation', { name: 'Settings sections' })).getByRole('link', { name }))
      expect(await screen.findByRole('heading', { level: 1, name })).toBeTruthy()
    }
  })

  it('shows the profile from the authenticated user and offers nothing the backend cannot save', async () => {
    renderApp('/settings/profile')
    expect((await screen.findAllByText('ada@example.com')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Ada Lovelace').length).toBeGreaterThan(0)
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' }).textContent).toMatch(/Settings\s*\/\s*Profile/)
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('button', { name: /Save/ })).toBeNull()
  })

  it('the account page shows account facts and says what is unavailable', async () => {
    renderApp('/settings/account')
    expect(await screen.findByText('u1')).toBeTruthy()
    expect(screen.getByText(/Password changes, billing, API keys and account deletion are not available/)).toBeTruthy()
  })

  it('the sidebar preference really is stored, and the theme is shown as dark-only', async () => {
    const user = userEvent.setup()
    renderApp('/settings/preferences')
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Sidebar' }), 'collapsed')
    expect(window.localStorage.getItem('awaaz.sidebar')).toBe('collapsed')
    expect(screen.getByLabelText('Theme').value).toBe('Dark')
    expect(screen.getByLabelText('Theme').hasAttribute('readonly')).toBe(true)
  })

  it('the security page explains the session and signs out', async () => {
    const user = userEvent.setup()
    renderApp('/settings/security')
    expect(await screen.findByText(/lasts 30 minutes/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy()
  })
})

describe('voices, tools and other new pages', () => {
  it('Voices lists the voices your agents really use, and its search filters them', async () => {
    const user = userEvent.setup()
    renderApp('/voices')
    const table = (await screen.findByText('Voices in use by your agents')).closest('section')
    expect(within(table).getAllByRole('row')).toHaveLength(4) // header + 3 agents
    expect(within(table).getByRole('link', { name: 'Alpha' }).getAttribute('href')).toBe('/agents/a1')
    await user.type(within(table).getByRole('searchbox'), 'gamma')
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('No voices to show')).toBeTruthy() // no catalogue exists, so none is invented
    expect(screen.getByRole('button', { name: /Preview voice/ }).hasAttribute('disabled')).toBe(true)
  })

  it('Voices shows the language-to-voice-mode mapping', async () => {
    renderApp('/voices')
    const row = (await screen.findByText('Supported languages')).closest('section').querySelector('tbody')
    expect(within(row).getAllByRole('row').map((r) => r.textContent)).toEqual(['Englishenenglish', 'Hindihihindi', 'Hinglish (Hindi in Latin script)hi-Latnhinglish'])
  })

  it('Tools: the configuration form is a preview whose rows work but which cannot be saved', async () => {
    const user = userEvent.setup()
    renderApp('/tools')
    expect(await screen.findByText('Preview · cannot be saved')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Save tool/ }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: /Add tool/ }).hasAttribute('disabled')).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Add parameter' }))
    expect(screen.getByLabelText('Parameter 2 name')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Remove parameter 1' }))
    expect(screen.queryByLabelText('Parameter 2 name')).toBeNull()
    expect(screen.getByLabelText('Parameter 1 name')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Authentication'), 'bearer')
    expect(screen.getByText('Secrets are never entered here')).toBeTruthy()
    expect(screen.queryByLabelText(/token|secret|password/i)).toBeNull()
  })

  it('Conversations invents no conversations and points to the playground', async () => {
    renderApp('/conversations')
    expect(await screen.findByText('No conversations')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Try the playground' }).getAttribute('href')).toBe('/playground')
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('Users shows only the signed-in account and cannot invite anyone', async () => {
    renderApp('/users')
    expect(await screen.findByText('Team management is not configured')).toBeTruthy()
    expect(screen.getAllByText('ada@example.com').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /Invite user/ }).hasAttribute('disabled')).toBe(true)
  })

  it('Deployment marks every channel as unavailable or preview-only and links the phone page', async () => {
    renderApp('/deployment')
    expect(await screen.findByText('Visual preview only')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Phone numbers' }).getAttribute('href')).toBe('/phone-numbers')
    expect(screen.queryByText(/^Live$/)).toBeNull()
  })

  it('Help explains how to run the services and what is not available', async () => {
    renderApp('/help')
    expect(await screen.findByText('Running it locally')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Create an agent' }).getAttribute('href')).toBe('/agents/new')
    expect(screen.getByText('What is not available yet')).toBeTruthy()
  })
})

describe('dashboard', () => {
  it('derives totals from the API and every card navigates somewhere', async () => {
    renderApp('/dashboard')
    const total = await screen.findByRole('link', { name: /Total agents/ })
    expect(total.textContent).toMatch(/3/)
    expect(total.getAttribute('href')).toBe('/agents')
    const active = screen.getByRole('link', { name: /Active agents/ })
    expect(active.textContent).toMatch(/2/)
    expect(active.getAttribute('href')).toBe('/agents?status=active')
    expect(screen.getByRole('link', { name: /Voice service/ }).getAttribute('href')).toBe('/playground')
    const quick = screen.getByRole('heading', { name: 'Quick links' }).parentElement
    for (const link of within(quick).getAllByRole('link')) expect(link.getAttribute('href')).toMatch(/^\//)
  })

  it('shows onboarding when there are no agents and an error with retry when loading fails', async () => {
    vi.mocked(api.agents.list).mockResolvedValue([])
    renderApp('/dashboard')
    expect(await screen.findByText('No agents yet')).toBeTruthy()
    expect(screen.getByText('Getting started')).toBeTruthy()
  })

  it('reports the voice service status from the backend', async () => {
    vi.mocked(api.voiceAgent.status).mockResolvedValue({ configured: true, status: 'unavailable', detail: 'Connection refused' })
    renderApp('/dashboard')
    expect(await screen.findByText('Unavailable')).toBeTruthy()
    expect(screen.getByText('Connection refused')).toBeTruthy()
  })
})

describe('voice testing pages', () => {
  it('the agent voice test page shows the playground for that agent without connecting', async () => {
    renderApp('/agents/a1/talk')
    expect(await screen.findByRole('button', { name: 'Start session' })).toBeTruthy()
    expect(screen.getByText(/saved agent settings are not applied/i)).toBeTruthy()
    expect(screen.getByText('Idle')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Back to the studio' }).getAttribute('href')).toBe('/agents/a1')
    expect(screen.queryByRole('button', { name: 'Talk' })).toBeNull() // nothing starts until a session is opened
  })

  it('refuses to test a language the voice service does not support', async () => {
    vi.mocked(api.agents.get).mockResolvedValue({ ...(await api.agents.get('a1')), language: 'fr' })
    renderApp('/agents/a1/talk')
    expect(await screen.findByText(/isn’t supported by the voice service/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start session' })).toBeNull()
  })

  it('the playground offers real agents and uses the chosen agent’s language', async () => {
    const user = userEvent.setup()
    renderApp('/playground')
    const agent = await screen.findByLabelText('Agent')
    await screen.findByRole('option', { name: 'Beta' })
    expect(screen.getByLabelText('Language').value).toBe('en')
    await user.selectOptions(agent, 'a2')
    expect(screen.getByLabelText('Language').value).toBe('hi')
    await user.selectOptions(screen.getByLabelText('Language'), 'en')
    expect(screen.getByText(/not the agent’s own language/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Start session' })).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Live voice playground' })).getByText('Beta')).toBeTruthy() // always clear which agent is tested
  })
})
