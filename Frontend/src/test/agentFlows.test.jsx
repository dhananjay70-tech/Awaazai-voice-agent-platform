import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/index.js'
import { AGENT_TEMPLATES } from '../utils/agentTemplates.js'
import { changeElsewhere, makeAgent, renderApp, resetApi, server } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

const tabs = () => screen.findByRole('tablist', { name: 'Agent studio' })
// A region can share a control's name (the panel and its textarea are both "System prompt"), so pick the control itself.
const field = async (label) => (await screen.findAllByLabelText(label)).find((el) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
const prompt = () => screen.getByRole('textbox', { name: 'System prompt' })

describe('create agent', () => {
  it('offers Blank plus the four starter templates', async () => {
    renderApp('/agents/new')
    const group = await screen.findByRole('group', { name: 'Starter template' })
    expect(within(group).getAllByRole('radio').map((radio) => radio.closest('label').textContent)).toEqual([
      expect.stringContaining('Blank'),
      ...AGENT_TEMPLATES.map((template) => expect.stringContaining(template.label)),
    ])
  })

  it('a template fills the real form fields, which stay editable; Blank empties them again', async () => {
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.click(await screen.findByRole('radio', { name: /Appointment Booking Agent/ }))
    const booking = AGENT_TEMPLATES.find((template) => template.id === 'booking')
    expect((await field('Agent name')).value).toBe(booking.name)
    expect(screen.getByLabelText(/Description/).value).toBe(booking.description)
    expect(prompt().value).toBe(booking.systemPrompt)
    await user.type(screen.getByLabelText('Agent name'), ' 2')
    expect(screen.getByLabelText('Agent name').value).toBe(`${booking.name} 2`)
    await user.click(screen.getByRole('radio', { name: /Sales Assistant/ }))
    expect(screen.getByLabelText('Agent name').value).toBe('Sales assistant')
    await user.click(screen.getByRole('radio', { name: /Blank/ }))
    expect(screen.getByLabelText('Agent name').value).toBe('')
    expect(prompt().value).toBe('')
  })

  it('validates before sending anything', async () => {
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.click(await screen.findByRole('button', { name: 'Create agent' }))
    expect(screen.getByText('Give your agent a name.')).toBeTruthy()
    expect(screen.getByText('Write instructions for the agent.')).toBeTruthy()
    expect(api.agents.create).not.toHaveBeenCalled()
  })

  it('counts prompt characters', async () => {
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.click(prompt())
    await user.paste('abc')
    expect(screen.getByText('3 / 10,000 characters')).toBeTruthy()
  })

  it('creates the agent through the API, opens its studio and keeps the template greeting as a local draft', async () => {
    const support = AGENT_TEMPLATES[0]
    const created = makeAgent({ id: 'new-1', name: support.name, system_prompt: support.systemPrompt })
    vi.mocked(api.agents.create).mockResolvedValue(created)
    vi.mocked(api.agents.get).mockResolvedValue(created)
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.click(await screen.findByRole('radio', { name: /Customer Support Agent/ }))
    await user.click(screen.getByRole('button', { name: 'Create agent' }))

    expect(await screen.findByRole('heading', { level: 2, name: support.name })).toBeTruthy()
    expect(api.agents.create).toHaveBeenCalledWith({
      name: support.name,
      description: support.description,
      system_prompt: support.systemPrompt,
      language: 'en',
      voice_config: { provider: null, voice_id: null, speed: 1 },
      is_active: true,
    })
    expect(await screen.findByText(`Created “${support.name}”.`)).toBeTruthy()
    expect(window.localStorage.getItem('awaaz.firstMessageDraft.new-1')).toBe(support.firstMessage)
    expect((await screen.findByLabelText('Greeting')).value).toBe(support.firstMessage)
  })

  it('does not claim success when the API fails and keeps what was typed', async () => {
    vi.mocked(api.agents.create).mockRejectedValue(new ApiError({ status: 409, code: 'agent_name_conflict', message: 'You already have an agent with this name' }))
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.type(await field('Agent name'), 'Alpha')
    await user.type(prompt(), 'Be helpful.')
    await user.click(screen.getByRole('button', { name: 'Create agent' }))
    expect(await screen.findByText('Could not create the agent')).toBeTruthy()
    expect(screen.getAllByText('You already have an agent with this name').length).toBeGreaterThan(0)
    expect(screen.queryByText(/Created “/)).toBeNull()
    expect(screen.getByLabelText('Agent name').value).toBe('Alpha')
  })

  it('sends one request even if the button is pressed repeatedly', async () => {
    let finish
    vi.mocked(api.agents.create).mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.type(await field('Agent name'), 'Solo')
    await user.type(prompt(), 'x')
    await user.click(screen.getByRole('button', { name: 'Create agent' }))
    const busy = await screen.findByRole('button', { name: /Creating/ })
    await user.click(busy)
    await user.keyboard('{Enter}')
    expect(api.agents.create).toHaveBeenCalledTimes(1)
    finish(makeAgent({ id: 'solo', name: 'Solo' }))
  })

  it('asks before discarding a half-filled form and Cancel returns to the list', async () => {
    const user = userEvent.setup()
    renderApp('/agents/new')
    await user.type(await field('Agent name'), 'Draft')
    await user.click(screen.getByRole('link', { name: 'Cancel' }))
    const dialog = await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.getByLabelText('Agent name').value).toBe('Draft')
    await user.click(screen.getByRole('link', { name: 'Cancel' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Discard changes' }))
    expect(await screen.findByRole('heading', { name: 'Your agents' })).toBeTruthy()
  })
})

describe('agent studio layout', () => {
  it('has the nine tabs, the Agent tab by default and a test panel beside the editor', async () => {
    renderApp('/agents/a1')
    const list = await tabs()
    expect(within(list).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Agent',
      'Workflow',
      'Knowledge Base',
      'Analysis',
      'Tools',
      'Tests',
      'Widget',
      'Security',
      'Advanced',
    ])
    expect(within(list).getByRole('tab', { name: 'Agent' }).getAttribute('aria-selected')).toBe('true')
    for (const heading of ['Agent details', 'System prompt', 'First message', 'Voice and language']) {
      expect(screen.getByRole('heading', { name: heading })).toBeTruthy()
    }
    const panel = screen.getByRole('complementary', { name: 'Test agent' })
    expect(within(panel).getByRole('button', { name: 'Start session' })).toBeTruthy()
  })

  it('shows the agent name, status and save state in the studio bar', async () => {
    renderApp('/agents/a1')
    expect(await screen.findByRole('heading', { level: 2, name: 'Alpha' })).toBeTruthy()
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0)
    expect(screen.getByText('Saved')).toBeTruthy()
    expect(screen.queryByText('All changes saved')).toBeNull() // nothing has been saved in this session yet
    expect(screen.queryByRole('button', { name: /Publish/ })).toBeNull() // there is no publishing mechanism
  })

  it.each([
    ['Workflow', 'Workflows are not available yet'],
    ['Knowledge Base', 'Knowledge ingestion is not connected yet'],
    ['Analysis', 'Analysis is not available yet'],
    ['Tools', 'Tools are not available yet'],
    ['Tests', 'Automated tests are not available yet'],
    ['Widget', 'Visual preview only'],
    ['Security', 'Voice session authentication'],
    ['Advanced', 'Language behaviour'],
  ])('the %s tab has its own honest content', async (tabName, text) => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.click(within(await tabs()).getByRole('tab', { name: tabName }))
    expect(await screen.findByText(text)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'System prompt' })).toBeNull()
  })

  it('tabs can be deep-linked, and the old knowledge route opens the Knowledge tab', async () => {
    const { unmount } = renderApp('/agents/a1?tab=security')
    expect((await screen.findByRole('tab', { name: 'Security' })).getAttribute('aria-selected')).toBe('true')
    unmount()
    renderApp('/agents/a1/knowledge')
    expect((await screen.findByRole('tab', { name: 'Knowledge Base' })).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByText('Knowledge ingestion is not connected yet')).toBeTruthy()
  })

  it('arrow keys, Home and End move between tabs', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const list = await tabs()
    within(list).getByRole('tab', { name: 'Agent' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(within(list).getByRole('tab', { name: 'Workflow' }).getAttribute('aria-selected')).toBe('true')
    await user.keyboard('{End}')
    expect(within(list).getByRole('tab', { name: 'Advanced' }).getAttribute('aria-selected')).toBe('true')
    await user.keyboard('{ArrowRight}')
    expect(within(list).getByRole('tab', { name: 'Agent' }).getAttribute('aria-selected')).toBe('true')
  })

  it('the Widget tab is clearly a preview: its controls change the preview, and there is no embed code', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1?tab=widget')
    await screen.findByText('Visual preview only')
    await user.selectOptions(screen.getByLabelText('Position'), 'bottom-left')
    expect(document.querySelector('.widget-bubble').className).toContain('bottom-left')
    expect(screen.getByRole('button', { name: 'Copy embed code' }).hasAttribute('disabled')).toBe(true)
    expect(api.agents.update).not.toHaveBeenCalled()
  })

  it('the Advanced tab shows the language mapping the voice service needs', async () => {
    renderApp('/agents/a1?tab=advanced')
    const row = (await screen.findByText('hi-Latn')).closest('tr')
    expect(row.textContent).toContain('hinglish')
  })

  it('shows a not-found state for an agent that does not exist', async () => {
    vi.mocked(api.agents.get).mockRejectedValue(new ApiError({ status: 404, code: 'not_found', message: 'Agent not found' }))
    renderApp('/agents/missing')
    expect((await screen.findAllByText('Agent not found')).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Back to agents' }).getAttribute('href')).toBe('/agents')
  })
})

