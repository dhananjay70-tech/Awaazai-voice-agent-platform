import { Menu, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useMatches, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth.js'
import { useSidebarWidth } from '../../hooks/useSidebarWidth.js'
import Button from '../ui/Button.jsx'
import ErrorBoundary from '../ui/ErrorBoundary.jsx'
import { buildCrumbs } from './navigation.js'
import Sidebar from './Sidebar.jsx'
import UserMenu from './UserMenu.jsx'

function useCollapsedPreference() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('awaaz.sidebar') === 'collapsed' // a layout preference only, never a credential
    } catch {
      return false
    }
  })
  function toggle() {
    setCollapsed((value) => {
      try {
        window.localStorage.setItem('awaaz.sidebar', value ? 'expanded' : 'collapsed')
      } catch {
        // storage unavailable: the preference just won't persist
      }
      return !value
    })
  }
  return [collapsed, toggle]
}

export default function AppShell() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const matches = useMatches()
  const [collapsed, toggleCollapsed] = useCollapsedPreference()
  const sidebarWidth = useSidebarWidth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [crumbLabel, setCrumbLabel] = useState(null)

  const handle = [...matches].reverse().find((match) => match.handle)?.handle
  const crumbs = buildCrumbs(location.pathname, crumbLabel)
  const title = crumbs[crumbs.length - 1].label
  const showCreate = Boolean(handle?.showCreate)

  useEffect(() => {
    document.title = `${title} · AwaazAI`
  }, [title])

  useEffect(() => {
    if (!mobileOpen) return undefined
    const onKeyDown = (event) => event.key === 'Escape' && setMobileOpen(false)
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [mobileOpen])

  function handleSignOut() {
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div
      className={`app-shell${collapsed ? ' is-collapsed' : ''}${sidebarWidth.resizing ? ' is-resizing' : ''}`}
      style={collapsed ? undefined : { '--sidebar-current': `${sidebarWidth.width}px` }}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar
        user={user}
        collapsed={collapsed}
        onToggleCollapsed={toggleCollapsed}
        width={sidebarWidth.width}
        onWidthChange={sidebarWidth.change}
        onWidthCommit={sidebarWidth.commit}
        onResizing={sidebarWidth.setResizing}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="app-main">
        <header className="app-header">
          <button
            type="button"
            className="icon-btn menu-toggle"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            aria-controls="app-sidebar"
          >
            <Menu size={20} aria-hidden="true" />
          </button>
          <div className="app-heading">
            {crumbs.length > 1 && (
            <nav className="breadcrumb" aria-label="Breadcrumb">
              {crumbs.map((crumb, index) => (
                <span className="crumb" key={crumb.label + index}>
                  {index > 0 && <span aria-hidden="true">/</span>}
                  {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span aria-current="page">{crumb.label}</span>}
                </span>
              ))}
            </nav>
            )}
            <h1 className={`app-title${handle?.hideTitle ? ' sr-only' : ''}`}>{title}</h1>
          </div>
          <div className="app-header-actions">
            {showCreate && (
              <Button to="/agents/new" variant="primary" size="sm" icon={Plus}>
                Create agent
              </Button>
            )}
            <UserMenu user={user} onSignOut={handleSignOut} />
          </div>
        </header>
        <main id="main-content" className={`app-content${handle?.wide ? ' is-wide' : ''}`} tabIndex={-1}>
          <ErrorBoundary key={location.pathname.split('/').slice(1, 3).join('/')}>
            <Outlet context={{ setCrumbLabel }} />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
