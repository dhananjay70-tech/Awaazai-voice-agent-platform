import { LogOut } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { API_BASE_URL } from '../api/index.js'
import { useAuth } from '../auth/useAuth.js'
import Alert from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import Field from '../components/ui/Field.jsx'
import { formatDateTime } from '../utils/format.js'

const SIDEBAR_KEY = 'awaaz.sidebar' // the same layout preference the sidebar reads (never a credential)

/** Layout for /settings/*: a sub-navigation and the active settings page. */
export function SettingsLayout() {
  return (
    <div className="page-stack" style={{ maxWidth: 'var(--width-narrow)' }}>
      <nav className="subnav" aria-label="Settings sections">
        {[
          ['/settings/profile', 'Profile'],
          ['/settings/account', 'Account'],
          ['/settings/preferences', 'Preferences'],
          ['/settings/security', 'Security'],
        ].map(([to, label]) => (
          <NavLink key={to} to={to} className="subnav-link">
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}

function useSignOut() {
  const { signOut } = useAuth()
  const navigate = useNavigate()
  return () => {
    signOut()
    navigate('/login', { replace: true })
  }
}

function Panel({ title, id, children }) {
  return (
    <section className="card page-stack" aria-labelledby={id} style={{ gap: 'var(--space-4)' }}>
      <h2 className="section-title" id={id}>
        {title}
      </h2>
      {children}
    </section>
  )
}

export function ProfilePage() {
  const { user } = useAuth()
  return (
    <Panel title="Profile" id="profile-title">
      <dl className="meta-list">
        <div>
          <dt>Name</dt>
          <dd>{user?.full_name || 'Not provided'}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd>{user?.email}</dd>
        </div>
      </dl>
      <p className="field-hint">These details come from your account. Editing your name or email isn’t supported by the backend yet, so there is nothing to save here.</p>
    </Panel>
  )
}

export function AccountPage() {
  const { user } = useAuth()
  return (
    <Panel title="Account" id="account-title">
      <dl className="meta-list">
        <div>
          <dt>Account ID</dt>
          <dd>
            <code>{user?.id}</code>
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{user?.is_active ? 'Active' : 'Inactive'}</dd>
        </div>
        <div>
          <dt>Member since</dt>
          <dd>{formatDateTime(user?.created_at)}</dd>
        </div>
        <div>
          <dt>API address</dt>
          <dd>
            <code>{API_BASE_URL}</code>
          </dd>
        </div>
      </dl>
      <p className="field-hint">Password changes, billing, API keys and account deletion are not available.</p>
    </Panel>
  )
}

function readSidebarPreference() {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === 'collapsed' ? 'collapsed' : 'expanded'
  } catch {
    return 'expanded'
  }
}

export function PreferencesPage() {
  const [sidebar, setSidebar] = useState(readSidebarPreference)
  const [stored, setStored] = useState(true)

  function change(event) {
    const value = event.target.value
    setSidebar(value)
    try {
      window.localStorage.setItem(SIDEBAR_KEY, value)
      setStored(true)
    } catch {
      setStored(false)
    }
  }

  return (
    <Panel title="Preferences" id="prefs-title">
      <Field as="select" label="Sidebar" value={sidebar} onChange={change} hint="How the sidebar looks when the app opens. Stored in this browser only.">
        <option value="expanded">Expanded</option>
        <option value="collapsed">Collapsed (icons only)</option>
      </Field>
      {!stored && <Alert tone="warning">This browser blocks storage, so the preference will not be remembered.</Alert>}
      <Field label="Theme" value="Dark" readOnly hint="Dark is the only theme at the moment." />
      <p className="field-hint">A language preference for the interface isn’t available: the app is in English.</p>
    </Panel>
  )
}

export function SecurityPage() {
  const signOut = useSignOut()
  return (
    <>
      <Panel title="Session" id="session-title">
        <Alert tone="info">
          Your sign-in is kept in memory only and lasts 30 minutes. Reloading the page or closing the tab ends it, and you’ll need to sign in again. There is no server-side sign-out, so signing out clears the
          session in this browser.
        </Alert>
        <div>
          <Button icon={LogOut} onClick={signOut}>
            Sign out
          </Button>
        </div>
      </Panel>
      <Panel title="Guidance" id="guidance-title">
        <ul className="feature-list">
          <li>
            <span>Use a password you don’t use anywhere else.</span>
          </li>
          <li>
            <span>Sign out on shared computers.</span>
          </li>
          <li>
            <span>Never paste provider API keys into a prompt or any field in this app.</span>
          </li>
        </ul>
      </Panel>
    </>
  )
}