describe('agent studio editing', () => {
  it('tracks unsaved changes and saves only what changed, then shows the server’s version', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const save = await screen.findByRole('button', { name: 'Save changes' })
    expect(save.hasAttribute('disabled')).toBe(true)
    await user.type(await field('Agent name'), ' 2')
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    await user.click(save)
    await waitFor(() => expect(api.agents.update).toHaveBeenCalledWith('a1', { name: 'Alpha 2' }))
    expect(await screen.findByText('Changes saved.')).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'Alpha 2' })).toBeTruthy()
    expect(screen.getByText('All changes saved')).toBeTruthy()
    expect(screen.getByText('Saved')).toBeTruthy()
    expect(server.agents.get('a1').name).toBe('Alpha 2') // the stand-in server really holds it
    expect(api.agents.update).toHaveBeenCalledTimes(1) // not once per keystroke
  })

  it('saves a changed system prompt, language and voice settings together', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const prompt = await field('System prompt')
    await user.clear(prompt)
    await user.type(prompt, 'New prompt')
    await user.selectOptions(screen.getByLabelText('Language'), 'hi')
    await user.type(screen.getByLabelText('Voice provider (optional)'), 'p')
    await user.type(screen.getByLabelText('Voice ID (optional)'), 'v')
    const speed = screen.getByLabelText('Speaking speed value')
    await user.clear(speed)
    await user.type(speed, '1.4')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() =>
      expect(api.agents.update).toHaveBeenCalledWith('a1', {
        system_prompt: 'New prompt',
        language: 'hi',
        voice_config: { provider: 'p', voice_id: 'v', speed: 1.4 },
      }),
    )
  })

  it('shows the language tag next to the voice mode the voice service will use', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await screen.findByLabelText('Language')
    expect(screen.getByText('english')).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Language'), 'hi-Latn')
    expect(screen.getByText('hinglish')).toBeTruthy()
  })

  it('refuses a speed outside 0.5 to 2.0 and keeps the preview button disabled with an explanation', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const speed = await screen.findByLabelText('Speaking speed value')
    await user.clear(speed)
    await user.type(speed, '3')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Speed must be between 0.5 and 2.')).toBeTruthy()
    expect(api.agents.update).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Preview voice' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText(/no preview service that returns playable audio/)).toBeTruthy()
  })

  it('validation errors are shown beside the field and block the request', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.clear(await field('System prompt'))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Write instructions for the agent.')).toBeTruthy()
    expect(prompt().getAttribute('aria-invalid')).toBe('true')
    expect(api.agents.update).not.toHaveBeenCalled()
  })

  it('shows API errors and keeps the edits', async () => {
    vi.mocked(api.agents.update).mockRejectedValue(new ApiError({ status: 409, code: 'agent_name_conflict', message: 'You already have an agent with this name' }))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.type(await field('Agent name'), 'x')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Could not save your changes')).toBeTruthy()
    expect(screen.getByLabelText('Agent name').value).toBe('Alphax')
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    expect(screen.queryByText('Changes saved.')).toBeNull()
  })

  it('warns before leaving with unsaved changes, and not when nothing changed', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.type(await field('Agent name'), 'x')
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Playground/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.getByLabelText('Agent name').value).toBe('Alphax')
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Playground/ }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Discard changes' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Playground' })).toBeTruthy()
  })

  it('edits survive switching tabs', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.type(await field('Agent name'), 'x')
    await user.click(within(await tabs()).getByRole('tab', { name: 'Security' }))
    await user.click(within(await tabs()).getByRole('tab', { name: 'Agent' }))
    expect((await field('Agent name')).value).toBe('Alphax')
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
  })

  it('does not warn when nothing changed', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await field('Agent name')
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Playground/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Playground' })).toBeTruthy()
  })
})

