import { Copy, ExternalLink, Mic, Settings2, Trash2, EllipsisVertical } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate, voiceSummary } from '../../utils/format.js'
import { languageLabel } from '../../utils/languages.js'
import Button from '../ui/Button.jsx'
import DropdownMenu from '../ui/DropdownMenu.jsx'
import { useToast } from '../ui/ToastContext.js'

export function AgentStatusBadge({ active }) {
  return (
    <span className={`badge ${active ? 'badge-success' : ''}`}>
      <span className="dot" aria-hidden="true" />
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}

/** The "more actions" menu shared by the card and the list row. */
export function AgentMenu({ agent, onDelete }) {
  const toast = useToast()
  async function copyId() {
    try {
      await navigator.clipboard.writeText(agent.id)
      toast.success('Agent ID copied.')
    } catch {
      toast.error('Could not copy the agent ID.')
    }
  }
  return (
    <DropdownMenu
      label={`More actions for ${agent.name}`}
      trigger={<EllipsisVertical size={17} aria-hidden="true" />}
      items={[
        { label: 'Open agent', icon: ExternalLink, to: `/agents/${agent.id}` },
        { label: 'Copy agent ID', icon: Copy, onSelect: copyId },
        { label: 'Delete agent', icon: Trash2, danger: true, onSelect: () => onDelete(agent) },
      ]}
    />
  )
}

export default function AgentCard({ agent, onDelete }) {
  return (
    <article className="card card-hover agent-card" aria-label={agent.name}>
      <div className="agent-card-head">
        <h3>
          <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
        </h3>
        <span className="agent-card-tools">
          <AgentStatusBadge active={agent.is_active} />
          <AgentMenu agent={agent} onDelete={onDelete} />
        </span>
      </div>
      <p className="agent-desc">{agent.description || <span className="muted">No description</span>}</p>
      <div className="agent-meta">
        <span>{languageLabel(agent.language)}</span>
        <span>{voiceSummary(agent)}</span>
        <span>Updated {formatDate(agent.updated_at)}</span>
      </div>
      <div className="agent-actions">
        <Button to={`/agents/${agent.id}`} size="sm" icon={ExternalLink} aria-label={`Open ${agent.name}`}>
          Open
        </Button>
        <Button to={`/agents/${agent.id}/configure`} size="sm" icon={Settings2} aria-label={`Configure ${agent.name}`}>
          Configure
        </Button>
        <Button to={`/agents/${agent.id}/talk`} size="sm" icon={Mic} aria-label={`Test ${agent.name}`}>
          Test
        </Button>
      </div>
    </article>
  )
}
