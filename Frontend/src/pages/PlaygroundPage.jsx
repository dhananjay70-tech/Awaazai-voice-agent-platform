import { useCallback, useState } from 'react'
import { api } from '../api/index.js'
import Alert from '../components/ui/Alert.jsx'
import Field from '../components/ui/Field.jsx'
import { ErrorState } from '../components/ui/States.jsx'
import VoiceTestPanel from '../components/voice/VoiceTestPanel.jsx'
import { useResource } from '../hooks/useResource.js'
import { AGENT_LANGUAGES, languageLabel, voiceLanguageFor } from '../utils/languages.js'

const NO_AGENT = ''

export default function PlaygroundPage() {
  const fetchAgents = useCallback((signal) => api.agents.list({ limit: 100, offset: 0 }, { signal }), [])
  const { data: agents, error, loading, reload } = useResource(fetchAgents)
  const [agentId, setAgentId] = useState(NO_AGENT)
  const [languageTag, setLanguageTag] = useState('en')

  const agent = agents?.find((item) => item.id === agentId) ?? null

  function chooseAgent(event) {
    const id = event.target.value
    setAgentId(id)
    const chosen = agents?.find((item) => item.id === id)
    if (chosen && voiceLanguageFor(chosen.language)) setLanguageTag(chosen.language) // the agent's language is a starting point
  }

  const voiceLanguage = voiceLanguageFor(languageTag)

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Voice playground</h2>
          <p>Try the voice pipeline in a language of your choice. Pick an agent to start from its language.</p>
        </div>
      </div>

      {error && <ErrorState error={error} title="We couldn’t load your agents" onRetry={reload} />}

      <div className="card form-grid">
        <Field as="select" label="Agent" value={agentId} onChange={chooseAgent} disabled={loading} hint="Optional. The voice service does not use the agent’s instructions yet.">
          <option value={NO_AGENT}>{loading ? 'Loading agents…' : 'No agent (general test)'}</option>
          {(agents ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </Field>
        <Field as="select" label="Language" value={languageTag} onChange={(event) => setLanguageTag(event.target.value)}>
          {AGENT_LANGUAGES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Field>
      </div>

      {agent && agent.language !== languageTag && (
        <Alert tone="info">
          You’re testing in {languageLabel(languageTag)}, not the agent’s own language ({languageLabel(agent.language)}).
        </Alert>
      )}

      <VoiceTestPanel
        agentName={agent ? agent.name : 'None (general test)'}
        languageText={languageLabel(languageTag)}
        voiceLanguage={voiceLanguage}
        unsupportedMessage="Choose English, Hindi or Hinglish."
      />
    </div>
  )
}
