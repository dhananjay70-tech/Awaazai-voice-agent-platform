import { createEvent, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SIDEBAR_WIDTH_KEY } from '../utils/sidebarWidth.js'
import { renderApp, resetApi } from './helpers.jsx'

vi.mock('../api/index.js', async (importOriginal) => (await import('./apiMock.js')).createApiModule(await importOriginal()))

beforeEach(resetApi)

const separator = () => screen.findByRole('separator', { name: 'Resize sidebar' })
const shell = () => document.querySelector('.app-shell')
const widthVar = () => shell().style.getPropertyValue('--sidebar-current')

// jsdom's PointerEvent has no coordinates, so build the event and define the fields the handler reads.
function pointer(element, type, { clientX = 0, pointerId = 1, button = 0 } = {}) {
  const event = createEvent[type](element, { bubbles: true })
  Object.defineProperties(event, { clientX: { value: clientX }, pointerId: { value: pointerId }, button: { value: button } })
  fireEvent(element, event)
}

describe('sidebar resize handle', () => {
  it('is an accessible separator with the width and its limits', async () => {
    renderApp('/dashboard')
    const handle = await separator()
    expect(handle.getAttribute('aria-orientation')).toBe('vertical')
    expect(handle.getAttribute('aria-valuenow')).toBe('240')
    expect(handle.getAttribute('aria-valuemin')).toBe('180')
    expect(handle.getAttribute('aria-valuemax')).toBe('320')
    expect(handle.tabIndex).toBe(0)
    expect(widthVar()).toBe('240px')
  })

  it('arrow keys resize in steps, Shift steps further, and the page follows at once', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const handle = await separator()
    handle.focus()
    await user.keyboard('{ArrowRight}')
    expect(handle.getAttribute('aria-valuenow')).toBe('256')
    expect(widthVar()).toBe('256px')
    await user.keyboard('{Shift>}{ArrowRight}{/Shift}')
    expect(widthVar()).toBe('304px')
    await user.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(widthVar()).toBe('272px')
  })

  it('stops at the limits: Home is the minimum, End the maximum, and keys cannot go past them', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const handle = await separator()
    handle.focus()
    await user.keyboard('{Home}')
    expect(widthVar()).toBe('180px')
    await user.keyboard('{ArrowLeft}')
    expect(widthVar()).toBe('180px')
    await user.keyboard('{End}')
    expect(widthVar()).toBe('320px')
    await user.keyboard('{ArrowRight}')
    expect(widthVar()).toBe('320px')
  })

  it('Enter and a double click restore the default width', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const handle = await separator()
    handle.focus()
    await user.keyboard('{End}{Enter}')
    expect(widthVar()).toBe('240px')
    await user.keyboard('{Home}')
    await user.dblClick(handle)
    expect(widthVar()).toBe('240px')
  })

  it('dragging with the mouse changes the width live and stays within the limits', async () => {
    renderApp('/dashboard')
    const handle = await separator()
    pointer(handle, 'pointerDown', { clientX: 240 })
    expect(shell().className).toContain('is-resizing')
    pointer(handle, 'pointerMove', { clientX: 290 })
    expect(widthVar()).toBe('290px')
    expect(handle.getAttribute('aria-valuenow')).toBe('290')
    pointer(handle, 'pointerMove', { clientX: 900 })
    expect(widthVar()).toBe('320px')
    pointer(handle, 'pointerMove', { clientX: 5 })
    expect(widthVar()).toBe('180px')
    pointer(handle, 'pointerUp', { clientX: 5 })
    expect(shell().className).not.toContain('is-resizing')
  })

  it('ignores movement when no drag is in progress, other pointers, and non-primary buttons', async () => {
    renderApp('/dashboard')
    const handle = await separator()
    pointer(handle, 'pointerMove', { clientX: 300 })
    expect(widthVar()).toBe('240px')
    pointer(handle, 'pointerDown', { clientX: 240, button: 2 })
    expect(shell().className).not.toContain('is-resizing')
    pointer(handle, 'pointerDown', { clientX: 240, pointerId: 1 })
    pointer(handle, 'pointerMove', { clientX: 300, pointerId: 2 }) // a second finger or device
    expect(widthVar()).toBe('240px')
    pointer(handle, 'pointerUp', { clientX: 240, pointerId: 1 })
  })

  it('a cancelled or lost drag ends cleanly', async () => {
    renderApp('/dashboard')
    const handle = await separator()
    pointer(handle, 'pointerDown', { clientX: 240 })
    pointer(handle, 'pointerMove', { clientX: 270 })
    pointer(handle, 'pointerCancel', { clientX: 270 })
    expect(shell().className).not.toContain('is-resizing')
    expect(widthVar()).toBe('270px')
  })

  it('needs no document-level listeners: nothing is added that could leak', async () => {
    const add = vi.spyOn(document, 'addEventListener')
    const addWindow = vi.spyOn(window, 'addEventListener')
    renderApp('/dashboard')
    const handle = await separator()
    add.mockClear()
    addWindow.mockClear()
    pointer(handle, 'pointerDown', { clientX: 240 })
    pointer(handle, 'pointerMove', { clientX: 260 })
    pointer(handle, 'pointerUp', { clientX: 260 })
    const moves = [...add.mock.calls, ...addWindow.mock.calls].filter(([type]) => /pointer|mouse|touch/.test(type))
    expect(moves).toEqual([])
  })

  it('remembers the finished width and reuses it next time', async () => {
    const user = userEvent.setup()
    const { unmount } = renderApp('/dashboard')
    const handle = await separator()
    handle.focus()
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(window.localStorage.getItem(SIDEBAR_WIDTH_KEY)).toBe('272')
    unmount()
    renderApp('/dashboard')
    await separator()
    expect(widthVar()).toBe('272px')
  })

  it('repairs a corrupt stored width', async () => {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, '99999')
    renderApp('/dashboard')
    await separator()
    expect(widthVar()).toBe('320px')
  })
})

describe('collapse and expand with a custom width', () => {
  it('collapses to the icon rail (no handle, tooltips on) and expands back to the same width', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const handle = await separator()
    handle.focus()
    await user.keyboard('{ArrowRight}')
    expect(widthVar()).toBe('256px')

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(document.getElementById('app-sidebar').className).toContain('is-collapsed')
    expect(screen.queryByRole('separator', { name: 'Resize sidebar' })).toBeNull()
    expect(widthVar()).toBe('') // the rail width comes from the stylesheet
    expect(screen.getByRole('link', { name: 'Agents' }).closest('.tooltip-host').querySelector('[role=tooltip]').textContent).toBe('Agents')

    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(widthVar()).toBe('256px')
    expect((await separator()).getAttribute('aria-valuenow')).toBe('256')
  })

  it('the resized sidebar is still one element with its navigation, and the main column is separate', async () => {
    renderApp('/dashboard')
    await separator()
    expect(document.querySelectorAll('#app-sidebar')).toHaveLength(1)
    expect(document.querySelectorAll('aside.sidebar')).toHaveLength(1)
    expect(document.getElementById('main-content')).toBeTruthy()
    expect(document.getElementById('app-sidebar').contains(document.getElementById('main-content'))).toBe(false)
  })
})
