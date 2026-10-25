import { Eraser, FileText, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { MAX_SYSTEM_PROMPT } from '../../utils/agentForm.js'
import { AGENT_TEMPLATES } from '../../utils/agentTemplates.js'
import Button from '../ui/Button.jsx'
import ConfirmDialog from '../ui/ConfirmDialog.jsx'
import DropdownMenu from '../ui/DropdownMenu.jsx'
import Field from '../ui/Field.jsx'

/**
 * The system prompt editor: a large monospace textarea with a character counter, writing guidance, optional prompt
 * templates, and clear / reset actions that ask first. `savedValue` is the prompt as stored on the server.
 */
export default function PromptEditor({ value, savedValue, error, onChange }) {
  const [pending, setPending] = useState(null) // { kind: 'clear' | 'reset' | 'template', text?, label? }
  const over = value.length > MAX_SYSTEM_PROMPT
  const changed = value !== savedValue

  function choose(kind, text = '', label = '') {
    // Only ask when something would actually be lost.
    if (!value.trim() || (kind === 'reset' && !changed)) return apply(kind, text)
    setPending({ kind, text, label })
  }

  function apply(kind, text) {
    if (kind === 'clear') onChange('')
    else if (kind === 'reset') onChange(savedValue)
    else onChange(text)
    setPending(null)
  }

  const templateItems = AGENT_TEMPLATES.map((template) => ({
    label: template.label,
    icon: FileText,
    onSelect: () => choose('template', template.systemPrompt, template.label),
  }))

  const copy = {
    clear: ['Clear the system prompt?', 'The prompt is emptied. You can still reset it to the saved version until you save.', 'Clear'],
    reset: ['Discard your edits to the prompt?', 'The prompt goes back to the saved version.', 'Discard edits'],
    template: ['Replace the prompt with this template?', pending?.label ? `“${pending.label}” replaces what you have written. Reset brings the saved version back.` : '', 'Replace'],
  }[pending?.kind ?? 'clear']

  return (
    <div className="prompt-editor">
      <div className="prompt-toolbar">
        <DropdownMenu label="Insert a prompt template" align="left" trigger={<span className="btn btn-sm">Templates</span>} items={templateItems} />
        <Button size="sm" variant="ghost" icon={Undo2} onClick={() => choose('reset')} disabled={!changed}>
          Reset
        </Button>
        <Button size="sm" variant="ghost" icon={Eraser} onClick={() => choose('clear')} disabled={!value}>
          Clear
        </Button>
        <span className={`counter${over ? ' is-over' : ''}`} aria-live="polite">
          {value.length.toLocaleString('en-US')} / {MAX_SYSTEM_PROMPT.toLocaleString('en-US')} characters
        </span>
      </div>
      <Field
        as="textarea"
        rows={16}
        label="System prompt"
        className="prompt-field"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        error={error}
        spellCheck={false}
        placeholder="You are a friendly receptionist for a dental clinic. Help callers book, move or cancel appointments…"
      />
      <details className="guidance">
        <summary>Prompt-writing guidance</summary>
        <ul>
          <li>Say who the agent is and who it is talking to.</li>
          <li>Describe the task, the tone, and how long answers should be: short sentences work best when spoken.</li>
          <li>List what the agent must never do, and when it should hand over to a person.</li>
          <li>Put the facts it needs (opening hours, policies) in the prompt: knowledge sources are not available yet.</li>
        </ul>
      </details>

      <ConfirmDialog
        open={Boolean(pending)}
        title={copy[0]}
        confirmLabel={copy[2]}
        tone="primary"
        onConfirm={() => apply(pending.kind, pending.text)}
        onCancel={() => setPending(null)}
      >
        {copy[1]}
      </ConfirmDialog>
    </div>
  )
}
