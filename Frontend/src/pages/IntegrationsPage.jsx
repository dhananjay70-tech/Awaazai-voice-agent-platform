import { AudioLines, MessageSquare, Search, Sparkles, Users, Webhook } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

// Categories of integration the product is aimed at. None is connectable; every card says so.
const CATALOG = [
  { id: 'ai', category: 'AI and model providers', icon: Sparkles, title: 'Language models', text: 'Choose which model writes an agent’s replies. Today the voice service picks it for every agent.' },
  { id: 'speech', category: 'AI and model providers', icon: AudioLines, title: 'Speech providers', text: 'Speech-to-text and text-to-speech providers. They are configured on the voice service, not per account.' },
  { id: 'communication', category: 'Communication', icon: MessageSquare, title: 'Telephony and messaging', text: 'Phone, SMS and chat channels that connect customers to an agent.' },
  { id: 'business', category: 'Business applications', icon: Users, title: 'Calendars, CRMs and helpdesks', text: 'Check availability, look up callers and create tickets during a call.' },
  { id: 'custom', category: 'Custom APIs', icon: Webhook, title: 'Webhooks and custom APIs', text: 'Send conversation events to your own systems or call your own endpoints.' },
]
const CATEGORIES = ['All', ...new Set(CATALOG.map((item) => item.category))]

export default function IntegrationsPage() {
  const [category, setCategory] = useState('All')
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return CATALOG.filter((item) => (category === 'All' || item.category === category) && (!needle || `${item.title} ${item.text}`.toLowerCase().includes(needle)))
  }, [category, query])

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Integrations</h2>
          <p>Connect your agents to the tools your team already uses.</p>
        </div>
      </div>

      <ComingSoonNotice title="No integrations are available yet">
        The cards below show the kinds of integrations planned. None can be connected in this version, and none is connected.
      </ComingSoonNotice>

      <div className="toolbar" role="search" aria-label="Filter integrations">
        <div className="search">
          <Search size={17} aria-hidden="true" />
          <input className="input" type="search" placeholder="Search integrations" aria-label="Search integrations" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <select className="select" aria-label="Filter by category" value={category} onChange={(event) => setCategory(event.target.value)}>
          {CATEGORIES.map((name) => (
            <option key={name} value={name}>
              {name === 'All' ? 'All categories' : name}
            </option>
          ))}
        </select>
      </div>

      {visible.length === 0 ? (
        <EmptyState icon={Search} title="No integrations match">
          Try a different search or category.
        </EmptyState>
      ) : (
        <div className="source-grid">
          {visible.map(({ id, category: group, icon: Icon, title, text }) => (
            <article className="card source-card" key={id} aria-label={title}>
              <span className="state-icon">
                <Icon size={22} aria-hidden="true" />
              </span>
              <h3>{title}</h3>
              <p>{text}</p>
              <div className="agent-meta">
                <span className="badge">{group}</span>
                <span className="badge badge-warning">Not available</span>
              </div>
              <ComingSoonButton>Connect</ComingSoonButton>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
