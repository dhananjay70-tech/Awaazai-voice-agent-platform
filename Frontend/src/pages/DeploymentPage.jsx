import { Code2, Globe, Phone } from 'lucide-react'
import Button from '../components/ui/Button.jsx'
import { ComingSoonNotice } from '../components/ui/ComingSoon.jsx'

const CHANNELS = [
  {
    icon: Globe,
    title: 'Website widget',
    badge: 'Visual preview only',
    tone: 'badge-warning',
    text: 'A voice and chat button for your site. The widget is not built; each agent’s Widget tab shows a preview.',
  },
  {
    icon: Phone,
    title: 'Phone',
    badge: 'Not available',
    tone: 'badge-warning',
    text: 'Inbound and outbound calls need a telephony provider and backend support.',
    to: '/phone-numbers',
    action: 'Phone numbers',
  },
  {
    icon: Code2,
    title: 'API',
    badge: 'Agent management only',
    tone: '',
    text: 'You can create and manage agents over the REST API. Starting a voice conversation through the API needs a session ticket that is not implemented.',
  },
]

export default function DeploymentPage() {
  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <h2>Deployment</h2>
          <p>Where your agents can talk to customers.</p>
        </div>
      </div>

      <ComingSoonNotice title="Nothing can be deployed yet">
        Deploying an agent needs secure, short-lived voice sessions issued by the backend. Until then agents can only be tried locally in the playground, and no channel below is live.
      </ComingSoonNotice>

      <div className="source-grid">
        {CHANNELS.map(({ icon: Icon, title, badge, tone, text, to, action }) => (
          <section className="card source-card" key={title} aria-label={title}>
            <span className="state-icon">
              <Icon size={22} aria-hidden="true" />
            </span>
            <h3>{title}</h3>
            <p>{text}</p>
            <span className={`badge ${tone}`}>{badge}</span>
            {to && (
              <Button to={to} size="sm">
                {action}
              </Button>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
