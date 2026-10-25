import { Check } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/index.js'
import { ApiError, fieldErrorsFrom } from '../api/client.js'
import { ErrorAlert } from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import Field from '../components/ui/Field.jsx'
import { useToast } from '../components/ui/ToastContext.js'
import { useAgentFormState } from '../hooks/useAgentForm.js'
import { useUnsavedChangesGuard } from '../hooks/useUnsavedChangesGuard.jsx'
import { backendFieldsToForm, emptyAgentForm, formToCreatePayload, isDirty, MAX_DESCRIPTION, MAX_NAME, MAX_SYSTEM_PROMPT, validateAgentForm } from '../utils/agentForm.js'
import { AGENT_TEMPLATES, templateById, templateToFormValues } from '../utils/agentTemplates.js'
import { saveFirstMessageDraft } from '../utils/firstMessage.js'
import { languageOptions } from '../utils/languages.js'

const BLANK = emptyAgentForm()

export default function NewAgentPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { form, setForm, errors, setErrors, set } = useAgentFormState(BLANK)
  const [templateId, setTemplateId] = useState('blank')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState(null)
  const inFlight = useRef(false)
  const { dialog, allowLeave } = useUnsavedChangesGuard(isDirty(form, BLANK))

  // A template fills the real form fields; everything stays editable and nothing is saved until "Create agent".
  function chooseTemplate(id) {
    setTemplateId(id)
    const template = templateById(id)
    setErrors({})
    setForm(template ? { ...form, ...templateToFormValues(template) } : { ...form, name: '', description: '', systemPrompt: '' })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (inFlight.current) return
    const found = validateAgentForm(form)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    inFlight.current = true
    setCreating(true)
    setCreateError(null)
    try {
      const created = await api.agents.create(formToCreatePayload(form))
      const template = templateById(templateId)
      if (template) saveFirstMessageDraft(created.id, template.firstMessage) // a local draft: the backend has no such field
      allowLeave()
      toast.success(`Created “${created.name}”.`)
      navigate(`/agents/${created.id}`)
    } catch (error) {
      setCreateError(error)
      if (error instanceof ApiError) {
        const mapped = backendFieldsToForm(fieldErrorsFrom(error))
        if (error.code === 'agent_name_conflict') mapped.name = error.message
        if (Object.keys(mapped).length > 0) setErrors(mapped)
      }
    } finally {
      inFlight.current = false
      setCreating(false)
    }
  }

  return (
    <form className="page-stack" onSubmit={handleSubmit} noValidate style={{ maxWidth: 'var(--width-narrow)' }}>
      <div className="page-intro">
        <div>
          <h2>Create an agent</h2>
          <p>Pick a starting point or begin from scratch. You can change everything in the studio afterwards.</p>
        </div>
      </div>

      <fieldset className="template-picker">
        <legend className="field-label">Starter template</legend>
        <div className="template-grid">
          {[{ id: 'blank', label: 'Blank', summary: 'Start with an empty agent.' }, ...AGENT_TEMPLATES].map((template) => (
            <label key={template.id} className={`template-card${templateId === template.id ? ' is-selected' : ''}`}>
              <input type="radio" name="template" value={template.id} checked={templateId === template.id} onChange={() => chooseTemplate(template.id)} />
              <span className="template-title">
                {template.label}
                {templateId === template.id && <Check size={15} aria-hidden="true" />}
              </span>
              <span className="template-summary">{template.summary}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <ErrorAlert error={createError} title="Could not create the agent" />

      <div className="card editor-panel">
        <Field
          label="Agent name"
          value={form.name}
          onChange={set('name')}
          error={errors.name}
          hint={`Up to ${MAX_NAME} characters. Must be unique in your account.`}
          autoComplete="off"
          placeholder="Appointment assistant"
          required
        />
        <Field as="textarea" rows={2} label="Description (optional)" value={form.description} onChange={set('description')} error={errors.description} hint={`Up to ${MAX_DESCRIPTION} characters.`} />
        <Field as="select" label="Language" value={form.language} onChange={set('language')} error={errors.language}>
          {languageOptions(form.language).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Field>
        <div>
          <Field
            as="textarea"
            rows={8}
            label="System prompt"
            value={form.systemPrompt}
            onChange={set('systemPrompt')}
            error={errors.systemPrompt}
            hint="The agent’s instructions. Required: edit the template’s text or write your own."
            spellCheck={false}
          />
          <p className={`counter${form.systemPrompt.length > MAX_SYSTEM_PROMPT ? ' is-over' : ''}`}>
            {form.systemPrompt.length.toLocaleString('en-US')} / {MAX_SYSTEM_PROMPT.toLocaleString('en-US')} characters
          </p>
        </div>
      </div>

      <div className="wizard-actions">
        <Button to="/agents" variant="ghost">
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={creating}>
          {creating ? 'Creating…' : 'Create agent'}
        </Button>
      </div>
      {dialog}
    </form>
  )
}
