import { Code2, Globe, Plug, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import Alert from '../components/ui/Alert.jsx'
import Button from '../components/ui/Button.jsx'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import Field from '../components/ui/Field.jsx'
import { EmptyState } from '../components/ui/States.jsx'

const TOOL_TYPES = [
  { icon: Globe, title: 'HTTP API request', text: 'Call an API from the conversation, for example to look up an order.' },
  { icon: Code2, title: 'Custom function', text: 'Run your own code for logic the agent should not guess.' },
  { icon: Plug, title: 'Application integration', text: 'Use a connected business application.' },
]

const AUTH_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'header', label: 'Custom header' },
]

let nextRow = 1

/**
 * Preview of the tool configuration form. It is local state only: nothing here is saved, validated by a server or
 * executed, and credentials are never collected on this page.
 */
function ToolFormPreview() {
  const [method, setMethod] = useState('GET')
  const [auth, setAuth] = useState('none')
  const [params, setParams] = useState([{ id: nextRow++, name: '', type: 'string', description: '' }])

  const update = (id, key) => (event) => setParams((rows) => rows.map((row) => (row.id === id ? { ...row, [key]: event.target.value } : row)))

  return (
    <section className="card page-stack" aria-labelledby="tool-form" style={{ gap: 'var(--space-4)' }}>
      <div className="section-head" style={{ marginBottom: 0 }}>
        <h3 className="section-title" id="tool-form">
          Tool configuration
        </h3>
        <span className="badge badge-warning">Preview · cannot be saved</span>
      </div>
      <div className="form-grid">
        <Field label="Name" placeholder="lookup_order" autoComplete="off" />
        <Field as="select" label="Method" value={method} onChange={(event) => setMethod(event.target.value)}>
          {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((name) => (
            <option key={name}>{name}</option>
          ))}
        </Field>
      </div>
      <Field label="Description" placeholder="When should the agent use this tool?" autoComplete="off" />
      <Field label="URL" placeholder="https://api.example.com/orders/{order_id}" autoComplete="off" hint="Server-side validation and SSRF protection are required before any tool can call a URL." />

      <fieldset className="param-table">
        <legend className="field-label">Parameter schema</legend>
        {params.map((row, index) => (
          <div className="param-row" key={row.id}>
            <Field label={`Parameter ${index + 1} name`} value={row.name} onChange={update(row.id, 'name')} autoComplete="off" />
            <Field as="select" label={`Parameter ${index + 1} type`} value={row.type} onChange={update(row.id, 'type')}>
              {['string', 'number', 'boolean'].map((type) => (
                <option key={type}>{type}</option>
              ))}
            </Field>
            <Field label={`Parameter ${index + 1} description`} value={row.description} onChange={update(row.id, 'description')} autoComplete="off" />
            <Button variant="ghost" icon={Trash2} aria-label={`Remove parameter ${index + 1}`} onClick={() => setParams((rows) => rows.filter((item) => item.id !== row.id))} />
          </div>
        ))}
        <Button size="sm" icon={Plus} onClick={() => setParams((rows) => [...rows, { id: nextRow++, name: '', type: 'string', description: '' }])}>
          Add parameter
        </Button>
      </fieldset>

      <Field as="select" label="Authentication" value={auth} onChange={(event) => setAuth(event.target.value)}>
        {AUTH_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Field>
      {auth !== 'none' && (
        <Alert tone="info" title="Secrets are never entered here">
          Credentials must be stored on the server and referenced by name. This page does not collect a token or header value.
        </Alert>
      )}

      <div className="wizard-actions" style={{ justifyContent: 'flex-end' }}>
        <ComingSoonButton>Save tool</ComingSoonButton>
      </div>
    </section>
  )
}

export default function ToolsPage() {
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Tools</h2>
          <p>Actions an agent can take during a conversation, such as calling an API.</p>
        </div>
        <ComingSoonButton icon={Plus}>Add tool</ComingSoonButton>
      </div>

      <ComingSoonNotice title="Tools are not available yet">
        There is no place to store tools and no service to run them. Running a tool means the server calls an address on your behalf, which needs authorisation, secret storage and SSRF protection first.
      </ComingSoonNotice>

      <div className="source-grid">
        {TOOL_TYPES.map(({ icon: Icon, title, text }) => (
          <section className="card source-card" key={title} aria-label={title}>
            <span className="state-icon">
              <Icon size={22} aria-hidden="true" />
            </span>
            <h3>{title}</h3>
            <p>{text}</p>
            <span className="badge badge-warning">Setup required</span>
          </section>
        ))}
      </div>

      <section className="card page-stack" aria-labelledby="tool-list" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="tool-list">
          Your tools
        </h3>
        <EmptyState icon={Code2} title="No tools">
          Created tools will be listed here with edit and delete actions.
        </EmptyState>
      </section>

      <ToolFormPreview />
    </div>
  )
}
