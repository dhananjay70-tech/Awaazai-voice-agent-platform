import { Bell, CalendarCheck, Mic, Plus, Zap } from 'lucide-react'
import { useState } from 'react'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

// A fixed, illustrative example. Nothing here is stored, sent or run.
const DEMO_STEPS = [
  { id: 'trigger', kind: 'Trigger', icon: Mic, title: 'Call ends', detail: 'Starts when a conversation with the agent finishes.' },
  { id: 'condition', kind: 'Condition', icon: Zap, title: 'Caller asked to book', detail: 'Continues only if the caller wanted an appointment.' },
  { id: 'action', kind: 'Action', icon: CalendarCheck, title: 'Create calendar event', detail: 'Adds the appointment to a connected calendar.' },
  { id: 'notify', kind: 'Action', icon: Bell, title: 'Send confirmation', detail: 'Messages the caller with the booking details.' },
]

export default function WorkflowsPage() {
  const [selected, setSelected] = useState('trigger')
  const step = DEMO_STEPS.find((item) => item.id === selected)

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Workflows</h2>
          <p>Automate what happens before, during and after a conversation.</p>
        </div>
        <ComingSoonButton icon={Plus}>Create workflow</ComingSoonButton>
      </div>

      <ComingSoonNotice title="Workflows are not available yet">
        There is no workflow service in this version, so nothing can be saved or run. The example below is a demonstration only.
      </ComingSoonNotice>

      <section className="card page-stack" aria-labelledby="wf-list" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="wf-list">
          Your workflows
        </h3>
        <EmptyState icon={Zap} title="No workflows">
          Saved workflows will be listed here with their trigger and status.
        </EmptyState>
      </section>

      <section className="card page-stack" aria-labelledby="wf-demo" style={{ gap: 'var(--space-4)' }}>
        <div className="section-head" style={{ marginBottom: 0 }}>
          <h3 className="section-title" id="wf-demo">
            Example: book an appointment
          </h3>
          <span className="badge badge-warning">Demonstration · not saved · not running</span>
        </div>
        <ol className="workflow-chain" aria-label="Example workflow steps">
          {DEMO_STEPS.map(({ id, kind, icon: Icon, title }) => (
            <li key={id}>
              <button type="button" className="workflow-node" aria-pressed={selected === id} onClick={() => setSelected(id)}>
                <Icon size={18} aria-hidden="true" />
                <span>
                  <small>{kind}</small>
                  {title}
                </span>
              </button>
            </li>
          ))}
        </ol>
        <div className="workflow-detail" role="status" aria-live="polite">
          <strong>
            {step.kind}: {step.title}
          </strong>
          <p>{step.detail}</p>
        </div>
      </section>
    </div>
  )
}
