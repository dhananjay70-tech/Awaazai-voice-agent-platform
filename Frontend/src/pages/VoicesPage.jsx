import { Search, Volume2 } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/index.js'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState, ErrorState, Skeleton } from '../components/ui/States.jsx'
import { useResource } from '../hooks/useResource.js'
import { AGENT_LANGUAGES, languageLabel } from '../utils/languages.js'

export default function VoicesPage() {
  const fetchAgents = useCallback((signal) => api.agents.list({ limit: 100, offset: 0 }, { signal }), [])
  const { data: agents, error, loading, reload } = useResource(fetchAgents)
  const [query, setQuery] = useState('')

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (agents ?? []).filter((agent) => `${agent.name} ${agent.voice_config.provider ?? ''} ${agent.voice_config.voice_id ?? ''}`.toLowerCase().includes(needle))
  }, [agents, query])

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Voices</h2>
          <p>The voices your agents use, and the languages the voice service supports.</p>
        </div>
      </div>

      <ComingSoonNotice title="No voice catalogue is connected">
        There is no service that lists available voices or plays a preview, so voices can’t be browsed here and none is invented. You can still store a provider and voice ID on an agent in the studio.
      </ComingSoonNotice>

      <section className="card page-stack" aria-labelledby="voice-catalog" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="voice-catalog">
          Voice library
        </h3>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Voice</th>
              <th scope="col">Provider</th>
              <th scope="col">Languages</th>
              <th scope="col">Preview</th>
              <th scope="col">Select</th>
            </tr>
          </thead>
        </table>
        <EmptyState icon={Volume2} title="No voices to show">
          When a voice catalogue is connected, each voice will appear here with its provider, languages, a preview and a button to select it for an agent.
        </EmptyState>
        <div>
          <ComingSoonButton>Preview voice</ComingSoonButton>
        </div>
      </section>

      <section className="card page-stack" aria-labelledby="voice-use" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="voice-use">
          Voices in use by your agents
        </h3>
        {loading && <Skeleton height={80} />}
        {error && <ErrorState error={error} title="We couldn’t load your agents" onRetry={reload} />}
        {agents?.length === 0 && <p className="muted">You have no agents yet.</p>}
        {agents?.length > 0 && (
          <>
            <div className="toolbar toolbar-compact">
              <div className="search">
                <Search size={17} aria-hidden="true" />
                <input className="input" type="search" placeholder="Search by agent, provider or voice" aria-label="Search voices in use" value={query} onChange={(event) => setQuery(event.target.value)} />
              </div>
            </div>
            {rows.length === 0 ? (
              <p className="muted">Nothing matches “{query}”.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Agent</th>
                    <th scope="col">Provider</th>
                    <th scope="col">Voice ID</th>
                    <th scope="col">Speed</th>
                    <th scope="col">Language</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((agent) => (
                    <tr key={agent.id}>
                      <td>
                        <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                      </td>
                      <td>{agent.voice_config.provider || <span className="muted">Default</span>}</td>
                      <td>{agent.voice_config.voice_id || <span className="muted">Default</span>}</td>
                      <td>{agent.voice_config.speed}</td>
                      <td>{languageLabel(agent.language)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>

      <section className="card page-stack" aria-labelledby="voice-langs" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="voice-langs">
          Supported languages
        </h3>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Language</th>
              <th scope="col">Stored tag</th>
              <th scope="col">Voice mode</th>
            </tr>
          </thead>
          <tbody>
            {AGENT_LANGUAGES.map((language) => (
              <tr key={language.value}>
                <td>{language.label}</td>
                <td>
                  <code>{language.value}</code>
                </td>
                <td>
                  <code>{language.voiceLanguage}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
