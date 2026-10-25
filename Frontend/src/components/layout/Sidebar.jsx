import { ChevronDown, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { initials } from '../../utils/format.js'
import Logo from '../ui/Logo.jsx'
import Tooltip from '../ui/Tooltip.jsx'
import { BOTTOM_NAV, NAV_GROUPS } from './navigation.js'
import SidebarResizer from './SidebarResizer.jsx'

function NavItem({ item, collapsed, onNavigate }) {
  const { to, label, icon: Icon, soon } = item
  return (
    <Tooltip text={label} side="right" disabled={!collapsed}>
      <NavLink to={to} className="nav-item" aria-label={soon ? `${label} (coming soon)` : label} onClick={onNavigate}>
        <Icon size={18} aria-hidden="true" />
        <span className="nav-label">{label}</span>
        {soon && <span className="nav-soon">Soon</span>}
      </NavLink>
    </Tooltip>
  )
}

function NavGroup({ group, collapsed, onNavigate }) {
  const [open, setOpen] = useState(true)
  const headingId = `nav-group-${group.id}`
  // Expandable sections: the heading toggles its list. A collapsed (icon-only) sidebar always shows every item.
  const showItems = open || collapsed
  return (
    <div className="nav-group">
      {group.label && (
        <button type="button" className="nav-group-toggle" aria-expanded={open} aria-controls={headingId} onClick={() => setOpen((value) => !value)}>
          <span>{group.label}</span>
          <ChevronDown size={14} aria-hidden="true" className={open ? 'is-open' : ''} />
        </button>
      )}
      {showItems && (
        <div id={headingId} className="nav-group-items">
          {group.items.map((item) => (
            <NavItem key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Sidebar({ user, collapsed, onToggleCollapsed, mobileOpen, onCloseMobile, width, onWidthChange, onWidthCommit, onResizing }) {
  return (
    <>
      {mobileOpen && <div className="sidebar-backdrop" onClick={onCloseMobile} aria-hidden="true" />}
      <aside id="app-sidebar" className={`sidebar${collapsed ? ' is-collapsed' : ''}${mobileOpen ? ' is-open' : ''}`} aria-label="Sidebar">
        <div className="sidebar-top">
          <Logo to="/dashboard" compact={collapsed} />
          <button type="button" className="icon-btn sidebar-close" onClick={onCloseMobile} aria-label="Close navigation">
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <NavGroup key={group.id} group={group} collapsed={collapsed} onNavigate={onCloseMobile} />
          ))}
        </nav>

        <div className="sidebar-bottom">
          <nav aria-label="Secondary" className="nav-group-items">
            {BOTTOM_NAV.map((item) => (
              <NavItem key={item.to} item={item} collapsed={collapsed} onNavigate={onCloseMobile} />
            ))}
          </nav>
          <button
            type="button"
            className="nav-item sidebar-collapse"
            onClick={onToggleCollapsed}
            aria-pressed={collapsed}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
            <span className="nav-label">Collapse</span>
          </button>
          <Link to="/settings/profile" className="workspace" aria-label={`Your profile: ${user?.email ?? ''}`} onClick={onCloseMobile}>
            <span className="avatar" aria-hidden="true">
              {initials(user)}
            </span>
            <span className="workspace-text nav-label">
              <strong>{user?.full_name || 'Your workspace'}</strong>
              <span>{user?.email}</span>
            </span>
          </Link>
        </div>
        {!collapsed && <SidebarResizer width={width} onChange={onWidthChange} onCommit={onWidthCommit} onDragging={onResizing} />}
      </aside>
    </>
  )
}
