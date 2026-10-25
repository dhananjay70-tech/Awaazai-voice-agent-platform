import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initialState } from '../voice/voiceState.js'
import { renderApp, resetApi } from './helpers.jsx'

// The real voice hook opens WebSockets and the microphone. Here it is replaced by a controllable stand-in, so these
// tests exercise the playground's own behaviour without any network, device or billable provider.
const voice = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), cancel: vi.fn(), sendText: vi.fn(), newConversation: vi.fn(), setState: null, complete: null, url: null }))

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))
vi.mock('../voice/useVoiceClient.js', async () => {
  const React = await import('react')
  const { initialState: initial } = await import('../voice/voiceState.js')
  const BUSY = ['requesting-mic', 'connecting', 'listening', 'processing']
  return {
    useVoiceClient: (url, options) => {
      const [state, setState] = React.useState(initial)
      voice.setState = setState
      voice.complete = options?.onTurnComplete
      voice.url = url
      const speaking = Object.values(state.segments).some((status) => status === 'playing' || status === 'ready')
      return { state, busy: BUSY.includes(state.phase), speaking, start: voice.start, stop: voice.stop, cancel: voice.cancel, sendText: voice.sendText, newConversation: voice.newConversation }
    },
  }
})

beforeEach(() => {
  resetApi()
  for (const key of ['start', 'stop', 'cancel', 'sendText', 'newConversation']) voice[key].mockClear()
})

const setVoice = (patch) => act(() => voice.setState((state) => ({ ...state, ...patch })))
const finishTurn = (patch) => act(() => voice.complete({ ...initialState, phase: 'done', ...patch }))

async function openSession(user) {
  renderApp('/agents/a1/talk')
  await user.click(await screen.findByRole('button', { name: 'Start session' }))
}
const stateBadge = (label) => screen.getByText(label, { selector: '.badge' })
const clientError = (code, message) => ({ stage: 'client', code, message, requestId: null, fatal: true })

describe('live playground', () => {
  it('never connects or listens until a session is started', async () => {
    renderApp('/agents/a1/talk')
    await screen.findByRole('button', { name: 'Start session' })
    expect(voice.start).not.toHaveBeenCalled()
    expect(voice.sendText).not.toHaveBeenCalled()
    expect(stateBadge('Idle')).toBeTruthy()
    expect(voice.url).toBe('ws://127.0.0.1:8001/voice/stream') // the loopback-only voice URL
    expect(screen.queryByRole('button', { name: 'Talk' })).toBeNull()
    expect(screen.queryByLabelText('Or type a message')).toBeNull()
  })

  it('starting a session shows Ready with the controls, still without connecting', async () => {
    const user = userEvent.setup()
    await openSession(user)
    expect(stateBadge('Ready')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Talk' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'End session' })).toBeTruthy()
    expect(screen.getByLabelText('Or type a message')).toBeTruthy()
    expect(voice.start).not.toHaveBeenCalled()
  })

  it('Talk starts a spoken turn in the agent’s voice mode and Stop ends it', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.click(screen.getByRole('button', { name: 'Talk' }))
    expect(voice.start).toHaveBeenCalledWith('english')
    setVoice({ phase: 'listening' })
    expect(stateBadge('Listening')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    expect(voice.stop).toHaveBeenCalledTimes(1)
  })

  it('shows each stage of a turn: connecting, listening, processing, speaking, ready again', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.click(screen.getByRole('button', { name: 'Talk' }))
    setVoice({ phase: 'requesting-mic' })
    expect(stateBadge('Connecting')).toBeTruthy()
    setVoice({ phase: 'connecting' })
    expect(stateBadge('Connecting')).toBeTruthy()
    setVoice({ phase: 'listening' })
    expect(stateBadge('Listening')).toBeTruthy()
    setVoice({ phase: 'processing' })
    expect(stateBadge('Processing')).toBeTruthy()
    setVoice({ segments: { 0: 'playing' } })
    expect(stateBadge('Speaking')).toBeTruthy()
    setVoice({ phase: 'done', segments: { 0: 'played' } })
    expect(stateBadge('Ready')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Talk' }).hasAttribute('disabled')).toBe(false)
  })

  it('Cancel turn is only available while something is running', async () => {
    const user = userEvent.setup()
    await openSession(user)
    expect(screen.getByRole('button', { name: 'Cancel turn' }).hasAttribute('disabled')).toBe(true)
    setVoice({ phase: 'processing' })
    await user.click(screen.getByRole('button', { name: 'Cancel turn' }))
    expect(voice.cancel).toHaveBeenCalledTimes(1)
  })

  it('a typed message is sent in the voice mode, clears the box, and is reported as processing, not listening', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.type(screen.getByLabelText('Or type a message'), 'book me in')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(voice.sendText).toHaveBeenCalledWith('book me in', 'english')
    expect(screen.getByLabelText('Or type a message').value).toBe('')
    setVoice({ phase: 'listening' }) // the socket is ready and the text has been sent
    expect(stateBadge('Processing')).toBeTruthy()
    expect(within(screen.getByRole('log')).getByText('book me in')).toBeTruthy() // shown while the turn runs
  })

  it('the Send button needs text and is disabled while a turn runs', async () => {
    const user = userEvent.setup()
    await openSession(user)
    expect(screen.getByRole('button', { name: 'Send' }).hasAttribute('disabled')).toBe(true)
    setVoice({ phase: 'processing' })
    expect(screen.getByLabelText('Or type a message').hasAttribute('disabled')).toBe(true)
  })
})

