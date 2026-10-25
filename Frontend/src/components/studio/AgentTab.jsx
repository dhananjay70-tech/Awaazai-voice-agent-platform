import { Check, Info, Volume2 } from 'lucide-react'
import { useId, useState } from 'react'
import { MAX_DESCRIPTION, MAX_NAME, MAX_SPEED, MIN_SPEED } from '../../utils/agentForm.js'
import { loadFirstMessageDraft, MAX_FIRST_MESSAGE, saveFirstMessageDraft } from '../../utils/firstMessage.js'
import { languageLabel, languageOptions, voiceLanguageFor } from '../../utils/languages.js'
import Alert from '../ui/Alert.jsx'
import Field, { Switch } from '../ui/Field.jsx'
import ConfigPanel from './ConfigPanel.jsx'
import PromptEditor from './PromptEditor.jsx'

function Counter({ value, max }) {
  return (
    <p className={`counter${value > max ? ' is-over' : ''}`} aria-live="polite">
      {value.toLocaleString('en-US')} / {max.toLocaleString('en-US')} characters
    </p>
  )
}

/** The first-message draft lives in this browser only: the backend has no field for it (see utils/firstMessage.js). */
function FirstMessage({ agentId }) {
  const [text, setText] = useState(() => loadFirstMessageDraft(agentId))
  const [stored, setStored] = useState(() => Boolean(loadFirstMessageDraft(agentId)))

  function change(event) {
    const value = event.target.value
    setText(value)
    setStored(saveFirstMessageDraft(agentId, value)) // a plain local write, not an API request
  }

  return (
    <ConfigPanel title="First message" description="What the agent says when a conversation starts." id="first-message">
      <Alert tone="warning" title="Local draft: not saved to your agent">
        The backend has no first-message field and the voice service cannot use one yet. This text is kept in this browser only so you don’t lose it. It is not sent to the server and does not change how the
        agent behaves.
      </Alert>
      <div>
        <Field as="textarea" rows={3} label="Greeting" value={text} onChange={change} maxLength={MAX_FIRST_MESSAGE} placeholder="Hello! How can I help you today?" />
        <Counter value={text.length} max={MAX_FIRST_MESSAGE} />
        {text && (
          <p className="field-hint" role="status">
            {stored ? 'Draft kept in this browser.' : 'This browser blocks storage, so the draft will be lost when you leave.'}
          </p>
        )}
      </div>
    </ConfigPanel>
  )
}

function VoiceSettings({ agent, form, errors, set }) {
  const speedId = useId()
  const savedVoice = agent.voice_config
  const voiceMode = voiceLanguageFor(form.language)
  return (
    <ConfigPanel title="Voice and language" description="Language, voice and speaking speed." id="voice-settings">
      <div className="voice-current" aria-label="Current selection">
        <Volume2 size={18} aria-hidden="true" />
        <div>
          <strong>
            {savedVoice.provider || 'Default provider'} · {savedVoice.voice_id || 'default voice'}
          </strong>
          <small>
            Saved: {languageLabel(agent.language)} · speed {savedVoice.speed}
          </small>
        </div>
        <span className="badge badge-success">
          <Check size={12} aria-hidden="true" /> Selected
        </span>
      </div>

      <Field as="select" label="Language" value={form.language} onChange={set('language')} error={errors.language}>
        {languageOptions(form.language).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Field>
      <p className="field-hint">
        <Info size={13} aria-hidden="true" style={{ verticalAlign: '-2px' }} /> Stored as the tag <code>{form.language}</code>; the voice service uses the mode{' '}
        <code>{voiceMode ?? 'none (unsupported)'}</code>.
      </p>

      <Alert tone="warning" title="Saved, but not yet applied">
        The voice service does not read an agent’s voice settings yet, and the provider and voice ID are not checked against any provider.
      </Alert>
      <div className="form-grid">
        <Field label="Voice provider (optional)" value={form.voiceProvider} onChange={set('voiceProvider')} error={errors.voiceProvider} autoComplete="off" />
        <Field label="Voice ID (optional)" value={form.voiceId} onChange={set('voiceId')} error={errors.voiceId} autoComplete="off" />
      </div>
      <div className="field">
        <label className="field-label" htmlFor={speedId}>
          Speaking speed
        </label>
        <div className="range-row">
          <input id={speedId} type="range" min={MIN_SPEED} max={MAX_SPEED} step="0.1" value={form.speed} onChange={set('speed')} aria-describedby={`${speedId}-hint`} />
          <input
            className="input"
            type="number"
            min={MIN_SPEED}
            max={MAX_SPEED}
            step="0.1"
            value={form.speed}
            onChange={set('speed')}
            aria-label="Speaking speed value"
            aria-invalid={errors.speed ? 'true' : undefined}
          />
        </div>
        <p className="field-hint" id={`${speedId}-hint`}>
          Between {MIN_SPEED} and {MAX_SPEED}. 1.0 is normal speed.
        </p>
        {errors.speed && (
          <p className="field-error" role="alert">
            {errors.speed}
          </p>
        )}
      </div>
      <div>
        <button type="button" className="btn btn-sm" disabled title="No voice preview service exists yet">
          Preview voice
        </button>
        <p className="field-hint">Voice preview isn’t available: there is no preview service that returns playable audio.</p>
      </div>
    </ConfigPanel>
  )
}

/** The default Agent Studio tab: details, system prompt, first message and voice settings. */
export default function AgentTab({ agent, form, errors, set, setField }) {
  return (
    <div className="config-stack">
      <ConfigPanel title="Agent details" description="How this agent is named and whether it is switched on." id="details">
        <Field
          label="Agent name"
          value={form.name}
          onChange={set('name')}
          error={errors.name}
          hint={`Up to ${MAX_NAME} characters. Each agent name must be unique in your account.`}
          autoComplete="off"
          required
        />
        <div>
          <Field as="textarea" rows={2} label="Description (optional)" value={form.description} onChange={set('description')} error={errors.description} hint="Shown on your agents list. Visible only to you." />
          <Counter value={form.description.length} max={MAX_DESCRIPTION} />
        </div>
        <Switch label={form.isActive ? 'Active' : 'Inactive'} checked={form.isActive} onChange={(value) => setField('isActive', value)} />
      </ConfigPanel>

      <ConfigPanel title="System prompt" description="The agent’s instructions: its personality, task and limits." id="prompt">
        <PromptEditor value={form.systemPrompt} savedValue={agent.system_prompt} error={errors.systemPrompt} onChange={(value) => setField('systemPrompt', value)} />
      </ConfigPanel>

      <FirstMessage agentId={agent.id} />

      <VoiceSettings agent={agent} form={form} errors={errors} set={set} />
    </div>
  )
}
