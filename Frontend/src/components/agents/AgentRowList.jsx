import { Mic, Settings2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate, voiceSummary } from '../../utils/format.js'
import { languageLabel } from '../../utils/languages.js'
import Button from '../ui/Button.jsx'
import { AgentMenu, AgentStatusBadge } from './AgentCard.jsx'

/** The compact "list" layout of the agents page. */
export default function AgentRowList({ agents, onDelete }) {
  return (
    <ul className="card row-list" aria-label="Agents">
      {agents.map((agent) => (
        <li className="agent-row" key={agent.id}>
          <div className="agent-row-main">
            <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
            <small>
              {languageLabel(agent.language)} · {voiceSummary(agent)} · Updated {formatDate(agent.updated_at)}
              {agent.description ? ` · ${agent.description}` : ''}
            </small>
          </div>
          <AgentStatusBadge active={agent.is_active} />
          <div className="agent-row-actions">
            <Button to={`/agents/${agent.id}/configure`} size="sm" icon={Settings2} aria-label={`Configure ${agent.name}`}>
              Configure
            </Button>
            <Button to={`/agents/${agent.id}/talk`} size="sm" icon={Mic} aria-label={`Test ${agent.name}`}>
              Test
            </Button>
            <AgentMenu agent={agent} onDelete={onDelete} />
          </div>
        </li>
      ))}
    </ul>
  )
}