describe('transcript', () => {
  it('shows the live partial transcript and reply while the turn runs', async () => {
    const user = userEvent.setup()
    await openSession(user)
    setVoice({ phase: 'processing', finals: ['what are'], partial: 'your hours', replyText: 'We open at nine' })
    const log = screen.getByRole('log', { name: 'Conversation transcript' })
    expect(within(log).getByText(/what are/)).toBeTruthy()
    expect(within(log).getByText(/your hours/)).toBeTruthy()
    expect(within(log).getByText('We open at nine')).toBeTruthy()
  })

  it('keeps every finished turn in order, as a history of the session', async () => {
    const user = userEvent.setup()
    await openSession(user)
    finishTurn({ finals: ['hello'], replyText: 'Hi there!', audioComplete: true })
    finishTurn({ finals: ['book Friday'], replyText: 'Friday works.', audioComplete: true })
    const bubbles = within(screen.getByRole('log')).getAllByText(/./, { selector: '.bubble' }).map((bubble) => bubble.textContent)
    expect(bubbles).toEqual(['Youhello', 'AgentHi there!', 'Youbook Friday', 'AgentFriday works.'])
  })

  it('records a typed turn with the typed text, and notes when speech failed part-way', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.type(screen.getByLabelText('Or type a message'), 'hi')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    finishTurn({ replyText: 'Hello!', audioComplete: false })
    const log = within(screen.getByRole('log'))
    expect(log.getByText('hi')).toBeTruthy()
    expect(log.getByText('Hello!')).toBeTruthy()
    expect(log.getByText('Speech failed part-way; the text is complete.')).toBeTruthy()
  })

  it('shows non-fatal warnings (such as one failed spoken sentence) without ending the turn', async () => {
    const user = userEvent.setup()
    await openSession(user)
    setVoice({ phase: 'processing', warnings: [{ stage: 'tts', code: 'tts_failed', message: 'One sentence could not be spoken.', requestId: null, fatal: false }] })
    expect(screen.getByText('One sentence could not be spoken.')).toBeTruthy()
    expect(stateBadge('Processing')).toBeTruthy()
  })

  it('Clear transcript asks first, then empties the history and starts a fresh conversation', async () => {
    const user = userEvent.setup()
    await openSession(user)
    finishTurn({ finals: ['hello'], replyText: 'Hi!' })
    await user.click(screen.getByRole('button', { name: 'Clear transcript' }))
    const dialog = await screen.findByRole('dialog', { name: 'Clear this conversation?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(within(screen.getByRole('log')).getByText('Hi!')).toBeTruthy()
    voice.newConversation.mockClear()
    await user.click(screen.getByRole('button', { name: 'Clear transcript' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Clear' }))
    expect(within(screen.getByRole('log')).queryByText('Hi!')).toBeNull()
    expect(voice.newConversation).toHaveBeenCalledTimes(1)
  })
})

describe('session end and failures', () => {
  it('End session stops everything, shows "Conversation ended" and keeps the transcript until a new session starts', async () => {
    const user = userEvent.setup()
    await openSession(user)
    finishTurn({ finals: ['hello'], replyText: 'Hi!' })
    voice.newConversation.mockClear()
    await user.click(screen.getByRole('button', { name: 'End session' }))
    expect(voice.newConversation).toHaveBeenCalledTimes(1)
    expect(stateBadge('Conversation ended')).toBeTruthy()
    expect(within(screen.getByRole('log')).getByText('Hi!')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Talk' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Start new session' }))
    expect(stateBadge('Ready')).toBeTruthy()
    expect(within(screen.getByRole('log')).queryByText('Hi!')).toBeNull() // a new session begins with a clean transcript
  })

  it('reports a blocked microphone clearly, offers a retry, and still allows typing', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.click(screen.getByRole('button', { name: 'Talk' }))
    setVoice({ phase: 'error', error: clientError('permission_denied', 'Microphone permission was denied.') })
    expect(stateBadge('Microphone blocked')).toBeTruthy()
    expect(screen.getByText('Microphone access is blocked')).toBeTruthy()
    expect(screen.getByLabelText('Or type a message').hasAttribute('disabled')).toBe(false)
    voice.start.mockClear()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(voice.start).toHaveBeenCalledWith('english')
  })

  it('reports a lost connection as Disconnected, with the request id when the server gave one', async () => {
    const user = userEvent.setup()
    await openSession(user)
    setVoice({ phase: 'error', error: { ...clientError('connection_lost', 'The connection to the voice service was lost.'), requestId: 'req-7' } })
    expect(stateBadge('Disconnected')).toBeTruthy()
    expect(screen.getByText('The connection to the voice service was lost.')).toBeTruthy()
    expect(screen.getByText(/Request ID: req-7/)).toBeTruthy()
  })

  it('other failures show as Error with the message, and Retry resends a typed message', async () => {
    const user = userEvent.setup()
    await openSession(user)
    await user.type(screen.getByLabelText('Or type a message'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    setVoice({ phase: 'error', error: clientError('connection_failed', 'Could not connect to the voice service.') })
    expect(stateBadge('Error')).toBeTruthy()
    expect(screen.getByText('Could not connect to the voice service.')).toBeTruthy()
    voice.sendText.mockClear()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(voice.sendText).toHaveBeenCalledWith('hello', 'english')
  })

  it('a server error names the stage that failed', async () => {
    const user = userEvent.setup()
    await openSession(user)
    setVoice({ phase: 'error', error: { stage: 'stt', code: 'stt_unavailable', message: 'Speech-to-text is unavailable.', requestId: null, fatal: true } })
    expect(screen.getByText('Error in stt')).toBeTruthy()
  })
})

describe('where the playground appears', () => {
  it('is also the right-hand panel of the agent studio, with its state and the same controls', async () => {
    const user = userEvent.setup()
    renderApp('/agents/a1')
    const panel = await screen.findByRole('complementary', { name: 'Test agent' })
    await user.click(within(panel).getByRole('button', { name: 'Start session' }))
    expect(within(panel).getByRole('button', { name: 'Talk' })).toBeTruthy()
    expect(voice.start).not.toHaveBeenCalled()
  })

  it('the playground page keeps the session when the agent selector is used, and names the agent', async () => {
    const user = userEvent.setup()
    renderApp('/playground')
    await user.selectOptions(await screen.findByLabelText('Agent'), 'a3')
    expect(screen.getByLabelText('Language').value).toBe('hi-Latn')
    await user.click(screen.getByRole('button', { name: 'Start session' }))
    await user.click(screen.getByRole('button', { name: 'Talk' }))
    expect(voice.start).toHaveBeenCalledWith('hinglish')
    expect(within(screen.getByRole('region', { name: 'Live voice playground' })).getByText('Gamma')).toBeTruthy()
  })
})

