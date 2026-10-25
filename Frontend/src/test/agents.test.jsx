import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/index.js'
import { AGENTS, renderApp, resetApi } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

const cards = () => screen.queryAllByRole('article').map((card) => card.getAttribute('aria-label'))

describe('agents list', () => {
  it('shows skeletons first, then the real agents with their details', async () => {
    renderApp('/agents')
    expect(await screen.findByLabelText('Loading agents')).toBeTruthy()
    await screen.findByRole('link', { name: 'Alpha' })
    expect(cards()).toEqual(['Alpha', 'Beta', 'Gamma'])
    expect(api.agents.list).toHaveBeenCalledWith({ limit: 50, offset: 0 }, expect.anything())
    expect(screen.getByText('Books appointments')).toBeTruthy()
    expect(within(screen.getByRole('article', { name: 'Beta' })).getByText('Inactive')).toBeTruthy()
  })

  it('every card action points at the right route', async () => {
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    expect(screen.getByRole('link', { name: 'Alpha' }).getAttribute('href')).toBe('/agents/a1')
    expect(screen.getByRole('link', { name: 'Open Alpha' }).getAttribute('href')).toBe('/agents/a1')
    expect(screen.getByRole('link', { name: 'Configure Alpha' }).getAttribute('href')).toBe('/agents/a1/configure')
    expect(screen.getByRole('link', { name: 'Test Alpha' }).getAttribute('href')).toBe('/agents/a1/talk')
    expect(screen.getAllByRole('link', { name: 'Create agent' })[0].getAttribute('href')).toBe('/agents/new')
  })

  it('search really filters the list by name and can be cleared', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    await user.type(screen.getByRole('searchbox', { name: 'Search agents by name' }), 'gam')
    expect(cards()).toEqual(['Gamma'])
    expect(screen.getByText('Showing 1 of 3 loaded agents.')).toBeTruthy()
    await user.clear(screen.getByRole('searchbox', { name: 'Search agents by name' }))
    expect(cards()).toHaveLength(3)
    await user.type(screen.getByRole('searchbox', { name: 'Search agents by name' }), 'nothing-like-this')
    expect(screen.getByText('No agents match your filters')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(cards()).toHaveLength(3)
  })

  it('keeps every typed character and mirrors the search in the URL', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    const box = screen.getByRole('searchbox', { name: 'Search agents by name' })
    await user.type(box, 'gamma')
    expect(box.value).toBe('gamma')
    expect(router.state.location.search).toBe('?q=gamma')
  })

  it('the status filter changes the list', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by status' }), 'inactive')
    expect(cards()).toEqual(['Beta'])
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter by status' }), 'active')
    expect(cards()).toEqual(['Alpha', 'Gamma'])
  })

  it('the dashboard link to active agents opens the list already filtered', async () => {
    renderApp('/agents?status=active')
    await screen.findByRole('link', { name: 'Alpha' })
    expect(cards()).toEqual(['Alpha', 'Gamma'])
  })

  it('switches between card and list layouts', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    await user.click(screen.getByRole('button', { name: 'List layout' }))
    expect(cards()).toEqual([])
    const list = screen.getByRole('list', { name: 'Agents' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getByRole('button', { name: 'List layout' }).getAttribute('aria-pressed')).toBe('true')
    await user.click(screen.getByRole('button', { name: 'Card layout' }))
    expect(cards()).toHaveLength(3)
  })

  it('shows an empty state with a way to create the first agent', async () => {
    vi.mocked(api.agents.list).mockResolvedValue([])
    renderApp('/agents')
    expect(await screen.findByText('Create your first agent')).toBeTruthy()
    expect(screen.queryByRole('searchbox')).toBeNull()
  })

  it('shows the error and retries on request', async () => {
    vi.mocked(api.agents.list).mockRejectedValueOnce(new ApiError({ status: 500, code: 'internal_error', message: 'Internal server error', requestId: 'r9' }))
    const user = userEvent.setup()
    renderApp('/agents')
    expect(await screen.findByText('We couldn’t load your agents')).toBeTruthy()
    expect(screen.getByText('Internal server error')).toBeTruthy()
    expect(screen.getByText('Request ID: r9')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('link', { name: 'Alpha' })).toBeTruthy()
  })

  it('loads the next page when the first one is full', async () => {
    const page = Array.from({ length: 50 }, (_, index) => ({ ...AGENTS[0], id: `p${index}`, name: `Agent ${index}` }))
    vi.mocked(api.agents.list).mockResolvedValueOnce(page).mockResolvedValueOnce([{ ...AGENTS[0], id: 'last', name: 'Last one' }])
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Agent 0' })
    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('link', { name: 'Last one' })).toBeTruthy()
    expect(api.agents.list).toHaveBeenLastCalledWith({ limit: 50, offset: 50 })
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })
})

