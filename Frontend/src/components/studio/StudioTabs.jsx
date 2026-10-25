import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { AGENT_LANGUAGES } from '../../utils/languages.js'
import { loadFirstMessageDraft } from '../../utils/firstMessage.js'
import { MAX_DESCRIPTION, MAX_NAME, MAX_SPEED, MAX_SYSTEM_PROMPT, MIN_SPEED } from '../../utils/agentForm.js'
import KnowledgeSources from '../knowledge/KnowledgeSources.jsx'
import Alert from '../ui/Alert.jsx'
import Button from '../ui/Button.jsx'
import { ComingSoonNotice } from '../ui/ComingSoon.jsx'
import Field from '../ui/Field.jsx'
import ConfigPanel from './ConfigPanel.jsx'

// The studio tabs below the Agent tab. None of them has a backend yet, so each says what is missing and links to the
// page that explains it; nothing here can be saved, run or "connected".

export function WorkflowTab() {
  return (
    <ConfigPanel title="Workflow" description="Route a conversation through steps, conditions and hand-offs.">
      <ComingSoonNotice title="Workflows are not available yet">
        There is no workflow engine in the backend or the voice service, so a workflow cannot be saved or run for this agent.
      </ComingSoonNotice>
      <div>
        <Button to="/workflows" icon={ExternalLink}>
          See the workflow preview
        </Button>
      </div>
    </ConfigPanel>
  )
}

export function KnowledgeTab({ agent }) {
  return <KnowledgeSources agentName={agent.name} />
}

export function AnalysisTab() {
  return (
    <ConfigPanel title="Analysis" description="Evaluate conversations against your own criteria and collect data from them.">
      <ComingSoonNotice title="Analysis is not available yet">
        Conversations are not recorded, so there is nothing to analyse. This needs a conversation-history service and an evaluation service.
      </ComingSoonNotice>
    </ConfigPanel>
  )
}

export function ToolsTab() {
  return (
    <ConfigPanel title="Tools" description="Let the agent call APIs and functions during a conversation.">
      <ComingSoonNotice title="Tools are not available yet">
        Tools need server-side storage, authorisation and request validation that do not exist yet. Nothing here can be attached to the agent.
      </ComingSoonNotice>
      <div>
        <Button to="/tools" icon={ExternalLink}>
          Open Tools
        </Button>
      </div>
    </ConfigPanel>
  )
}

export function TestsTab() {
  return (
    <ConfigPanel title="Tests" description="Check that the agent behaves as expected after every change.">
      <ComingSoonNotice title="Automated tests are not available yet">There is no evaluation service, so no test has been run and no result is shown.</ComingSoonNotice>
      <div>
        <Button to="/tests" icon={ExternalLink}>
          Open Tests
        </Button>
      </div>
    </ConfigPanel>
  )
}

const POSITIONS = [
  { value: 'bottom-right', label: 'Bottom right' },
  { value: 'bottom-left', label: 'Bottom left' },
]

