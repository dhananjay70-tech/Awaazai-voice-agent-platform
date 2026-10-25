import { useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../../api/index.js'
import { useResource } from '../../hooks/useResource.js'
import { useCrumbLabel } from '../layout/crumbs.js'
import Button from '../ui/Button.jsx'
import { ErrorState, Skeleton } from '../ui/States.jsx'

function Loaded({ id, children }) {
  const fetchAgent = useCallback((signal) => api.agents.get(id, { signal }), [id])
  const { data: agent, error, loading, reload, setData } = useResource(fetchAgent)
  useCrumbLabel(agent?.name)

  if (loading) {
    return (
      <div className="card" aria-busy="true" aria-label="Loading agent" style={{ display: 'grid', gap: 16 }}>
        <Skeleton width="35%" height={24} />
        <Skeleton height={44} />
        <Skeleton height={160} />
      </div>
    )
  }
  if (error) {
    const missing = error.status === 404
    return (
      <ErrorState
        error={error}
        title={missing ? 'Agent not found' : 'We couldn’t load this agent'}
        onRetry={missing ? undefined : reload}
        actions={
          <Button to="/agents" variant="outline">
            Back to agents
          </Button>
        }
      />
    )
  }
  return children(agent, setData)
}

/**
 * Loads the agent named by the :id route parameter (owner-scoped by the server) and renders `children(agent, setAgent)`.
 * Keyed by id, so moving between agents never shows the previous one's data.
 */
export default function AgentLoader({ children }) {
  const { id } = useParams()
  return (
    <Loaded key={id} id={id}>
      {children}
    </Loaded>
  )
}
