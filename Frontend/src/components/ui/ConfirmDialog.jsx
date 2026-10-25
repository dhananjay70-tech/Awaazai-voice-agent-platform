import { useEffect, useId, useRef } from 'react'
import Button from './Button.jsx'

/**
 * Modal confirmation built on the native <dialog>: the browser traps focus, restores it on close and handles Escape.
 * Render it only while it is needed (`open`); `busy` blocks every way of dismissing it while the action runs.
 */
export default function ConfirmDialog({ open, title, children, confirmLabel = 'Confirm', tone = 'danger', busy = false, error, onConfirm, onCancel }) {
  const ref = useRef(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return undefined
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
    return undefined
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault() // we close it ourselves so a running request cannot be dismissed
        if (!busy) onCancel()
      }}
      onClick={(event) => {
        if (event.target === ref.current && !busy) onCancel()
      }}
    >
      {open && (
        <div className="dialog-body">
          <h2 className="dialog-title" id={titleId}>
            {title}
          </h2>
          <div className="dialog-text">{children}</div>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <Button variant="ghost" onClick={onCancel} disabled={busy} autoFocus>
              Cancel
            </Button>
            <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} loading={busy}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      )}
    </dialog>
  )
}
