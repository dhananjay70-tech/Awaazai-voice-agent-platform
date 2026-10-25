import { ChevronDown, LogOut, Settings } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { initials } from '../../utils/format.js'

export default function UserMenu({ user, onSignOut }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return undefined
    function onPointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="user-menu-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden="true">
          {initials(user)}
        </span>
        <span className="sr-only">Account menu for {user?.email}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <div className="menu" id={menuId} role="menu">
          <div className="menu-header">
            <strong>{user?.full_name || 'Signed in'}</strong>
            <span>{user?.email}</span>
          </div>
          <Link to="/settings" className="menu-item" role="menuitem" onClick={() => setOpen(false)}>
            <Settings size={16} aria-hidden="true" /> Settings
          </Link>
          <button type="button" className="menu-item" role="menuitem" onClick={onSignOut}>
            <LogOut size={16} aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}
