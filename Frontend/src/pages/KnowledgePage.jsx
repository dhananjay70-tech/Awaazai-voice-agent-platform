import { Search } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/index.js'
import KnowledgeSources from '../components/knowledge/KnowledgeSources.jsx'
import { ErrorState, Skeleton } from '../components/ui/States.jsx'
import { useResource } from '../hooks/useResource.js'

/** Workspace-wide knowledge overview: the source structure plus each real agent and its (empty) knowledge state. */
export default function KnowledgePage() {
  const fetchAgents = useCallback((signal) => api.agents.list({ limit: 100, offset: 0 }, { signal }), [])
  const { data: agents, error, loading, reload } = useResource(fetchAgents)
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (agents ?? []).filter((agent) => agent.name.toLowerCase().includes(needle))
  }, [agents, query])

  return (
    <div className="page-stack">
      <KnowledgeSources />

      <section className="card page-stack" aria-labelledby="assoc-title" style={{ gap: 'var(--space-4)' }}>
        <div className="section-head" style={{ marginBottom: 0 }}>
          <h3 className="section-title" id="assoc-title">
            Agents and their knowledge
          </h3>
        </div>
        {loading && <Skeleton height={80} />}
        {error && <ErrorState error={error} title="We couldn’t load your agents" onRetry={reload} />}
        {agents?.length === 0 && <p className="muted">You have no agents yet, so there is nothing to attach knowledge to.</p>}
        {agents?.length > 0 && (
          <>
            <div className="toolbar toolbar-compact">
              <div className="search">
                <Search size={17} aria-hidden="true" />
                <input className="input" type="search" placeholder="Search agents" aria-label="Search agents" value={query} onChange={(event) => setQuery(event.target.value)} />
              </div>
            </div>
            {visible.length === 0 ? (
              <p className="muted">No agents match “{query}”.</p>
            ) : (
              <ul className="row-list" aria-label="Agents">
                {visible.map((agent) => (
                  <li className="agent-row" key={agent.id}>
                    <div className="agent-row-main">
                      <Link to={`/agents/${agent.id}/knowledge`}>{agent.name}</Link>
                      <small>No knowledge sources · ingestion not connected</small>
                    </div>
                    <span className="badge">0 sources</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  )
}
