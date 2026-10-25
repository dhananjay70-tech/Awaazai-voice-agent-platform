import { Phone, PhoneIncoming, Router } from 'lucide-react'
import { ComingSoonButton, ComingSoonNotice } from '../components/ui/ComingSoon.jsx'
import { EmptyState } from '../components/ui/States.jsx'

// Ways a number could be connected later. None is available, and none names a provider that is not integrated.
const OPTIONS = [
  { icon: PhoneIncoming, title: 'Get a number', text: 'Choose a number from a telephony provider and route its calls to an agent.', action: 'Get a number' },
  { icon: Router, title: 'Bring your own', text: 'Connect an existing number or SIP trunk you already have.', action: 'Connect a number' },
]

const SETUP = [
  'A telephony service that can stream call audio to AwaazAI.',
  'A way to route each number to a specific agent.',
  'Secure authentication on the voice service (it currently has none and only runs locally).',
]

export default function PhoneNumbersPage() {
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Phone numbers</h2>
          <p>Let customers call your agents directly.</p>
        </div>
      </div>

      <ComingSoonNotice title="Phone numbers are not available yet">There is no telephony service in this version, so no numbers can be added or connected.</ComingSoonNotice>

      <div className="source-grid">
        {OPTIONS.map(({ icon: Icon, title, text, action }) => (
          <section className="card source-card" key={title} aria-label={title}>
            <span className="state-icon">
              <Icon size={22} aria-hidden="true" />
            </span>
            <h3>{title}</h3>
            <p>{text}</p>
            <span className="badge">Not available</span>
            <ComingSoonButton icon={Phone}>{action}</ComingSoonButton>
          </section>
        ))}
      </div>

      <section className="card page-stack" aria-labelledby="pn-numbers" style={{ gap: 'var(--space-4)' }}>
        <h3 className="section-title" id="pn-numbers">
          Your numbers
        </h3>
        <EmptyState icon={Phone} title="No phone numbers">
          Connected numbers will appear here with their agent and status.
        </EmptyState>
      </section>

      <section className="card" aria-labelledby="pn-setup">
        <h3 className="section-title" id="pn-setup" style={{ marginBottom: 'var(--space-4)' }}>
          What setup will need
        </h3>
        <ol className="steps">
          {SETUP.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      </section>
    </div>
  )
}
