import { BookOpen, Bot, Mic, Plug, Plus } from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/index.js'
import { useAuth } from '../auth/useAuth.js'
import { AgentStatusBadge } from '../components/agents/AgentCard.jsx'
import Button from '../components/ui/Button.jsx'
import { EmptyState, ErrorState, Skeleton } from '../components/ui/States.jsx'
import VoiceServiceStatus from '../components/voice/VoiceServiceStatus.jsx'
import { describeVoiceStatus, useVoiceServiceStatus } from '../components/voice/voiceStatus.js'
import { useResource } from '../hooks/useResource.js'
import { firstName, formatDate } from '../utils/format.js'
import { languageLabel } from '../utils/languages.js'

const COUNT_LIMIT = 100 // the largest page the API allows; beyond it the totals are shown as "100+"
const PREVIEW_COUNT = 5

function Stat({ label, value, note, loading, to }) {
  const Wrapper = to ? Link : 'div'
  return (
    <Wrapper className={`card stat${to ? ' card-hover stat-link' : ''}`} {...(to ? { to } : {})}>
      <span className="stat-label">{label}</span>
      {loading ? <Skeleton width={60} height={32} /> : <span className="stat-value">{value}</span>}
      {note && <span className="stat-note">{note}</span>}
    </Wrapper>
  )
}

export default function DashboardPage() {
  const { user } = useAuth()
  const fetchAgents = useCallback((signal) => api.agents.list({ limit: COUNT_LIMIT, offset: 0 }, { signal }), [])
  const agentsResource = useResource(fetchAgents)
  const voiceResource = useVoiceServiceStatus()

  const { data: agents, loading, error, reload } = agentsResource
  const capped = agents?.length === COUNT_LIMIT
  const total = agents ? `${agents.length}${capped ? '+' : ''}` : '-'
  const active = agents ? `${agents.filter((agent) => agent.is_active).length}${capped ? '+' : ''}` : '-'
  const voiceInfo = describeVoiceStatus(voiceResource)
  const name = firstName(user)

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>{name ? `Welcome, ${name}` : 'Welcome'}</h2>
          <p>Create, configure and test your AI voice agents from one place.</p>
        </div>
      </div>

      <div className="stat-grid">
        <Stat label="Total agents" to="/agents" value={total} loading={loading} note={error ? 'Could not load' : undefined} />
        <Stat label="Active agents" to="/agents?status=active" value={active} loading={loading} note={error ? 'Could not load' : undefined} />
        <Link to="/playground" className="card stat card-hover stat-link">
          <span className="stat-label">Voice service</span>
          <VoiceServiceStatus resource={voiceResource} />
          <span className="stat-note">{voiceInfo.detail ?? 'Reported by the backend · open the playground'}</span>
        </Link>
      </div>

      <div className="two-col">
        <section className="card" aria-labelledby="your-agents">
          <div className="section-head">
            <h3 className="section-title" id="your-agents">
              Your agents
            </h3>
            {agents?.length > 0 && (
              <Link to="/agents" className="btn btn-ghost btn-sm">
                View all
              </Link>
            )}
          </div>
          {loading && (
            <div aria-busy="true" aria-label="Loading agents" style={{ display: 'grid', gap: 12 }}>
              <Skeleton height={44} />
              <Skeleton height={44} />
              <Skeleton height={44} />
            </div>
          )}
          {error && <ErrorState error={error} title="We couldn't load your agents" onRetry={reload} />}
          {agents?.length === 0 && (
            <EmptyState
              icon={Bot}
              title="No agents yet"
              actions={
                <Button to="/agents/new" variant="primary" icon={Plus}>
                  Create your first agent
                </Button>
              }
            >
              Agents hold the instructions, language and voice settings for a conversation.
            </EmptyState>
          )}
          {agents?.length > 0 &&
            agents.slice(0, PREVIEW_COUNT).map((agent) => (
              <div className="agent-row" key={agent.id}>
                <div>
                  <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                  <small>
                    {languageLabel(agent.language)} · Updated {formatDate(agent.updated_at)}
                  </small>
                </div>
                <AgentStatusBadge active={agent.is_active} />
              </div>
            ))}
        </section>

        <section className="card" aria-labelledby="getting-started">
          <h3 className="section-title" id="getting-started" style={{ marginBottom: 'var(--space-4)' }}>
            Getting started
          </h3>
          <ol className="steps">
            <li>
              <strong>Create an agent</strong>
              Name it and write its instructions.
            </li>
            <li>
              <strong>Choose language and voice</strong>
              Pick English, Hindi or Hinglish and a speaking speed.
            </li>
            <li>
              <strong>Test the conversation</strong>
              Try the agent in the studio’s test panel or the Playground with the <Mic size={13} aria-label="microphone" style={{ verticalAlign: '-2px' }} /> button.
            </li>
          </ol>
        </section>
      </div>

      <section aria-labelledby="quick-links">
        <h3 className="section-title" id="quick-links" style={{ marginBottom: 'var(--space-4)' }}>
          Quick links
        </h3>
        <div className="quick-grid">
          <Link to="/agents/new" className="card card-hover quick-link">
            <Plus size={18} aria-hidden="true" /> Create an agent
          </Link>
          <Link to="/agents" className="card card-hover quick-link">
            <Bot size={18} aria-hidden="true" /> Manage agents
          </Link>
          <Link to="/playground" className="card card-hover quick-link">
            <Mic size={18} aria-hidden="true" /> Voice playground
          </Link>
          <Link to="/knowledge" className="card card-hover quick-link">
            <BookOpen size={18} aria-hidden="true" /> Knowledge Base <span className="badge badge-warning">Soon</span>
          </Link>
          <Link to="/integrations" className="card card-hover quick-link">
            <Plug size={18} aria-hidden="true" /> Integrations <span className="badge badge-warning">Soon</span>
          </Link>
        </div>
      </section>
    </div>
  )
}