export function WidgetTab({ agent }) {
  const [position, setPosition] = useState('bottom-right')
  const [theme, setTheme] = useState('dark')
  const [greeting, setGreeting] = useState(() => loadFirstMessageDraft(agent.id) || 'Hi! How can I help?')
  const [startMode, setStartMode] = useState('click')

  return (
    <ConfigPanel title="Widget" description="A chat-and-voice button for your website.">
      <Alert tone="warning" title="Visual preview only">
        The embeddable widget is not built. The controls below only change the preview on this page: nothing is saved, and there is no embed code because a widget would need a secure, short-lived voice session from
        the backend.
      </Alert>
      <div className="widget-layout">
        <div className="page-stack" style={{ gap: 'var(--space-4)' }}>
          <Field as="select" label="Position" value={position} onChange={(event) => setPosition(event.target.value)}>
            {POSITIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Field>
          <Field as="select" label="Theme" value={theme} onChange={(event) => setTheme(event.target.value)}>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </Field>
          <Field label="Greeting" value={greeting} onChange={(event) => setGreeting(event.target.value)} maxLength={120} />
          <Field label="Language" value={AGENT_LANGUAGES.find((item) => item.value === agent.language)?.label ?? agent.language} readOnly hint="Follows the agent’s language." />
          <Field as="select" label="Start behaviour" value={startMode} onChange={(event) => setStartMode(event.target.value)}>
            <option value="click">Start when the visitor clicks</option>
            <option value="open">Open the panel when the page loads</option>
          </Field>
          <div>
            <Button disabled title="The widget is not implemented">
              Copy embed code
            </Button>
            <p className="field-hint">Embed code is not available.</p>
          </div>
        </div>

        <div className={`widget-stage theme-${theme}`} role="img" aria-label="Visual preview of the website widget">
          <span className="widget-site">Your website</span>
          <div className={`widget-bubble ${position}`}>
            {startMode === 'open' && <div className="widget-panel">{greeting || '…'}</div>}
            <span className="widget-button">{startMode === 'click' ? greeting || '…' : 'Chat'}</span>
          </div>
        </div>
      </div>
    </ConfigPanel>
  )
}

function StatusRow({ title, badge, tone, children }) {
  return (
    <div className="status-row">
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
      <span className={`badge ${tone}`}>{badge}</span>
    </div>
  )
}

export function SecurityTab() {
  return (
    <ConfigPanel title="Security" description="What protects this agent today, and what is not configured.">
      <div className="status-rows">
        <StatusRow title="Agent configuration access" badge="Active" tone="badge-success">
          Your agents can only be read and changed by your own signed-in account. The server checks this on every request.
        </StatusRow>
        <StatusRow title="Voice session authentication" badge="Not configured" tone="badge-warning">
          The voice service has no authentication of its own. A safe setup needs the backend to issue a short-lived session ticket for one agent and the voice service to verify it. Until then the voice test only
          works against a service on your own machine.
        </StatusRow>
        <StatusRow title="Allowed origins" badge="Not configured" tone="badge-warning">
          Per-agent origin rules do not exist. The voice service has one global list of allowed browser origins, set in its server configuration.
        </StatusRow>
        <StatusRow title="Session expiration" badge="Not configured" tone="badge-warning">
          Voice sessions have no expiry setting. Your sign-in lasts 30 minutes and is kept in memory only.
        </StatusRow>
      </div>
      <Alert tone="info" title="Guidance">
        Never put provider API keys in the browser or in an agent’s prompt. Do not expose the voice service to the public internet until session tickets are in place.
      </Alert>
    </ConfigPanel>
  )
}

export function AdvancedTab({ onOpenAgentTab }) {
  return (
    <div className="config-stack">
      <ConfigPanel title="Language behaviour" description="How an agent language becomes a voice mode.">
        <p className="field-hint">The backend stores a language tag; the voice service expects one of three modes. This mapping is applied automatically.</p>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Stored tag</th>
              <th scope="col">Language</th>
              <th scope="col">Voice mode</th>
            </tr>
          </thead>
          <tbody>
            {AGENT_LANGUAGES.map((language) => (
              <tr key={language.value}>
                <td>
                  <code>{language.value}</code>
                </td>
                <td>{language.label}</td>
                <td>
                  <code>{language.voiceLanguage}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="field-hint">Any other tag can be stored but cannot be voice-tested.</p>
      </ConfigPanel>

      <ConfigPanel title="Limits enforced by the backend" description="Read-only reference for what a save will accept.">
        <ul className="feature-list">
          <li>Name: 1 to {MAX_NAME} characters, unique per account.</li>
          <li>Description: up to {MAX_DESCRIPTION} characters.</li>
          <li>System prompt: 1 to {MAX_SYSTEM_PROMPT.toLocaleString('en-US')} characters.</li>
          <li>
            Voice speed: {MIN_SPEED} to {MAX_SPEED}. <button type="button" className="link-button" onClick={onOpenAgentTab}>Change it on the Agent tab</button>.
          </li>
        </ul>
      </ConfigPanel>

      <ConfigPanel title="Not exposed" description="Parameters that would be silently ignored are left out on purpose.">
        <p className="field-hint">Response timing, interruption behaviour, session length and model parameters are not validated by the backend and not read by the voice pipeline, so there are no controls for them.</p>
      </ConfigPanel>
    </div>
  )
}