describe('more-actions menu', () => {
  it('shows the voice saved on each agent', async () => {
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    expect(within(screen.getByRole('article', { name: 'Alpha' })).getByText('Default voice · speed 1')).toBeTruthy()
  })

  it('opens with the keyboard, moves with the arrows and closes with Escape', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    const trigger = screen.getByRole('button', { name: 'More actions for Alpha' })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    trigger.focus()
    await user.keyboard('{Enter}')
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    const items = screen.getAllByRole('menuitem')
    expect(items.map((item) => item.textContent)).toEqual(['Open agent', 'Copy agent ID', 'Delete agent'])
    expect(document.activeElement).toBe(items[0])
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(items[1])
    await user.keyboard('{End}')
    expect(document.activeElement).toBe(items[2])
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('Open agent links to the studio and Copy agent ID uses the clipboard', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    await screen.findByRole('link', { name: 'Alpha' })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await user.click(screen.getByRole('button', { name: 'More actions for Alpha' }))
    expect(screen.getByRole('menuitem', { name: 'Open agent' }).getAttribute('href')).toBe('/agents/a1')
    await user.click(screen.getByRole('menuitem', { name: 'Copy agent ID' }))
    expect(writeText).toHaveBeenCalledWith('a1')
    expect(await screen.findByText('Agent ID copied.')).toBeTruthy()
  })
})

describe('deleting from the list', () => {
  async function openDialog(user, name = 'Alpha') {
    await screen.findByRole('link', { name })
    await user.click(screen.getByRole('button', { name: `More actions for ${name}` }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete agent' }))
    return screen.findByRole('dialog', { name: `Delete “${name}”?` })
  }

  it('asks for confirmation naming the agent, and cancelling changes nothing', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    const dialog = await openDialog(user)
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.agents.remove).not.toHaveBeenCalled()
    expect(cards()).toHaveLength(3)
  })

  it('Escape closes the dialog without deleting', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    const dialog = await openDialog(user)
    fireEvent(dialog, new Event('cancel', { cancelable: true })) // what the browser fires for Escape
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(api.agents.remove).not.toHaveBeenCalled()
  })

  it('removes the agent only after the server confirms', async () => {
    const user = userEvent.setup()
    renderApp('/agents')
    const dialog = await openDialog(user)
    await user.click(within(dialog).getByRole('button', { name: 'Delete agent' }))
    await waitFor(() => expect(cards()).toEqual(['Beta', 'Gamma']))
    expect(api.agents.remove).toHaveBeenCalledWith('a1')
    expect(await screen.findByText('Deleted “Alpha”.')).toBeTruthy()
  })

  it('keeps the agent and reports the problem when deletion fails', async () => {
    vi.mocked(api.agents.remove).mockRejectedValue(new ApiError({ status: 500, code: 'internal_error', message: 'Internal server error' }))
    const user = userEvent.setup()
    renderApp('/agents')
    const dialog = await openDialog(user)
    await user.click(within(dialog).getByRole('button', { name: 'Delete agent' }))
    expect(await within(dialog).findByText('Internal server error')).toBeTruthy()
    expect(cards()).toHaveLength(3)
  })
})
