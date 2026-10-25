import { ArrowLeft, Settings2 } from 'lucide-react'
import AgentLoader from '../components/agents/AgentLoader.jsx'
import Alert from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import VoiceTestPanel from '../components/voice/VoiceTestPanel.jsx'
import { languageLabel, voiceLanguageFor } from '../utils/languages.js'

function Talk({ agent }) {
  const voiceLanguage = voiceLanguageFor(agent.language)
  return (
    <div className="page-stack">
      <div className="editor-bar">
        <Button to={`/agents/${agent.id}`} variant="ghost" icon={ArrowLeft}>
          Back to the studio
        </Button>
        <span className="muted">
          Testing <strong>{agent.name}</strong>
        </span>
      </div>
      <VoiceTestPanel
        agentName={agent.name}
        languageText={languageLabel(agent.language)}
        voiceLanguage={voiceLanguage}
        unsupportedMessage={`The agent’s language “${agent.language}” has no matching voice mode. Change it to English, Hindi or Hinglish in the studio to test it.`}
        agentNote={
          <>
            {!agent.is_active && <Alert tone="info">This agent is inactive. The voice test still works while it is switched off.</Alert>}
            {!voiceLanguage && (
              <div>
                <Button to={`/agents/${agent.id}`} icon={Settings2} variant="outline">
                  Open the studio
                </Button>
              </div>
            )}
          </>
        }
      />
    </div>
  )
}

/** /agents/:id/talk: the full-page live playground scoped to one agent. The agent id stays in the URL. */
export default function AgentTalkPage() {
  return <AgentLoader>{(agent) => <Talk agent={agent} />}</AgentLoader>
}