describe('system prompt editor', () => {
  it('Clear and Reset ask before discarding, and Reset restores the saved prompt', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const prompt = await field('System prompt')
    expect(screen.getByRole('button', { name: 'Reset' }).hasAttribute('disabled')).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    const dialog = await screen.findByRole('dialog', { name: 'Clear the system prompt?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(prompt.value).toBe('You are a friendly receptionist.')
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Clear' }))
    expect(prompt.value).toBe('')
    await user.click(screen.getByRole('button', { name: 'Reset' })) // nothing typed, so no confirmation is needed
    expect(prompt.value).toBe('You are a friendly receptionist.')
  })

  it('inserting a template replaces the prompt only after confirmation', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const prompt = await field('System prompt')
    await user.click(screen.getByRole('button', { name: 'Insert a prompt template' }))
    await user.click(screen.getByRole('menuitem', { name: 'Sales Assistant' }))
    const dialog = await screen.findByRole('dialog', { name: 'Replace the prompt with this template?' })
    await user.click(within(dialog).getByRole('button', { name: 'Replace' }))
    expect(prompt.value).toBe(AGENT_TEMPLATES.find((template) => template.id === 'sales').systemPrompt)
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
  })

  it('shows writing guidance and a live character counter', async () => {
    renderApp('/agents/a1')
    await field('System prompt')
    expect(screen.getByText('Prompt-writing guidance')).toBeTruthy()
    expect(screen.getByText('32 / 10,000 characters')).toBeTruthy()
  })
})

