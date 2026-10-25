import { Bot, LayoutGrid, List, Plus, Search } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api/index.js'
import AgentCard from '../components/agents/AgentCard.jsx'
import AgentRowList from '../components/agents/AgentRowList.jsx'
import AgentGridSkeleton from '../components/agents/AgentGridSkeleton.jsx'
import Button from '../components/ui/Button.jsx'
import ConfirmDialog from '../components/ui/ConfirmDialog.jsx'
import { EmptyState, ErrorState } from '../components/ui/States.jsx'
import { useToast } from '../components/ui/ToastContext.js'
import { useResource } from '../hooks/useResource.js'
import { AGENTS_PAGE_SIZE } from '../api/agents.js'

export default function AgentsPage() {
  const toast = useToast()
  const fetchFirstPage = useCallback((signal) => api.agents.list({ limit: AGENTS_PAGE_SIZE, offset: 0 }, { signal }), [])
  const { data: firstPage, error, loading, reload, setData } = useResource(fetchFirstPage)

  const [more, setMore] = useState([])
  const [lastPageFull, setLastPageFull] = useState(null) // null until a further page has been loaded
  const [loadingMore, setLoadingMore] = useState(false)
  const [moreError, setMoreError] = useState(null)

  // Search and status live in the URL, so a filtered list can be linked to (the dashboard does) and survives a refresh.
  const [searchParams, setSearchParams] = useSearchParams()
  // The text box keeps its own state (URL updates are asynchronous and would drop fast keystrokes); the URL is kept in sync.
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '')
  const statusParam = searchParams.get('status')
  const statusFilter = ['active', 'inactive'].includes(statusParam) ? statusParam : 'all'
  const [layout, setLayout] = useState('grid')

  function updateFilter(name, value) {
    const next = new URLSearchParams(searchParams)
    if (value && value !== 'all') next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  const agents = useMemo(() => [...(firstPage ?? []), ...more], [firstPage, more])
  const hasMore = lastPageFull ?? firstPage?.length === AGENTS_PAGE_SIZE

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return agents.filter((agent) => {
      if (statusFilter === 'active' && !agent.is_active) return false
      if (statusFilter === 'inactive' && agent.is_active) return false
      if (!needle) return true
      return agent.name.toLowerCase().includes(needle) || (agent.description ?? '').toLowerCase().includes(needle)
    })
  }, [agents, query, statusFilter])

  async function loadMore() {
    setLoadingMore(true)
    setMoreError(null)
    try {
      const page = await api.agents.list({ limit: AGENTS_PAGE_SIZE, offset: agents.length })
      setMore((current) => [...current, ...page])
      setLastPageFull(page.length === AGENTS_PAGE_SIZE)
    } catch (loadError) {
      setMoreError(loadError)
    } finally {
      setLoadingMore(false)
    }
  }

  async function confirmDelete() {
    const target = deleteTarget
    setDeleting(true)
    setDeleteError(null)
    try {
      await api.agents.remove(target.id)
    } catch (removeError) {
      if (!(removeError instanceof ApiError && removeError.status === 404)) {
        // Keep the agent visible: the server did not confirm the deletion.
        setDeleteError(removeError instanceof ApiError ? removeError.message : 'Could not delete the agent.')
        setDeleting(false)
        return
      }
    }
    // Confirmed by the server (204), or already gone (404): only now does it leave the list.
    setData((current) => (current ?? []).filter((agent) => agent.id !== target.id))
    setMore((current) => current.filter((agent) => agent.id !== target.id))
    toast.success(`Deleted “${target.name}”.`)
    setDeleting(false)
    setDeleteTarget(null)
  }

  let content
  if (loading) {
    content = <AgentGridSkeleton />
  } else if (error) {
    content = <ErrorState error={error} title="We couldn’t load your agents" onRetry={reload} />
  } else if (agents.length === 0) {
    content = (
      <EmptyState
        icon={Bot}
        title="Create your first agent"
        actions={
          <Button to="/agents/new" variant="primary" icon={Plus}>
            Create agent
          </Button>
        }
      >
        An agent combines instructions, a language and voice settings. Create one, then test the conversation.
      </EmptyState>
    )
  } else {
    content = (
      <>
        <div className="toolbar" role="search" aria-label="Filter agents">
          <div className="search">
            <Search size={17} aria-hidden="true" />
            <input
              className="input"
              type="search"
              placeholder="Search by name"
              aria-label="Search agents by name"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                updateFilter('q', event.target.value)
              }}
            />
          </div>
          <select className="select" aria-label="Filter by status" value={statusFilter} onChange={(event) => updateFilter('status', event.target.value)}>
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <div className="segmented" role="group" aria-label="Layout">
            <button type="button" aria-pressed={layout === 'grid'} onClick={() => setLayout('grid')} aria-label="Card layout">
              <LayoutGrid size={17} aria-hidden="true" />
            </button>
            <button type="button" aria-pressed={layout === 'list'} onClick={() => setLayout('list')} aria-label="List layout">
              <List size={17} aria-hidden="true" />
            </button>
          </div>
        </div>

        <p className="field-hint" role="status" aria-live="polite">
          Showing {visible.length} of {agents.length} loaded {agents.length === 1 ? 'agent' : 'agents'}.
        </p>

        {visible.length === 0 ? (
          <EmptyState
            icon={Search}
            title="No agents match your filters"
            actions={
              <Button
                onClick={() => {
                  setQuery('')
                  setSearchParams({}, { replace: true })
                }}
              >
                Clear filters
              </Button>
            }
          >
            Try a different search or clear the status filter.
          </EmptyState>
        ) : layout === 'grid' ? (
          <div className="agent-grid">
            {visible.map((agent) => (
              <AgentCard key={agent.id} agent={agent} onDelete={askDelete} />
            ))}
          </div>
        ) : (
          <AgentRowList agents={visible} onDelete={askDelete} />
        )}

        {moreError && <ErrorState error={moreError} title="We couldn’t load more agents" onRetry={loadMore} />}
        {hasMore && !moreError && (
          <div className="state-actions">
            <Button onClick={loadMore} loading={loadingMore}>
              Load more
            </Button>
          </div>
        )}
      </>
    )
  }

  function askDelete(agent) {
    setDeleteError(null)
    setDeleteTarget(agent)
  }

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Your agents</h2>
          <p>Create, configure, test and manage the voice agents in your workspace.</p>
        </div>
        <Button to="/agents/new" variant="primary" icon={Plus}>
          Create agent
        </Button>
      </div>

      {content}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`Delete “${deleteTarget?.name ?? ''}”?`}
        confirmLabel="Delete agent"
        busy={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      >
        This permanently removes the agent and its settings. This can’t be undone.
      </ConfirmDialog>
    </div>
  )
}
