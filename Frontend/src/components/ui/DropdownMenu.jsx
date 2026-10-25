import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

/**
 * A button that opens a menu of actions. Keyboard: Enter/Space/ArrowDown open it, arrows move, Home/End jump,
 * Escape closes and returns focus to the button, Tab closes. `items`: [{ label, icon, to | onSelect, danger, disabled, hint }].
 */
export default function DropdownMenu({ label, trigger, items, align = 'right', direction = 'down', className = '' }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const menuId = useId()

  const focusables = () => [...(rootRef.current?.querySelectorAll('[role="menuitem"]:not([aria-disabled="true"])') ?? [])]

  useEffect(() => {
    if (!open) return undefined
    focusables()[0]?.focus()
    function onPointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  function close(restoreFocus = true) {
    setOpen(false)
    if (restoreFocus) buttonRef.current?.focus()
  }

  function onKeyDown(event) {
    if (!open) return
    const list = focusables()
    const index = list.indexOf(document.activeElement)
    const move = (next) => {
      event.preventDefault()
      list[(next + list.length) % list.length]?.focus()
    }
    if (event.key === 'ArrowDown') move(index + 1)
    else if (event.key === 'ArrowUp') move(index - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(list.length - 1)
    else if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'Tab') close(false)
  }

  return (
    <div className={`dropdown ${className}`} ref={rootRef} onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        className="dropdown-trigger"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {trigger}
      </button>
      {open && (
        <div className={`menu dropdown-menu align-${align} direction-${direction}`} id={menuId} role="menu" aria-label={label}>
          {items.map((item) => {
            const content = (
              <>
                {item.icon && <item.icon size={16} aria-hidden="true" />}
                <span className="menu-item-text">
                  {item.label}
                  {item.hint && <small>{item.hint}</small>}
                </span>
              </>
            )
            const classes = `menu-item${item.danger ? ' is-danger' : ''}`
            if (item.to && !item.disabled) {
              return (
                <Link key={item.label} to={item.to} role="menuitem" className={classes} onClick={() => close(false)}>
                  {content}
                </Link>
              )
            }
            return (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={classes}
                aria-disabled={item.disabled || undefined}
                tabIndex={item.disabled ? -1 : 0}
                onClick={() => {
                  if (item.disabled) return
                  close(false)
                  item.onSelect?.()
                }}
              >
                {content}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
