import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { session } from '../auth/session.js'

// jsdom does not implement <dialog> modal behaviour; this mirrors the parts the app relies on.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute('open')
  }
}

// Layout effects the tests do not exercise.
window.scrollTo = () => {}
Element.prototype.scrollIntoView = () => {}

afterEach(() => {
  cleanup()
  session.signOut() // the session store is a module singleton: never leak a login into the next test
  window.localStorage.clear() // layout preferences and first-message drafts must not leak either
})
