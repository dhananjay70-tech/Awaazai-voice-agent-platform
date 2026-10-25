import { useEffect, useRef } from 'react'
import { useBlocker } from 'react-router-dom'
import ConfirmDialog from '../components/ui/ConfirmDialog.jsx'

/**
 * Warns before unsaved edits are lost: in-app navigation shows a confirmation dialog and closing the tab shows the
 * browser's own warning. Call `allowLeave()` right before a navigation that should not be blocked (after a save).
 * Render `dialog` somewhere in the page.
 */
export function useUnsavedChangesGuard(dirty) {
  const allowed = useRef(false)
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !allowed.current && currentLocation.pathname !== nextLocation.pathname)

  useEffect(() => {
    if (!dirty) return undefined
    const warn = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const dialog = (
    <ConfirmDialog
      open={blocker.state === 'blocked'}
      title="Discard unsaved changes?"
      confirmLabel="Discard changes"
      onConfirm={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      You have changes that haven’t been saved. If you leave this page they will be lost.
    </ConfirmDialog>
  )

  return {
    dialog,
    allowLeave() {
      allowed.current = true
    },
  }
}