describe('first message', () => {
  it('is an honest local draft: stored in the browser, never sent to the API, never counted as an unsaved change', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    expect(await screen.findByText('Local draft: not saved to your agent')).toBeTruthy()
    await user.type(screen.getByLabelText('Greeting'), 'Hello there!')
    expect(window.localStorage.getItem('awaaz.firstMessageDraft.a1')).toBe('Hello there!')
    expect(screen.getByText('Draft kept in this browser.')).toBeTruthy()
    expect(screen.getByText('Saved')).toBeTruthy() // the agent itself is unchanged
    expect(api.agents.update).not.toHaveBeenCalled()
  })

  it('is restored from this browser when the studio is opened again', async () => {
    window.localStorage.setItem('awaaz.firstMessageDraft.a1', 'Welcome back')
    renderApp('/agents/a1')
    expect((await screen.findByLabelText('Greeting')).value).toBe('Welcome back')
  })
})

describe('studio actions', () => {
  it('the overflow menu links to the full-screen test and copies the agent ID', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await user.click(await screen.findByRole('button', { name: 'More actions' }))
    expect(screen.getByRole('menuitem', { name: 'Open full-screen test' }).getAttribute('href')).toBe('/agents/a1/talk')
    await user.click(screen.getByRole('menuitem', { name: 'Copy agent ID' }))
    expect(writeText).toHaveBeenCalledWith('a1')
  })

  it('deletes only after confirmation, then returns to the list', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.click(await screen.findByRole('button', { name: 'More actions' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete agent' }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete “Alpha”?' })
    expect(api.agents.remove).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Delete agent' }))
    expect(await screen.findByRole('heading', { name: 'Your agents' })).toBeTruthy()
    expect(api.agents.remove).toHaveBeenCalledWith('a1')
  })

  it('the test panel can be collapsed and expanded, and "Test agent" reopens it', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const panel = await screen.findByRole('complementary', { name: 'Test agent' })
    await user.click(within(panel).getByRole('button', { name: 'Collapse test panel' }))
    expect(within(panel).queryByRole('button', { name: 'Start session' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Test agent' }))
    expect(within(panel).getByRole('button', { name: 'Start session' })).toBeTruthy()
  })

  it('says so when the agent’s language cannot be voice-tested', async () => {
    vi.mocked(api.agents.get).mockResolvedValue(makeAgent({ language: 'fr' }))
    renderApp('/agents/a1')
    expect(await screen.findByText(/isn’t supported by the voice service/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start session' })).toBeNull()
  })
})

describe('saving is confirmed by the server', () => {
  async function edit(user, text = ' 2') {
    await user.type(await field('Agent name'), text)
  }

  it('sends every edited field in one PATCH and the server really stores them', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const prompt = await field('System prompt')
    await user.clear(prompt)
    await user.type(prompt, 'Edited prompt')
    await user.clear(await field('Agent name'))
    await user.type(await field('Agent name'), 'Edited')
    await user.clear(screen.getByLabelText(/Description/))
    await user.type(screen.getByLabelText(/Description/), 'Edited description')
    await user.selectOptions(screen.getByLabelText('Language'), 'hi-Latn')
    await user.type(screen.getByLabelText('Voice provider (optional)'), 'deepgram')
    await user.type(screen.getByLabelText('Voice ID (optional)'), 'aura')
    const speed = screen.getByLabelText('Speaking speed value')
    await user.clear(speed)
    await user.type(speed, '1.4')
    await user.click(screen.getByRole('switch'))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('All changes saved')

    expect(api.agents.update).toHaveBeenCalledTimes(1)
    expect(api.agents.update).toHaveBeenCalledWith('a1', {
      name: 'Edited',
      description: 'Edited description',
      system_prompt: 'Edited prompt',
      language: 'hi-Latn',
      is_active: false,
      voice_config: { provider: 'deepgram', voice_id: 'aura', speed: 1.4 },
    })
    expect(server.agents.get('a1')).toMatchObject({
      name: 'Edited',
      description: 'Edited description',
      system_prompt: 'Edited prompt',
      language: 'hi-Latn',
      is_active: false,
      voice_config: { provider: 'deepgram', voice_id: 'aura', speed: 1.4 },
    })
  })

  it('"All changes saved" only appears after the agent has been reloaded and compared', async () => {
    let finishReload
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    const reads = api.agents.get.getMockImplementation()
    api.agents.get.mockImplementationOnce(reads) // the stale-state check
    api.agents.get.mockImplementationOnce(() => new Promise((resolve) => (finishReload = () => resolve(reads('a1'))))) // the verification read
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Verifying…')).toBeTruthy()
    expect(api.agents.update).toHaveBeenCalledTimes(1) // the PATCH returned, yet nothing is called "saved" yet
    expect(screen.queryByText('All changes saved')).toBeNull()
    expect(screen.queryByText('Changes saved.')).toBeNull()
    const { act } = await import('@testing-library/react')
    await act(async () => finishReload())
    expect(await screen.findByText('All changes saved')).toBeTruthy()
    expect(await screen.findByText('Changes saved.')).toBeTruthy()
  })

  it('does not claim success when the server answers OK but did not store a field', async () => {
    server.ignore = ['language'] // the PATCH "succeeds" but the database keeps the old value
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.selectOptions(await screen.findByLabelText('Language'), 'hi')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('The server did not store everything you changed')).toBeTruthy()
    expect(screen.getByText(/still shows the old value for: language/)).toBeTruthy()
    expect(screen.queryByText('All changes saved')).toBeNull()
    expect(screen.queryByText('Changes saved.')).toBeNull()
    expect(screen.getByLabelText('Language').value).toBe('hi') // the user's edit is kept
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
  })

  it('a failed save shows the server’s message and never "All changes saved"', async () => {
    api.agents.update.mockRejectedValue(new ApiError({ status: 500, code: 'internal_error', message: 'Internal server error', requestId: 'r-42' }))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Could not save your changes')).toBeTruthy()
    expect(screen.getByText('Internal server error')).toBeTruthy()
    expect(screen.getByText('Request ID: r-42')).toBeTruthy()
    expect(screen.queryByText('All changes saved')).toBeNull()
    expect(screen.getByLabelText('Agent name').value).toBe('Alpha 2')
    expect(server.agents.get('a1').name).toBe('Alpha')
  })

  it('a network failure is shown, keeps the edits, and the save can simply be retried', async () => {
    api.agents.update.mockRejectedValueOnce(new ApiError({ status: 0, code: 'network_error', message: 'Could not reach the server. Check your connection and that the backend is running.' }))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/Could not reach the server/)).toBeTruthy()
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('All changes saved')).toBeTruthy()
    expect(server.agents.get('a1').name).toBe('Alpha 2')
  })

  it('shows server validation errors beside the field and keeps the edit', async () => {
    api.agents.update.mockRejectedValue(new ApiError({ status: 422, code: 'validation_error', message: 'Request validation failed', details: [{ field: 'language', message: 'String should match pattern' }] }))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.selectOptions(await screen.findByLabelText('Language'), 'hi')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('String should match pattern')).toBeTruthy()
    expect(screen.getByLabelText('Language').getAttribute('aria-invalid')).toBe('true')
    expect(screen.queryByText('All changes saved')).toBeNull()
  })

  it('an expired sign-in keeps the edits for this tab and offers them back afterwards', async () => {
    api.agents.update.mockRejectedValueOnce(new ApiError({ status: 401, code: 'invalid_token', message: 'Could not validate credentials' }))
    const user = userEvent.setup()
    const first = renderApp('/agents/a1')
    await edit(user, ' kept')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Could not save your changes')).toBeTruthy()
    expect(JSON.parse(window.sessionStorage.getItem('awaaz.studioDraft.a1')).form.name).toBe('Alpha kept')
    first.unmount()

    renderApp('/agents/a1') // after signing in again
    expect(await screen.findByText('You have unsaved edits from before your session ended')).toBeTruthy()
    expect((await field('Agent name')).value).toBe('Alpha') // not applied until the user chooses
    await user.click(screen.getByRole('button', { name: 'Restore my edits' }))
    expect((await field('Agent name')).value).toBe('Alpha kept')
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('All changes saved')).toBeTruthy()
    expect(window.sessionStorage.getItem('awaaz.studioDraft.a1')).toBeNull()
  })

  it('kept edits can be discarded', async () => {
    window.sessionStorage.setItem('awaaz.studioDraft.a1', JSON.stringify({ form: { name: 'Old draft' } }))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(screen.queryByText('You have unsaved edits from before your session ended')).toBeNull()
    expect(window.sessionStorage.getItem('awaaz.studioDraft.a1')).toBeNull()
    expect((await field('Agent name')).value).toBe('Alpha')
  })

  it('a kept draft identical to the saved agent is not offered', async () => {
    window.sessionStorage.setItem('awaaz.studioDraft.a1', JSON.stringify({ form: { name: 'Alpha' } }))
    renderApp('/agents/a1')
    await field('Agent name')
    expect(screen.queryByText('You have unsaved edits from before your session ended')).toBeNull()
  })

  it('does not overwrite a newer version: a change made elsewhere is reported and nothing is sent', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    changeElsewhere('a1', { system_prompt: 'Changed in another tab', is_active: false })
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('This agent was changed since you opened it')).toBeTruthy()
    expect(screen.getByText(/system prompt, active status/)).toBeTruthy()
    expect(api.agents.update).not.toHaveBeenCalled()
    expect(server.agents.get('a1').system_prompt).toBe('Changed in another tab')
    expect(screen.queryByText('All changes saved')).toBeNull()
    expect(screen.getByLabelText('Agent name').value).toBe('Alpha 2') // the edit is not thrown away
  })

  it('"Load latest version" shows the newer data and discards the stale edit', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    changeElsewhere('a1', { system_prompt: 'Changed in another tab' })
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await user.click(await screen.findByRole('button', { name: 'Load latest version' }))
    expect(await screen.findByText('Loaded the latest version. Your unsaved edits were discarded.')).toBeTruthy()
    expect(prompt().value).toBe('Changed in another tab')
    expect((await field('Agent name')).value).toBe('Alpha')
    expect(screen.queryByText('This agent was changed since you opened it')).toBeNull()
    expect(screen.getByText('Saved')).toBeTruthy()
  })

  it('"Save my changes anyway" sends only the fields the user edited, so the newer data is kept', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    changeElsewhere('a1', { system_prompt: 'Changed in another tab' })
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await user.click(await screen.findByRole('button', { name: 'Save my changes anyway' }))
    expect(await screen.findByText('All changes saved')).toBeTruthy()
    expect(api.agents.update).toHaveBeenCalledWith('a1', { name: 'Alpha 2' })
    expect(server.agents.get('a1')).toMatchObject({ name: 'Alpha 2', system_prompt: 'Changed in another tab' })
    expect(prompt().value).toBe('Changed in another tab')
  })

  it('a second save after a first uses the newest version, so repeated saving never trips the conflict check', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user, ' one')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await screen.findByText('All changes saved')
    await user.type(await field('Agent name'), ' two')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(server.agents.get('a1').name).toBe('Alpha one two'))
    expect(screen.queryByText('This agent was changed since you opened it')).toBeNull()
    expect(api.agents.update).toHaveBeenCalledTimes(2)
  })

  it('a whitespace-only edit is not an unsaved change, so the page cannot get stuck on "Unsaved changes"', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await user.type(await field('System prompt'), '   \n')
    expect(screen.queryByText('Unsaved changes')).toBeNull()
    expect(screen.getByRole('button', { name: 'Save changes' }).hasAttribute('disabled')).toBe(true)
  })

  it('pressing Save repeatedly sends a single request', async () => {
    let finish
    api.agents.update.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)))
    const user = userEvent.setup()
    renderApp('/agents/a1')
    await edit(user)
    const save = screen.getByRole('button', { name: 'Save changes' })
    await user.click(save)
    await user.click(save)
    await user.click(save)
    expect(api.agents.update).toHaveBeenCalledTimes(1)
    finish({ ...server.agents.get('a1'), name: 'Alpha 2' })
  })

  it('switching to another agent never shows or saves the previous agent’s edits', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/agents/a1')
    await edit(user)
    await router.navigate('/agents/a3')
    await user.click(await screen.findByRole('button', { name: 'Discard changes' }))
    expect((await field('Agent name')).value).toBe('Gamma')
    expect(screen.queryByText('Unsaved changes')).toBeNull()
  })
})
