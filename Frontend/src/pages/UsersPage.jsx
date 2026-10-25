import { useAuth } from '../auth/useAuth.js'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { initials } from '../utils/format.js'

export default function UsersPage() {
  const { user } = useAuth()
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Users</h2>
          <p>The people who can use this workspace.</p>
        </div>
        <ComingSoonButton>Invite user</ComingSoonButton>
      </div>

      <ComingSoonNotice title="Team management is not configured">
        There are no workspaces, memberships or roles in the backend: every account is separate and only sees its own agents. Inviting people and assigning roles isn’t possible, and other accounts are never listed.
      </ComingSoonNotice>

      <section className="card" aria-labelledby="you">
        <h3 className="section-title" id="you" style={{ marginBottom: 'var(--space-4)' }}>
          You
        </h3>
        <div className="agent-row" style={{ borderBottom: 0 }}>
          <div className="user-line">
            <span className="avatar" aria-hidden="true">
              {initials(user)}
            </span>
            <div>
              <strong>{user?.full_name || 'No name set'}</strong>
              <small className="muted" style={{ display: 'block' }}>
                {user?.email}
              </small>
            </div>
          </div>
          <span className="badge badge-success">Signed in</span>
        </div>
      </section>
    </div>
  )
}
